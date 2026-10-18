"""Phase 2 CRNN fine-tune: Phase 1 synthetic SATB strips + Camera-PrIMuS replay (PIYA-106).

Ported from training/piyanota-training-ver-2.ipynb (code cells 6-10) with the logic kept: CameraPrIMuSDataset loading
and _augment, ctc_collate, the canary set (first 10% of the sorted CPM glob, the base run's own val slice) with its
bootstrap soft floor and 3x hard cap, explicit seeding with deterministic cuDNN and a seeded loader generator, AdamW +
cosine schedule, gradient clipping 5.0 and patience-based early stopping. What changes:
- The training pool is the Phase 1 train split (training/phase2/build_manifest.py) plus CPM replay. Each epoch draws
  every synthetic strip once and a fresh seeded CPM subset sized so CPM is --replay-ratio of the epoch. Canary stems
  are never in the replay pool (it is the forgetting probe).
- Selection and patience run on the piece-held-out synthetic val SER, not loo_font_ser: the val pieces never appear in
  training under any font, so this measures reading unseen music (ml-cv-lead condition 1, 2026-10-08).
- Each epoch also writes metrics.json with val SER per line_mult / interline tertile and per font, and LCS recall for
  the G2 watch classes (whole note, half rest, fermata, the final barline of a final system).
The canary baseline is measured on the --init checkpoint, as the notebook measured it on its start checkpoint.

Usage (Kaggle GPU, via training/phase2/kaggle/phase2_kernel.py, or locally):
  python training/phase2/train_phase2.py --recut-out <dir with strips/ and pages/> --cpm-root <CameraPrIMuS root>
      --init <checkpoint.pt> --seed 1 --out <dir> [--expect-manifest-sha <sha>] [--smoke]
--smoke runs a CPU-sized check (32 strips per pool, 2 steps, 1 epoch) and verifies save/reload gives identical logits.
Divisi arm (docs/decisions/piya-106-divisi-arm-freeze.md): --vocab-ext --divisi-recut-out <dir> --select-last; its
control: --control-rows N --select-last; head-only arm (amendment A2): add --head-only --lr 1e-3. With none of these
flags a run is Phase 2 unchanged.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
import torch
from torch.utils.data import ConcatDataset, DataLoader, Dataset, Sampler, Subset

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_manifest import FORBIDDEN_CLASS, WATCH_CLASSES, build, token_class  # noqa: E402
from stage3_transcription import (BLANK_IDX, CRNN, IDX_TO_SYM, SYM_TO_IDX, VOCAB, VOCAB_EXT_CHORD_TUPLET,  # noqa: E402
                                  VOCAB_SIZE, _greedy_ctc_decode, compute_ser)

BASE_VOCAB_SIZE = VOCAB_SIZE   # before use_ext_vocab() rebinds the tables
IMG_HEIGHT = 64
BATCH_SIZE = 16
CANARY_FRACTION = 0.1
CANARY_HARD_CAP_MULTIPLIER = 3.0       # notebook cell 8, 2026-09-15 amendment
# The notebook's canary (cell 11 output: 399 of 3,995 samples), pinned by the sha256 of its stems in order, so a
# different CPM mount or glob order fails loudly instead of moving the caps (ml-cv-lead P5 blocker 3).
CANARY_COUNT = 399
CANARY_STEMS_SHA256 = "dbe119c9c447dabfa27e95b6e4e8a9e9b6257bdb8d5027218063decf6b371365"
BOOTSTRAP_N, BOOTSTRAP_CI = 2000, 0.95
GRAD_CLIP = 5.0
WEIGHT_DECAY = 1e-4
GATE_MODE = "soft_diagnostic_hard_cap_v1"
SMOKE_N = 32
SMOKE_STEPS = 2
# Divisi arm head expansion (docs/decisions/piya-106-divisi-arm-freeze.md section 2).
NEW_HEAD_WEIGHT_STD = 0.01
NEW_HEAD_BIAS_STEP = 1.0
NEW_HEAD_MAX_BIAS_STEPS = 10
CHORDNOTE_PREFIX = "chordnote-"


# ---- data (notebook code cells 6 and 7) -------------------------------------------------------------------------

def ctc_collate(batch: list[tuple[torch.Tensor, torch.Tensor]]) -> tuple[torch.Tensor, ...]:
    images, labels = zip(*batch)
    max_w = max(img.shape[2] for img in images)
    padded = torch.zeros(len(images), 1, images[0].shape[1], max_w)
    for i, img in enumerate(images):
        padded[i, :, :, :img.shape[2]] = img
    input_lengths = torch.tensor([img.shape[2] // 4 for img in images], dtype=torch.long)
    label_lengths = torch.tensor([len(lb) for lb in labels], dtype=torch.long)
    return padded, torch.cat(labels), input_lengths, label_lengths


class StripDataset(Dataset):
    """(image_path, distorted_path_or_None, label_ids) rows; image loading and _augment are the notebook's
    CameraPrIMuSDataset unchanged. Phase 1 strips have no distorted variant, so they only get _augment when
    augment=True (the --augment-synth flag)."""

    def __init__(self, samples: list[tuple[str, str | None, list[int]]], augment: bool = False,
                 distorted_prob: float = 0.5, force_distorted: bool = False) -> None:
        self.samples = samples
        self.augment = augment
        self.distorted_prob = distorted_prob
        self.force_distorted = force_distorted

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        img_path, distorted_path, label = self.samples[idx]
        if self.force_distorted and distorted_path is not None:
            use_distorted = True
        elif self.augment and distorted_path is not None:
            use_distorted = np.random.rand() < self.distorted_prob
        else:
            use_distorted = False
        img = cv2.imread(distorted_path if use_distorted else img_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise RuntimeError(f"Could not read image: {img_path}")
        h, w = img.shape
        if h != IMG_HEIGHT:
            img = cv2.resize(img, (max(1, int(w * IMG_HEIGHT / h)), IMG_HEIGHT), interpolation=cv2.INTER_AREA)
        if self.augment:
            img = self._augment(img)
        img = (img.astype(np.float32) / 255.0 - 0.5) / 0.5
        return torch.tensor(img).unsqueeze(0), torch.tensor(label, dtype=torch.long)

    def _augment(self, img: np.ndarray) -> np.ndarray:
        img = np.clip(np.random.uniform(0.6, 1.4) * img + np.random.randint(-35, 35), 0, 255).astype(np.uint8)
        if np.random.rand() < 0.3:
            img = self._add_shadow(img)
        if np.random.rand() < 0.3:
            img = self._rotate(img, np.random.uniform(-3.0, 3.0))
        if np.random.rand() < 0.3:
            img = cv2.resize(img, (max(1, int(img.shape[1] * np.random.uniform(0.9, 1.1))), img.shape[0]))
        if np.random.rand() < 0.35:
            k = int(np.random.choice([3, 5, 7]))
            if np.random.rand() < 0.5:
                img = cv2.GaussianBlur(img, (k, k), 0)
            else:
                kernel = np.zeros((k, k), dtype=np.float32)
                kernel[k // 2, :] = 1.0 / k
                img = cv2.filter2D(img, -1, kernel)
        if np.random.rand() < 0.3:
            img = self._random_perspective(img)
        if np.random.rand() < 0.35:
            img = self._elastic_distort(img)
        return img

    @staticmethod
    def _rotate(img: np.ndarray, angle_deg: float) -> np.ndarray:
        h, w = img.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
        return cv2.warpAffine(img, m, (w, h), borderValue=255, flags=cv2.INTER_LINEAR)

    @staticmethod
    def _add_shadow(img: np.ndarray) -> np.ndarray:
        h, w = img.shape
        if np.random.rand() < 0.5:
            ramp = np.linspace(0, 1, w, dtype=np.float32)
            if np.random.rand() < 0.5:
                ramp = ramp[::-1]
            gradient = np.tile(ramp, (h, 1))
        else:
            ramp = np.linspace(0, 1, h, dtype=np.float32)
            if np.random.rand() < 0.5:
                ramp = ramp[::-1]
            gradient = np.tile(ramp.reshape(-1, 1), (1, w))
        darken = 1.0 - gradient * np.random.uniform(0.15, 0.45)
        return np.clip(img.astype(np.float32) * darken, 0, 255).astype(np.uint8)

    @staticmethod
    def _random_perspective(img: np.ndarray) -> np.ndarray:
        h, w = img.shape
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = (src + np.random.uniform(-0.04, 0.04, src.shape) * np.array([w, h])).astype(np.float32)
        return cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=255)

    @staticmethod
    def _elastic_distort(img: np.ndarray, alpha: float = 6.0, sigma: float = 4.0) -> np.ndarray:
        h, w = img.shape
        dx = cv2.GaussianBlur((np.random.rand(h, w).astype(np.float32) * 2 - 1), (0, 0), sigma) * alpha
        dy = cv2.GaussianBlur((np.random.rand(h, w).astype(np.float32) * 2 - 1), (0, 0), sigma) * alpha
        x, y = np.meshgrid(np.arange(w), np.arange(h))
        return cv2.remap(img, (x + dx).astype(np.float32), (y + dy).astype(np.float32),
                         interpolation=cv2.INTER_LINEAR, borderValue=255)


def cpm_samples(root: str) -> list[tuple[str, str | None, list[int]]]:
    """Notebook CameraPrIMuSDataset.__init__: sorted glob, so the canary slice is the base run's val slice."""
    out = []
    # Sorted on "/" separators so a Windows smoke run orders paths exactly as the Linux Kaggle kernel does.
    for agnostic_path in sorted(glob.glob(f"{root}/**/*.agnostic", recursive=True), key=lambda p: p.replace("\\", "/")):
        img_path = agnostic_path.replace(".agnostic", ".png")
        if not os.path.exists(img_path):
            continue
        distorted = agnostic_path.replace(".agnostic", "_distorted.jpg")
        with open(agnostic_path) as f:
            label = [SYM_TO_IDX.get(t, SYM_TO_IDX["<unk>"]) for t in f.read().split()]
        if label:
            out.append((img_path, distorted if os.path.exists(distorted) else None, label))
    return out


