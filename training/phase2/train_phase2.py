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
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
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
from stage3_transcription import (BLANK_IDX, CRNN, IDX_TO_SYM, SYM_TO_IDX, VOCAB, VOCAB_SIZE,  # noqa: E402
                                  _greedy_ctc_decode, compute_ser)

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
    reseeded by run() exactly like the notebook reseeds the train loader, so a seed fixes the whole order."""

    def __init__(self, n_synth: int, n_cpm_pool: int, n_cpm_per_epoch: int, generator: torch.Generator) -> None:
        self.n_synth, self.n_pool, self.n_cpm = n_synth, n_cpm_pool, min(n_cpm_per_epoch, n_cpm_pool)
        self.generator = generator

    def __len__(self) -> int:
        return self.n_synth + self.n_cpm

    def __iter__(self) -> Iterator[int]:
        cpm = (torch.randperm(self.n_pool, generator=self.generator)[:self.n_cpm] + self.n_synth).tolist()
        idx = list(range(self.n_synth)) + cpm
        return iter([idx[i] for i in torch.randperm(len(idx), generator=self.generator).tolist()])


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


def load_model(path: Path, device: torch.device) -> tuple[torch.nn.Module, dict[str, object]]:
    ckpt = torch.load(path, map_location=device)
    if ckpt.get("vocab") is not None and ckpt["vocab"] != VOCAB:
        raise ValueError(f"{path}: stored vocab differs from stage3_transcription.VOCAB; indices would misalign")
    model = CRNN(VOCAB_SIZE).to(device)
    model.load_state_dict(ckpt["model_state"], strict=True)
    return model, ckpt


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
    a = ap.parse_args()
    if not 0.0 <= a.replay_ratio < 1.0:
        raise ValueError("--replay-ratio must be in [0, 1)")

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
        train_rows, val_rows = train_rows[:SMOKE_N], val_rows[:SMOKE_N]
        canary, cpm_train = canary[:SMOKE_N], cpm_train[:SMOKE_N]
        a.max_epochs = 1
    assert not canary_stems & {Path(s[0]).stem for s in cpm_train}, "canary stem leaked into the replay pool"

    n_cpm_epoch = round(len(train_rows) * a.replay_ratio / (1.0 - a.replay_ratio))
    train_ds = ConcatDataset([StripDataset(synth(train_rows), augment=a.augment_synth),
                              StripDataset(cpm_train, augment=True, distorted_prob=0.5)])
    gen = torch.Generator()
    gen.manual_seed(a.seed)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, collate_fn=ctc_collate, num_workers=0,
                              sampler=ReplaySampler(len(train_rows), len(cpm_train), n_cpm_epoch, gen))
    eval_kw = {"batch_size": BATCH_SIZE, "shuffle": False, "collate_fn": ctc_collate, "num_workers": 0}
    val_loader = DataLoader(StripDataset(synth(val_rows)), **eval_kw)
    canary_clean = DataLoader(StripDataset(canary), **eval_kw)
    canary_dist = DataLoader(StripDataset(canary, force_distorted=True), **eval_kw)

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
        "gate_mode": GATE_MODE,
    }
    (a.out / "run_info.json").write_text(json.dumps(run_info, indent=1), encoding="utf-8")
    print(f"[run] seed={a.seed} manifest={manifest_sha[:12]} train={len(train_rows)}+{run_info['cpm_per_epoch']} cpm "
          f"val={len(val_rows)} canary={len(canary)} base canary {run_info['canary_baseline']} "
          f"stack={run_info['stack']}", flush=True)

    criterion = torch.nn.CTCLoss(blank=BLANK_IDX, zero_infinity=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=a.max_epochs)
    history: list[dict[str, object]] = []
    best_ser, best_epoch, since_improve = float("inf"), None, 0
    weights_best = a.out / f"phase2_seed{a.seed}.pt"
    losses: list[float] = []
    for epoch in range(1, a.max_epochs + 1):
        t0 = time.time()
        model.train()
        losses = []
        for step, (images, labels, in_lens, lb_lens) in enumerate(train_loader):
            if a.smoke and step >= SMOKE_STEPS:
                break
            images, labels, in_lens, lb_lens = (x.to(device) for x in (images, labels, in_lens, lb_lens))
            log_probs = model(images)
            loss = criterion(log_probs, labels, in_lens.clamp(max=log_probs.shape[0]), lb_lens)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
            optimizer.step()
            losses.append(loss.item())
        scheduler.step()
        vm = val_metrics(decode_batches(model, val_loader, device), val_rows)
        c_clean = mean_ser(decode_batches(model, canary_clean, device))
        c_dist = mean_ser(decode_batches(model, canary_dist, device))
        hard_ok = c_clean <= caps["canary_clean_hard_cap"] and c_dist <= caps["canary_distorted_hard_cap"]
        soft_breach = c_clean > caps["canary_clean_soft_floor"] or c_dist > caps["canary_distorted_soft_floor"]
        rec = {"epoch": epoch, "train_loss": float(np.mean(losses)) if losses else float("nan"), **vm,
               "canary_clean_ser": c_clean, "canary_distorted_ser": c_dist,
               "status": "HARD CAP BREACHED" if not hard_ok else ("soft floor breached" if soft_breach else "OK"),
               "seconds": round(time.time() - t0, 1)}
        history.append(rec)
        (a.out / "metrics.json").write_text(json.dumps(history, indent=1), encoding="utf-8")
        print(f"Epoch {epoch:02d} | loss {rec['train_loss']:.4f} | val SER {vm['val_ser']:.4f} | canary "
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
        if vm["val_ser"] < best_ser:  # type: ignore[operator]
            best_ser, best_epoch, since_improve = float(vm["val_ser"]), epoch, 0  # type: ignore[arg-type]
            torch.save(state, weights_best)
        else:
            since_improve += 1
            if since_improve >= a.patience:
                print(f"  Stopping: no val SER improvement for {a.patience} epochs.")
                break
    summary = {"best_epoch": best_epoch, "best_val_ser": best_ser, "epochs_run": len(history)}
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