class ReplaySampler(Sampler[int]):
    """Per epoch: every synthetic index once plus a fresh draw of CPM indices, shuffled together. The generator is
    reseeded by run() exactly like the notebook reseeds the train loader, so a seed fixes the whole order.

    A6 divisi pool: indices [n_synth + n_pool, n_synth + n_pool + n_divisi_pool) are redrawn each epoch
    (n_divisi_per_epoch of them), so the model sees different divisi strips every epoch instead of one fixed subset.
    The divisi draw is skipped entirely when n_divisi_per_epoch is 0, so train-1 consumes the generator exactly as
    before and keeps its order for a given seed."""

    def __init__(self, n_synth: int, n_cpm_pool: int, n_cpm_per_epoch: int, generator: torch.Generator,
                 n_divisi_pool: int = 0, n_divisi_per_epoch: int = 0) -> None:
        self.n_synth, self.n_pool, self.n_cpm = n_synth, n_cpm_pool, min(n_cpm_per_epoch, n_cpm_pool)
        self.n_divisi_pool, self.n_divisi = n_divisi_pool, min(n_divisi_per_epoch, n_divisi_pool)
        self.generator = generator
        self.last_epoch_divisi = 0   # divisi indices in the most recent epoch's draw, for divisi_share_realised

    def __len__(self) -> int:
        return self.n_synth + self.n_cpm + self.n_divisi

    def __iter__(self) -> Iterator[int]:
        cpm = (torch.randperm(self.n_pool, generator=self.generator)[:self.n_cpm] + self.n_synth).tolist()
        idx = list(range(self.n_synth)) + cpm
        if self.n_divisi:
            base = self.n_synth + self.n_pool
            idx += (torch.randperm(self.n_divisi_pool, generator=self.generator)[:self.n_divisi] + base).tolist()
        order = [idx[i] for i in torch.randperm(len(idx), generator=self.generator).tolist()]
        self.last_epoch_divisi = sum(i >= self.n_synth + self.n_pool for i in order)
        return iter(order)


# ---- evaluation ------------------------------------------------------------------------------------------------

def decode_batches(model: torch.nn.Module, loader: DataLoader, device: torch.device,
                   max_batches: int | None = None) -> list[tuple[list[str], list[str]]]:
    model.eval()
    pairs = []
    with torch.no_grad():
        for bi, (images, labels, _in_lens, lb_lens) in enumerate(loader):
            if max_batches is not None and bi >= max_batches:
                break
            log_probs = model(images.to(device))
            off = 0
            for b in range(images.size(0)):
                n = int(lb_lens[b])
                gt = [IDX_TO_SYM.get(i, "<unk>") for i in labels[off:off + n].tolist()]
                off += n
                pred = [IDX_TO_SYM.get(i, "<unk>") for i in _greedy_ctc_decode(log_probs[:, b, :])]
                pairs.append((pred, gt))
    return pairs


def mean_ser(pairs: list[tuple[list[str], list[str]]]) -> float:
    return float(np.mean([compute_ser(p, g) for p, g in pairs])) if pairs else 0.0


def lcs_matched_gt(pred: list[str], gt: list[str]) -> set[int]:
    """GT positions matched by one longest common subsequence; a GT token counts as recalled only if matched."""
    n, m = len(gt), len(pred)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if gt[i] == pred[j] else max(dp[i + 1][j], dp[i][j + 1])
    out, i, j = set(), 0, 0
    while i < n and j < m:
        if gt[i] == pred[j]:
            out.add(i)
            i, j = i + 1, j + 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def val_metrics(pairs: list[tuple[list[str], list[str]]], rows: list[dict[str, object]]) -> dict[str, object]:
    sers = [compute_ser(p, g) for p, g in pairs]
    groups: dict[str, list[float]] = defaultdict(list)
    hit: Counter[str] = Counter()
    tot: Counter[str] = Counter()
    for (pred, gt), ser, row in zip(pairs, sers, rows):
        for key in ("line_mult_tertile", "interline_px_tertile", "font"):
            groups[f"{key}={row[key]}"].append(ser)
        matched = lcs_matched_gt(pred, gt)
        classes = [token_class(t) for t in gt]
        for i, c in enumerate(classes):
            if c in WATCH_CLASSES:
                tot[c] += 1
                hit[c] += int(i in matched)
        bars = [i for i, c in enumerate(classes) if c == "barline"]
        if row["final_system"] and bars:
            tot["final_barline"] += 1
            hit["final_barline"] += int(bars[-1] in matched)
    recall = {c: {"recall": hit[c] / tot[c] if tot[c] else None, "n": tot[c]}
              for c in (*WATCH_CLASSES, "final_barline")}
    return {"val_ser": float(np.mean(sers)) if sers else 0.0,
            "val_ser_by_stratum": {k: float(np.mean(v)) for k, v in sorted(groups.items())},
            "watch_recall": recall}


def bootstrap_ci_upper(samples: list[float], seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    arr = np.asarray(samples)
    means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(BOOTSTRAP_N)]
    return float(np.percentile(means, BOOTSTRAP_CI * 100))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def use_ext_vocab() -> None:
    """Divisi arm: switch this module's token tables to VOCAB_EXT_CHORD_TUPLET. The old VOCAB is its prefix, so every
    old index keeps its meaning and CPM/Phase 1 labels encode exactly as before."""
    global VOCAB, VOCAB_SIZE, SYM_TO_IDX, IDX_TO_SYM
    VOCAB = list(VOCAB_EXT_CHORD_TUPLET)
    VOCAB_SIZE = len(VOCAB)
    SYM_TO_IDX = {s: i for i, s in enumerate(VOCAB)}
    IDX_TO_SYM = dict(enumerate(VOCAB))


def load_model(path: Path, device: torch.device, expand: bool = True,
               bias_drop: float = 0.0) -> tuple[torch.nn.Module, dict[str, object]]:
    """Load a checkpoint whose vocab is VOCAB or a prefix of it. With `expand`, a shorter head grows to VOCAB_SIZE:
    old rows copied, new weights N(0, 0.01) from a fixed generator, new biases at the minimum old non-blank bias
    minus `bias_drop` (freeze section 2), so new tokens start below every old one."""
    ckpt = torch.load(path, map_location=device)
    old = ckpt.get("vocab")
    if old is not None and list(old) != VOCAB[:len(old)]:
        raise ValueError(f"{path}: stored vocab is not a prefix of the active vocab; indices would misalign")
    state = dict(ckpt["model_state"])
    w, b = state["fc.weight"], state["fc.bias"]
    if w.shape[0] > VOCAB_SIZE:
        raise ValueError(f"{path}: head has {w.shape[0]} outputs, active vocab {VOCAB_SIZE}; pass --vocab-ext")
    if expand and w.shape[0] < VOCAB_SIZE:
        n_new = VOCAB_SIZE - w.shape[0]
        gen = torch.Generator().manual_seed(0)
        new_w = torch.randn(n_new, w.shape[1], generator=gen) * NEW_HEAD_WEIGHT_STD
        floor = b[torch.arange(b.shape[0], device=b.device) != BLANK_IDX].min() - bias_drop
        state["fc.weight"] = torch.cat([w, new_w.to(w)])
        state["fc.bias"] = torch.cat([b, floor.repeat(n_new)])
    model = CRNN(state["fc.weight"].shape[0]).to(device)
    model.load_state_dict(state, strict=True)
    return model, ckpt


def expand_init_head(path: Path, device: torch.device,
                     loaders: list[DataLoader]) -> tuple[torch.nn.Module, dict[str, object], float]:
    """Expand the init head and lower the new biases by 1.0 until the greedy decode of `loaders` is token-identical
    to the unexpanded init (freeze section 2): training then starts from Phase 2's exact behaviour."""
    ref, _ = load_model(path, device, expand=False)
    want = [[p for p, _g in decode_batches(ref, ld, device)] for ld in loaders]
    for k in range(NEW_HEAD_MAX_BIAS_STEPS + 1):
        model, ckpt = load_model(path, device, bias_drop=k * NEW_HEAD_BIAS_STEP)
        if [[p for p, _g in decode_batches(model, ld, device)] for ld in loaders] == want:
            return model, ckpt, k * NEW_HEAD_BIAS_STEP
    raise SystemExit(f"expanded head still changes the init decode after {NEW_HEAD_MAX_BIAS_STEPS} bias steps")


def chordnote_metrics(pairs: list[tuple[list[str], list[str]]]) -> dict[str, object]:
    """Chordnote precision/recall via one LCS per strip, and predicted chordnotes per 100 GT notes (on un-injected
    strips every predicted chordnote is a hallucination)."""
    gt_n = pred_n = hit = notes = split_dups = 0
    for pred, gt in pairs:
        # Greedy collapse is non-local: a chordnote frame inside a run "X X X" decodes as "X chordnote X".
        split_dups += sum(pred[i].startswith(CHORDNOTE_PREFIX) and pred[i - 1] == pred[i + 1]
                          for i in range(1, len(pred) - 1))
        matched = lcs_matched_gt(pred, gt)
        gt_n += sum(t.startswith(CHORDNOTE_PREFIX) for t in gt)
        pred_n += sum(t.startswith(CHORDNOTE_PREFIX) for t in pred)
        hit += sum(gt[i].startswith(CHORDNOTE_PREFIX) for i in matched)
        notes += sum(t.startswith(("note.", CHORDNOTE_PREFIX)) for t in gt)
    return {"chordnote_precision": hit / pred_n if pred_n else None, "chordnote_recall": hit / gt_n if gt_n else None,
            "chordnote_gt": gt_n, "chordnote_pred": pred_n, "chordnote_split_duplicates": split_dups,
            "chordnote_pred_per_100_notes": 100.0 * pred_n / notes if notes else None, **interval_metrics(pairs)}


# Staff steps from the head below to the chordnote -> interval row (divisi freeze A3; 6 = 7th and >7 fall in "other").
INTERVAL_ROWS = {1: "2nd", 2: "3rd", 3: "4th5th", 4: "4th5th", 5: "6th", 7: "8ve"}
WILSON_Z = 1.96
POSITION_SUFFIX = re.compile(r"-([LS])(-?\d+)$")


def staff_step(token: str) -> int:
    """`...-L3` -> 6, `...-S3` -> 7: lines and spaces on one step scale (Sn is the space above Ln)."""
    m = POSITION_SUFFIX.search(token)
    if m is None:
        raise ValueError(f"no staff position in {token!r}")
    return 2 * int(m.group(2)) + (m.group(1) == "S")


def wilson95(hit: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    p, z2 = hit / n, WILSON_Z ** 2
    centre, half = p + z2 / (2 * n), WILSON_Z * (p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5
    return [(centre - half) / (1 + z2 / n), (centre + half) / (1 + z2 / n)]


def interval_metrics(pairs: list[tuple[list[str], list[str]]]) -> dict[str, object]:
    """Chordnote recall per interval to the head below it, plus `second_as_sequence`: a GT second not recalled
    while the decode holds two successive notes at its two positions (the side-by-side heads read in time)."""
    gt_n, hit, as_seq = Counter(), Counter(), 0
    for pred, gt in pairs:
        matched = lcs_matched_gt(pred, gt)
        seq_pairs = {(staff_step(a), staff_step(b)) for a, b in zip(pred, pred[1:])
                     if a.startswith(("note.", CHORDNOTE_PREFIX)) and b.startswith("note.")}
        for i, tok in enumerate(gt):
            if not tok.startswith(CHORDNOTE_PREFIX) or i == 0:
                continue
            lo, hi = staff_step(gt[i - 1]), staff_step(tok)
            row = INTERVAL_ROWS.get(hi - lo, "other")
            gt_n[row] += 1
            hit[row] += i in matched
            # shortcut: the note pair may sit anywhere in the strip, not at this onset; fine for a diagnostic count.
            as_seq += row == "2nd" and i not in matched and (lo, hi) in seq_pairs
    rows = ("2nd", "3rd", "4th5th", "6th", "8ve", "other")
    return {"by_interval": {r: {"gt": gt_n[r], "hit": hit[r], "recall": hit[r] / gt_n[r] if gt_n[r] else None,
                                "wilson95": wilson95(hit[r], gt_n[r])} for r in rows},
            "second_as_sequence": as_seq}


# ---- run -------------------------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--recut-out", type=Path, required=True)
    ap.add_argument("--cpm-root", required=True)
    ap.add_argument("--cpm-font-root", default=None,
                    help="optional font-rerendered CPM (cpm-font-augmented2); its fonts join the replay pool")
    ap.add_argument("--init", type=Path, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--replay-ratio", type=float, default=0.5)
    ap.add_argument("--augment-synth", action="store_true", help="also apply the CPM _augment to Phase 1 strips")
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--max-epochs", type=int, default=6)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--expect-manifest-sha", default=None)
    ap.add_argument("--smoke", action="store_true")
    # Divisi arm and its control (docs/decisions/piya-106-divisi-arm-freeze.md sections 2-4).
    ap.add_argument("--vocab-ext", action="store_true", help="train on VOCAB_EXT_CHORD_TUPLET (expands the init head)")
    ap.add_argument("--divisi-recut-out", type=Path, default=None,
                    help="cut divisi corpus; its strips with a chordnote join train/val by their inherited split")
    ap.add_argument("--expect-divisi-manifest-sha", default=None)
    ap.add_argument("--divisi-share", type=float, default=None,
                    help="A6: divisi strips are this fraction of the synthetic strips each epoch, a fresh draw from "
                         "the whole divisi train pool (chord-free strips kept); omit for the train-1 filter and mix")
    ap.add_argument("--holdout-chord-font", default=None,
                    help="A6: drop divisi train rows of this font (case-insensitive), then assert none remain")
    ap.add_argument("--control-rows", type=int, default=0,
                    help="control run: add a seeded draw of this many extra Phase 1 train rows (same step count)")
    ap.add_argument("--select-last", action="store_true", help="no patience; the last epoch is always selected")
    ap.add_argument("--head-only", action="store_true",
                    help="freeze the backbone and old head rows; train only the new chordnote rows (amendment A2)")
    a = ap.parse_args()
    if a.head_only and not a.vocab_ext:
        raise ValueError("--head-only needs --vocab-ext")
    if not 0.0 <= a.replay_ratio < 1.0:
        raise ValueError("--replay-ratio must be in [0, 1)")
    if a.divisi_recut_out is not None and not a.vocab_ext:
        raise ValueError("--divisi-recut-out needs --vocab-ext")
    if (a.divisi_share is not None or a.holdout_chord_font) and a.divisi_recut_out is None:
        raise ValueError("--divisi-share and --holdout-chord-font need --divisi-recut-out")
    if a.divisi_share is not None and not 0.0 < a.divisi_share < 1.0:
        raise ValueError("--divisi-share must be in (0, 1)")
    if a.vocab_ext:
        use_ext_vocab()

    random.seed(a.seed)
    np.random.seed(a.seed)
    torch.manual_seed(a.seed)
    torch.cuda.manual_seed_all(a.seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    device = torch.device("cuda" if torch.cuda.is_available() and not a.smoke else "cpu")
    a.out.mkdir(parents=True, exist_ok=True)

    # Phase 1 manifest, rebuilt from the attached corpus and pinned by sha256 (nothing is uploaded).
    rows, meta = build(a.recut_out)
    body = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")
    manifest_sha = hashlib.sha256(body).hexdigest()
    if a.expect_manifest_sha and manifest_sha != a.expect_manifest_sha:
        raise SystemExit(f"manifest sha256 {manifest_sha} != expected {a.expect_manifest_sha}")
    if any(token_class(t) == FORBIDDEN_CLASS for r in rows for t in r["tokens"]):  # type: ignore[union-attr]
        raise SystemExit(f"{FORBIDDEN_CLASS} in manifest labels")
    train_rows = [r for r in rows if r["split"] == "train"]
    val_rows = [r for r in rows if r["split"] == "val"]
    divisi_val: list[dict[str, object]] = []
    divisi_info: dict[str, object] = {}
    if a.divisi_recut_out is not None:
        drows, _dmeta = build(a.divisi_recut_out)
        dbody = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in drows).encode("utf-8")
        dsha = hashlib.sha256(dbody).hexdigest()
        if a.expect_divisi_manifest_sha and dsha != a.expect_divisi_manifest_sha:
            raise SystemExit(f"divisi manifest sha256 {dsha} != expected {a.expect_divisi_manifest_sha}")
        if a.divisi_share is None:
            # Train-1: only strips that carry a chord are kept (freeze section 3). A6 keeps the chord-free ones too,
            # so the model also sees divisi-page strips with no chord and does not learn "divisi means chord".
            drows = [r for r in drows if any(str(t).startswith(CHORDNOTE_PREFIX) for t in r["tokens"])]  # type: ignore[union-attr]
        for r in drows:   # absolute, so synth()'s recut_out join leaves it alone
            r["path"] = str(a.divisi_recut_out.resolve() / str(r["path"]))
        dtrain = [r for r in drows if r["split"] == "train"]
        divisi_val = [r for r in drows if r["split"] == "val"]
        train_tunes = {r["tune"] for r in train_rows + dtrain}
        val_tunes = {r["tune"] for r in val_rows + divisi_val}
        if train_tunes & val_tunes:
            raise SystemExit(f"split assert: {len(train_tunes & val_tunes)} tunes on both sides")
        divisi_info = {"divisi_manifest_sha256": dsha, "divisi_val_strips": len(divisi_val)}
        if a.holdout_chord_font:
            held = a.holdout_chord_font.casefold()
            before = len(dtrain)
            dtrain = [r for r in dtrain if str(r["font"]).casefold() != held]
            assert not any(str(r["font"]).casefold() == held for r in dtrain), "held-out chord font in divisi train"
            divisi_info.update({"holdout_chord_font": a.holdout_chord_font,
                                "divisi_train_dropped_for_holdout": before - len(dtrain)})
            print(f"[holdout] {a.holdout_chord_font}: dropped {before - len(dtrain)} of {before} divisi train rows, "
                  f"{len(dtrain)} remain, 0 of the held-out font", flush=True)
        divisi_info["divisi_train_strips"] = len(dtrain)
        if a.divisi_share is not None:
            divisi_info["divisi_share"] = a.divisi_share
        if a.divisi_share is None:
            train_rows = train_rows + dtrain
            dtrain = []
    if a.control_rows:
        train_rows = train_rows + random.Random(f"control:{a.seed}").sample(train_rows, a.control_rows)

    def synth(rs: list[dict[str, object]]) -> list[tuple[str, str | None, list[int]]]:
        return [(str(a.recut_out / str(r["path"])), None, [SYM_TO_IDX[t] for t in r["tokens"]]) for r in rs]  # type: ignore[union-attr]

    # Canary: notebook cell 8, first 10% of the sorted CPM glob.
    cpm = cpm_samples(a.cpm_root)
    n_canary = int(CANARY_FRACTION * len(cpm))
    canary, cpm_train = cpm[:n_canary], cpm[n_canary:]
    canary_stems = {Path(s[0]).stem for s in canary}
    canary_sha = hashlib.sha256("\n".join(Path(s[0]).stem for s in canary).encode("utf-8")).hexdigest()
    if (len(canary), canary_sha) != (CANARY_COUNT, CANARY_STEMS_SHA256):
        raise SystemExit(f"canary is not the notebook's slice: {len(canary)} stems, sha256 {canary_sha}")
    if a.cpm_font_root:
        for font_dir in sorted(p for p in Path(a.cpm_font_root).iterdir() if p.is_dir()):
            cpm_train += [s for s in cpm_samples(str(font_dir)) if Path(s[0]).stem not in canary_stems]
    if a.smoke:
        # Keep some divisi rows in the smoke train slice, so the chord path is exercised.
        train_rows = train_rows[:SMOKE_N // 2] + train_rows[-(SMOKE_N // 2):]
        val_rows, divisi_val = val_rows[:SMOKE_N], divisi_val[:SMOKE_N]
        dtrain = dtrain[:SMOKE_N]
        canary, cpm_train = canary[:SMOKE_N], cpm_train[:SMOKE_N]
        a.max_epochs = 1
    assert not canary_stems & {Path(s[0]).stem for s in cpm_train}, "canary stem leaked into the replay pool"

    # A6: n_phase1 is the Phase 1 synthetic strips per epoch (not CPM, not divisi), so divisi / (phase1 + divisi) is
    # exactly the share; CPM replay is then sized on all synthetic strips.
    n_divisi_epoch = 0
    if a.divisi_share is not None:
        n_divisi_epoch = round(a.divisi_share * len(train_rows) / (1.0 - a.divisi_share))
        if n_divisi_epoch > len(dtrain):
            raise SystemExit(f"divisi pool {len(dtrain)} < {n_divisi_epoch} strips needed per epoch for share "
                             f"{a.divisi_share} of {len(train_rows)} Phase 1 strips")
    n_cpm_epoch = round((len(train_rows) + n_divisi_epoch) * a.replay_ratio / (1.0 - a.replay_ratio))
    train_parts = [StripDataset(synth(train_rows), augment=a.augment_synth),
                   StripDataset(cpm_train, augment=True, distorted_prob=0.5)]
    if a.divisi_share is not None:
        train_parts.append(StripDataset(synth(dtrain), augment=a.augment_synth))
    train_ds = ConcatDataset(train_parts)
    gen = torch.Generator()
    gen.manual_seed(a.seed)
    sampler = ReplaySampler(len(train_rows), len(cpm_train), n_cpm_epoch, gen,
                            n_divisi_pool=len(dtrain), n_divisi_per_epoch=n_divisi_epoch)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, collate_fn=ctc_collate, num_workers=0, sampler=sampler)
    eval_kw = {"batch_size": BATCH_SIZE, "shuffle": False, "collate_fn": ctc_collate, "num_workers": 0}
    val_loader = DataLoader(StripDataset(synth(val_rows)), **eval_kw)
    canary_clean = DataLoader(StripDataset(canary), **eval_kw)
    canary_dist = DataLoader(StripDataset(canary, force_distorted=True), **eval_kw)
    divisi_val_loader = DataLoader(StripDataset(synth(divisi_val)), **eval_kw) if divisi_val else None

    head_bias_drop = None
    if a.vocab_ext:
        model, _init_ckpt, head_bias_drop = expand_init_head(a.init, device, [canary_clean, val_loader])
    else:
        model, _init_ckpt = load_model(a.init, device)
    base_clean = [compute_ser(p, g) for p, g in decode_batches(model, canary_clean, device)]
    base_dist = [compute_ser(p, g) for p, g in decode_batches(model, canary_dist, device)]
    caps = {"canary_clean_hard_cap": float(np.mean(base_clean)) * CANARY_HARD_CAP_MULTIPLIER,
            "canary_distorted_hard_cap": float(np.mean(base_dist)) * CANARY_HARD_CAP_MULTIPLIER,
            "canary_clean_soft_floor": bootstrap_ci_upper(base_clean),
            "canary_distorted_soft_floor": bootstrap_ci_upper(base_dist)}
    run_info = {
        "args": {k: str(v) for k, v in vars(a).items()}, "manifest_sha256": manifest_sha,
        "init_sha256": sha256_file(a.init), "edges": meta["edges"],
        "train_strips": len(train_rows), "val_strips": len(val_rows), "val_pieces": sorted({str(r["piece"]) for r in val_rows}),
        "cpm_replay_pool": len(cpm_train), "cpm_per_epoch": min(n_cpm_epoch, len(cpm_train)), "canary": len(canary),
        "canary_baseline": {"clean": float(np.mean(base_clean)), "distorted": float(np.mean(base_dist))}, **caps,
        "stack": {"device": torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu",
                  "torch": torch.__version__, "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version()},
        "gate_mode": GATE_MODE, "vocab_size": VOCAB_SIZE, "head_bias_drop": head_bias_drop, **divisi_info,
    }
    (a.out / "run_info.json").write_text(json.dumps(run_info, indent=1), encoding="utf-8")
    print(f"[run] seed={a.seed} manifest={manifest_sha[:12]} train={len(train_rows)}+{run_info['cpm_per_epoch']} cpm "
          f"val={len(val_rows)} canary={len(canary)} base canary {run_info['canary_baseline']} "
          f"stack={run_info['stack']}", flush=True)

    criterion = torch.nn.CTCLoss(blank=BLANK_IDX, zero_infinity=True)
    # Diagnostic only: counts the samples zero_infinity silently zeroes (gate: 0 chord samples, freeze section 5).
    per_sample = torch.nn.CTCLoss(blank=BLANK_IDX, reduction="none", zero_infinity=False)
    first_new = BASE_VOCAB_SIZE   # label indices at or above this are divisi-arm tokens
    frozen_init: dict[str, torch.Tensor] = {}
    if a.head_only:
        # Old logits stay bit-identical: backbone frozen and in eval() (BatchNorm stats), old fc rows get zero
        # gradient and no weight decay, so AdamW's update for them is exactly 0 (amendment A2).
        frozen_init = {k: v.detach().clone() for k, v in model.state_dict().items()}
        for p in model.parameters():
            p.requires_grad_(False)
        for p in model.fc.parameters():
            p.requires_grad_(True)
            p.register_hook(lambda g: torch.cat([torch.zeros_like(g[:BASE_VOCAB_SIZE]), g[BASE_VOCAB_SIZE:]]))
        optimizer = torch.optim.AdamW(model.fc.parameters(), lr=a.lr, weight_decay=0.0)
    else:
        optimizer = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=a.max_epochs)
    history: list[dict[str, object]] = []
    best_ser, best_epoch, since_improve = float("inf"), None, 0
    weights_best = a.out / f"phase2_seed{a.seed}.pt"
    losses: list[float] = []
    for epoch in range(1, a.max_epochs + 1):
        t0 = time.time()
        model.train()
        if a.head_only:
            model.cnn.eval()
            model.rnn.eval()
        losses = []
        zeroed = {"all": 0, "chord": 0}
        for step, (images, labels, in_lens, lb_lens) in enumerate(train_loader):
            if a.smoke and step >= SMOKE_STEPS:
                break
            if a.head_only:
                assert not (model.cnn.training or model.rnn.training), "head-only backbone left in train mode"
            images, labels, in_lens, lb_lens = (x.to(device) for x in (images, labels, in_lens, lb_lens))
            log_probs = model(images)
            in_clamped = in_lens.clamp(max=log_probs.shape[0])
            loss = criterion(log_probs, labels, in_clamped, lb_lens)
            with torch.no_grad():
                inf = torch.isinf(per_sample(log_probs.detach(), labels, in_clamped, lb_lens)).tolist()
                ends = torch.cumsum(lb_lens, 0).tolist()
                for b, bad in enumerate(inf):
                    if bad:
                        zeroed["all"] += 1
                        zeroed["chord"] += int(bool((labels[ends[b] - int(lb_lens[b]):ends[b]] >= first_new).any()))
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
            optimizer.step()
            losses.append(loss.item())
        scheduler.step()
        vm = val_metrics(decode_batches(model, val_loader, device), val_rows)
        cpairs = decode_batches(model, canary_clean, device)
        c_clean = mean_ser(cpairs)
        c_dist = mean_ser(decode_batches(model, canary_dist, device))
        hard_ok = c_clean <= caps["canary_clean_hard_cap"] and c_dist <= caps["canary_distorted_hard_cap"]
        soft_breach = c_clean > caps["canary_clean_soft_floor"] or c_dist > caps["canary_distorted_soft_floor"]
        chord: dict[str, object] = {}
        if a.vocab_ext:
            chord["uninjected_val"] = chordnote_metrics(decode_batches(model, val_loader, device))
            chord["canary_clean"] = chordnote_metrics(cpairs)
            if divisi_val_loader is not None:
                dpairs = decode_batches(model, divisi_val_loader, device)
                chord["divisi_val"] = {**chordnote_metrics(dpairs), "ser": mean_ser(dpairs)}
        n_synth_epoch = len(train_rows) + sampler.last_epoch_divisi
        share_extra = ({"divisi_share_realised": sampler.last_epoch_divisi / n_synth_epoch}
                       if a.divisi_share is not None else {})
        rec = {"epoch": epoch, **share_extra, "train_loss": float(np.mean(losses)) if losses else float("nan"), **vm,
               "zeroed_by_zero_infinity": zeroed, **({"chord": chord} if chord else {}),
               "canary_clean_ser": c_clean, "canary_distorted_ser": c_dist,
               "status": "HARD CAP BREACHED" if not hard_ok else ("soft floor breached" if soft_breach else "OK"),
               "seconds": round(time.time() - t0, 1)}
        history.append(rec)
        share_log = f" | divisi {rec['divisi_share_realised']:.3f}" if a.divisi_share is not None else ""
        (a.out / "metrics.json").write_text(json.dumps(history, indent=1), encoding="utf-8")
        print(f"Epoch {epoch:02d} | loss {rec['train_loss']:.4f}{share_log} | val SER {vm['val_ser']:.4f} | canary "
              f"{c_clean:.4f}/{c_dist:.4f} | {rec['status']} | {rec['seconds']}s", flush=True)
        state = {"model_state": model.state_dict(), "optimizer_state": optimizer.state_dict(),
                 "scheduler_state": scheduler.state_dict(), "epoch": epoch, "val_ser": vm["val_ser"],
                 "canary_clean_ser": c_clean, "canary_distorted_ser": c_dist, "gate_mode": GATE_MODE, **caps,
                 "vocab": VOCAB, "manifest_sha256": manifest_sha, "val_pieces": run_info["val_pieces"],
                 "canary_val_stems": sorted(canary_stems), "seed": a.seed, "init_sha256": run_info["init_sha256"]}
        torch.save(state, a.out / f"phase2_seed{a.seed}_epoch{epoch}.pt")
        if not hard_ok:
            print(f"  Stopping: canary hard cap breached; best stays epoch {best_epoch}.")
            break
        if a.select_last:
            best_ser, best_epoch = float(vm["val_ser"]), epoch  # type: ignore[arg-type]
            torch.save(state, weights_best)
        elif vm["val_ser"] < best_ser:  # type: ignore[operator]
            best_ser, best_epoch, since_improve = float(vm["val_ser"]), epoch, 0  # type: ignore[arg-type]
            torch.save(state, weights_best)
        else:
            since_improve += 1
            if since_improve >= a.patience:
                print(f"  Stopping: no val SER improvement for {a.patience} epochs.")
                break
    summary: dict[str, object] = {"best_epoch": best_epoch, "best_val_ser": best_ser, "epochs_run": len(history)}
    if a.head_only:
        now = model.state_dict()
        changed = [k for k, v in frozen_init.items()
                   if not torch.equal(v[:BASE_VOCAB_SIZE] if k.startswith("fc.") else v,
                                      now[k][:BASE_VOCAB_SIZE] if k.startswith("fc.") else now[k])]
        summary["head_only_identity"] = not changed
        if changed:
            raise SystemExit(f"head-only identity broken: {changed}")
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"[done] {summary}")

    if a.smoke:
        reloaded, _ = load_model(weights_best, device)
        model.eval()
        reloaded.eval()
        images = next(iter(val_loader))[0].to(device)
        with torch.no_grad():
            same = torch.equal(model(images), reloaded(images))
        keys = {"val_ser", "val_ser_by_stratum", "watch_recall", "canary_clean_ser", "canary_distorted_ser"}
        ok = same and all(np.isfinite(losses)) and bool(losses) and keys <= set(history[-1])
        print(f"[smoke] {'PASS' if ok else 'FAIL'}: finite_loss={all(np.isfinite(losses))} "
              f"reload_identical={same} metric_keys={keys <= set(history[-1])}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
