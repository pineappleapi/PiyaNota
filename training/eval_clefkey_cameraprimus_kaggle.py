"""ClefKeyNet on Camera-PrIMuS: clef and key-signature accuracy, clean vs distorted (one Kaggle cell).

Paste this whole file into one Kaggle notebook cell (or run it with ``python``). Attach two inputs:
  1. The Camera-PrIMuS dataset (the one the CRNN notebook already uses; it holds ``Corpus/``).
  2. A dataset holding the frozen ClefKeyNet files from
     ``training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt`` and the repo-root
     ``clef_key_core.py``. Both are found by globbing /kaggle/input, so the folder names do not matter.

Why this test is out-of-source: ClefKeyNet was trained on DeepScoresV2 dense pages plus Verovio
synthetic systems, never on Camera-PrIMuS, so every CPM incipit is unseen data in an unseen engraving.
It is NOT the CRNN's training distribution comparison either: the CRNN was trained on CPM, the
classifier was not.

Why the input path is copied, not re-designed: the network is only valid on inputs built exactly the
way its own test sets were built (train_clef_key.py: refine the five staff lines, store a grey crop at
12 px/space with the staff's left edge, upscale x2, binarize_like_stage1, make_input). Any change here
would measure a different input contract. The one addition is a deskew, because the distorted CPM
images are rotated and Stage 1 deskews every real page before the classifier ever sees it.

Labels come from the sample files, not from a person:
  clef: first ``clef-XN`` token of ``.semantic``: G2 -> G, F4 -> F, anything else -> other.
  key:  accidentals that follow the first clef in ``.agnostic`` (what is drawn), cross-checked against
        ``.semantic``'s keySignature; disagreeing samples get no key label and are counted.
"""
from __future__ import annotations

import csv
import glob
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import cv2
import numpy as np
import torch

# ==============================================================================================
# Configuration
# ==============================================================================================
ON_KAGGLE: bool = Path("/kaggle/input").is_dir()
INPUT_ROOT: Path = Path("/kaggle/input") if ON_KAGGLE else Path(os.environ.get("CPM_EVAL_INPUT_ROOT", "."))
OUT_DIR: Path = Path("/kaggle/working/clefkey_cpm_eval") if ON_KAGGLE else Path(
    os.environ.get("CPM_EVAL_OUT", "clefkey_cpm_eval"))
CPM_CORPUS: Optional[Path] = (Path(os.environ["CPM_EVAL_CORPUS"]) if os.environ.get("CPM_EVAL_CORPUS")
                              else None)  # None = find the folder named "Corpus" under INPUT_ROOT
CHECKPOINT: Optional[Path] = None      # None = glob INPUT_ROOT for clef_key_classifier.pt
CORE_FILE: Optional[Path] = None       # None = glob INPUT_ROOT for clef_key_core.py
SAMPLE_N: Optional[int] = int(os.environ["CPM_EVAL_N"]) if os.environ.get("CPM_EVAL_N") else None  # None = all
SAMPLE_SEED: int = 42
VARIANTS: tuple[str, ...] = ("clean", "distorted")
WORKERS: int = max(1, (os.cpu_count() or 2))
CHUNK: int = 128                       # samples per worker task; bounds memory (each input is 96x128 float32)
BOOTSTRAP_REPS: int = 1000
SAVE_ERROR_EXAMPLES: int = 48          # per variant: network inputs of the first N wrong clefs, for a montage

# ----------------------------------------------------------------------------------------------
# Copied verbatim from training/train_clef_key.py (the test-set input path). Do not tune these.
# ----------------------------------------------------------------------------------------------
STORE_PPS = 12
STORE_LEFT, STORE_RIGHT, STORE_ABOVE, STORE_BELOW = 4.0, 19.0, 7.0, 7.0
CANON_BLOCK_SPACES = 2.5
CANON_C = 10.0
CANON_UPSCALE = 2.0
BLUR_SPACES = 0.035
BG_KERNEL_SPACES = 1.5

# ----------------------------------------------------------------------------------------------
# CPM-specific geometry (this file only)
# ----------------------------------------------------------------------------------------------
DESKEW_MAX_DEG = 6.0        # CPM distortion rotates by a few degrees; real pages are deskewed by Stage 1
DESKEW_STEP_DEG = 0.25
LINE_FILL_FRAC = 0.5        # a staff-line row is ink over at least this fraction of the window (as training)
LINE_WINDOW_FRACS: tuple[tuple[float, float], ...] = ((0.1, 0.9), (0.02, 0.35), (0.02, 0.2))
SPACING_MAX_REL_DEV = 0.25  # the four gaps between five lines must agree within this fraction of their mean
BG_NORM_KERNEL_PX = 31      # background estimate for the line-finding (Otsu) image only

IN_SCOPE_SOURCE_CLEFS = {"G2": "G", "F4": "F"}
FLAT_ORDER_TONICS = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
                     "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7}
# Minor tonics as the fifths of their relative major (A minor = C major = 0).
MINOR_TONICS = {"A": 0, "E": 1, "B": 2, "F#": 3, "C#": 4, "G#": 5, "D#": 6, "A#": 7,
                "D": -1, "G": -2, "C": -3, "F": -4, "Bb": -5, "Eb": -6, "Ab": -7}
AGNOSTIC_HEADER_STOP = ("digit.", "metersign.", "note.", "rest.", "barline", "gracenote.", "multirest")


# ==============================================================================================
# Locating inputs and importing the frozen core
# ==============================================================================================
def _find_one(pattern: str, explicit: Optional[Path], what: str) -> Path:
    if explicit is not None:
        if not explicit.exists():
            raise FileNotFoundError(f"{what}: {explicit} does not exist")
        return explicit
    hits = sorted(Path(p) for p in glob.glob(str(INPUT_ROOT / "**" / pattern), recursive=True))
    if len(hits) != 1:
        raise FileNotFoundError(f"{what}: expected exactly one {pattern} under {INPUT_ROOT}, found {hits}. "
                                f"Set it explicitly in the configuration block.")
    return hits[0]


def _find_corpus() -> Path:
    if CPM_CORPUS is not None:
        return CPM_CORPUS
    hits = [Path(p) for p in glob.glob(str(INPUT_ROOT / "**" / "Corpus"), recursive=True) if Path(p).is_dir()]
    if len(hits) != 1:
        raise FileNotFoundError(f"expected exactly one Camera-PrIMuS 'Corpus' folder under {INPUT_ROOT}, "
                                f"found {hits}. Set CPM_CORPUS.")
    return hits[0]


def _lf_sha256(path: Path) -> str:
    """LF-normalised, the same way the checkpoint recorded core_sha256 (git autocrlf would change it)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _import_core(core_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("clef_key_core", core_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {core_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["clef_key_core"] = module
    spec.loader.exec_module(module)
    return module


CORE_PATH: Path = _find_one("clef_key_core.py", CORE_FILE, "ClefKeyNet core")
ck = _import_core(CORE_PATH)


# ==============================================================================================
# Ground truth
# ==============================================================================================
@dataclass
class Truth:
    sample_id: str
    piece_id: str                 # incipits of the same source piece share this; bootstrap clusters on it
    source_clef: Optional[str]    # e.g. "G2", "C1"
    clef: Optional[str]           # ClefKeyNet class
    key: Optional[int]            # None = semantic and agnostic disagree, or unparseable
    key_semantic: Optional[int]
    key_agnostic: Optional[int]


def _semantic_key(name: str) -> Optional[int]:
    """'EbM' -> -3, 'F#m' -> 3. None if the name is not a key PrIMuS writes."""
    if name.endswith("M"):
        return FLAT_ORDER_TONICS.get(name[:-1])
    if name.endswith("m"):
        return MINOR_TONICS.get(name[:-1])
    return None


def parse_truth(sample_dir: Path) -> Truth:
    sid = sample_dir.name
    sem = (sample_dir / f"{sid}.semantic").read_text(encoding="utf-8").split()
    agn = (sample_dir / f"{sid}.agnostic").read_text(encoding="utf-8").split()
    source_clef = next((t.split("-", 1)[1] for t in sem if t.startswith("clef-")), None)
    clef = None if source_clef is None else IN_SCOPE_SOURCE_CLEFS.get(source_clef, "other")

    key_sem: Optional[int] = None
    first_clef = next((i for i, t in enumerate(sem) if t.startswith("clef-")), None)
    if first_clef is not None:
        nxt = sem[first_clef + 1] if first_clef + 1 < len(sem) else ""
        key_sem = _semantic_key(nxt.split("-", 1)[1]) if nxt.startswith("keySignature-") else 0

    key_agn: Optional[int] = None
    a0 = next((i for i, t in enumerate(agn) if t.startswith("clef.")), None)
    if a0 is not None:
        sharps = flats = 0
        for t in agn[a0 + 1:]:
            if t.startswith("accidental.sharp"):
                sharps += 1
            elif t.startswith("accidental.flat"):
                flats += 1
            elif t.startswith(AGNOSTIC_HEADER_STOP) or t.startswith("clef."):
                break
        if not (sharps and flats):
            key_agn = sharps - flats
    key = key_agn if key_agn is not None and key_agn == key_sem else None
    return Truth(sid, sid.split("-", 1)[0], source_clef, clef, key, key_sem, key_agn)


# ==============================================================================================
# Image -> network input (training's test-set path, plus deskew)
# ==============================================================================================
def _odd(v: float) -> int:
    return max(3, int(round(v)) | 1)


def binarize_like_stage1(gray: np.ndarray, sp_px: float, block_spaces: float = CANON_BLOCK_SPACES,
                         c: float = CANON_C) -> np.ndarray:
    """Verbatim from train_clef_key.py. Returns ink = 0, paper = 255."""
    h, w = gray.shape
    small = cv2.resize(gray, (max(1, w // 4), max(1, h // 4)), interpolation=cv2.INTER_AREA)
    k = _odd(BG_KERNEL_SPACES * sp_px / 4)
    bg = cv2.dilate(small, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), max(1.0, 0.5 * sp_px))
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    norm = cv2.divide(gray, np.maximum(bg, 1), scale=255)
    norm = cv2.GaussianBlur(norm, (0, 0), max(0.5, BLUR_SPACES * sp_px))
    return cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
                                 _odd(block_spaces * sp_px), c)


STORE_W = int(round((STORE_LEFT + STORE_RIGHT) * STORE_PPS))
STORE_H = int(round((STORE_ABOVE + ck.STAFF_SPACES + STORE_BELOW) * STORE_PPS))
STORE_TOP = STORE_ABOVE * STORE_PPS - 0.5
STORE_BOTTOM = STORE_TOP + ck.STAFF_SPACES * STORE_PPS
STORE_X0 = STORE_LEFT * STORE_PPS - 0.5


def store_crop(gray_page: np.ndarray, x0: float, top: float, bottom: float) -> tuple[np.ndarray, float, bool]:
    """Verbatim from train_clef_key.py: grey storage crop plus the staff-start column."""
    crop = ck.warp_staff_region(gray_page, x0, top, bottom, STORE_PPS, STORE_LEFT, STORE_RIGHT,
                                STORE_ABOVE, STORE_BELOW)
    edge = ck.staff_left_edge(binarize_like_stage1(crop, STORE_PPS), STORE_TOP, STORE_BOTTOM)
    if edge is None or abs(edge - STORE_X0) > 2 * STORE_PPS:
        return crop, float(STORE_X0), False
    return crop, float(edge), True


def canonical_input(crop: np.ndarray, x0s: float) -> np.ndarray:
    """Training's evaluation input from a stored crop (the parity-fixture code in train_clef_key.py)."""
    g2 = cv2.resize(crop, (int(round(STORE_W * CANON_UPSCALE)), int(round(STORE_H * CANON_UPSCALE))),
                    interpolation=cv2.INTER_CUBIC)
    fx, fy = g2.shape[1] / STORE_W, g2.shape[0] / STORE_H
    b = binarize_like_stage1(g2, STORE_PPS * fy, CANON_BLOCK_SPACES, CANON_C)
    return ck.make_input(b, (x0s + 0.5) * fx - 0.5, (STORE_TOP + 0.5) * fy - 0.5, (STORE_BOTTOM + 0.5) * fy - 0.5)


def _ink(gray: np.ndarray) -> np.ndarray:
    """Background-normalised Otsu ink mask (bool), used only to find geometry, never as network input."""
    bg = cv2.dilate(gray, np.ones((BG_NORM_KERNEL_PX, BG_NORM_KERNEL_PX), np.uint8))
    norm = cv2.divide(gray, np.maximum(bg, 1), scale=255)
    _, b = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return b < 128


def deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Rotates so staff lines are horizontal: the angle whose row profile is sharpest wins."""
    ink = _ink(gray).astype(np.float32)
    h, w = ink.shape
    centre = (w / 2.0, h / 2.0)
    best, best_score = 0.0, -1.0
    for a in np.arange(-DESKEW_MAX_DEG, DESKEW_MAX_DEG + 1e-9, DESKEW_STEP_DEG):
        r = cv2.warpAffine(ink, cv2.getRotationMatrix2D(centre, float(a), 1.0), (w, h), flags=cv2.INTER_NEAREST)
        score = float(np.square(r.sum(axis=1)).sum())
        if score > best_score:
            best, best_score = float(a), score
    if best == 0.0:
        return gray, 0.0
    m = cv2.getRotationMatrix2D(centre, best, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE), best


def find_staff_lines(gray: np.ndarray) -> Optional[tuple[float, float, float]]:
    """(top line row, bottom line row, window left column) or None.

    Same rule as train_clef_key.refine_staff_lines (rows with ink over half the window, exactly five
    groups), tried on a full-width window first and then on left-side windows, because a perspective-
    distorted line can leave the full-width projection but stays straight near the clef, which is the
    only place the crop looks.
    """
    ink = _ink(gray)
    w = ink.shape[1]
    for fa, fb in LINE_WINDOW_FRACS:
        xa, xb = int(fa * w), int(fb * w)
        rows = np.nonzero(ink[:, xa:xb].mean(axis=1) > LINE_FILL_FRAC)[0]
        if not len(rows):
            continue
        groups = np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1)
        if len(groups) != 5:
            continue
        c = np.array([float(g.mean()) for g in groups])
        gaps = np.diff(c)
        if gaps.min() <= 0 or np.abs(gaps - gaps.mean()).max() > SPACING_MAX_REL_DEV * gaps.mean():
            continue
        return float(c[0]), float(c[-1]), float(xa)
    return None


@dataclass
class Prepared:
    sample_id: str
    variant: str
    status: str                      # ok | no_image | no_lines | no_edge
    deskew_deg: float = 0.0
    edge_ok: bool = False
    staff_space_px: float = float("nan")


def prepare(sample_dir: Path, variant: str) -> tuple[Prepared, Optional[np.ndarray]]:
    sid = sample_dir.name
    fn = sample_dir / (f"{sid}.png" if variant == "clean" else f"{sid}_distorted.jpg")
    gray = cv2.imread(str(fn), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return Prepared(sid, variant, "no_image"), None
    gray, angle = deskew(gray)
    lines = find_staff_lines(gray)
    if lines is None:
        return Prepared(sid, variant, "no_lines", angle), None
    top, bottom, _ = lines
    binary = np.where(_ink(gray), 0, 255).astype(np.uint8)
    x0 = ck.staff_left_edge(binary, top, bottom)
    if x0 is None:
        return Prepared(sid, variant, "no_edge", angle), None
    crop, x0s, edge_ok = store_crop(gray, float(x0), top, bottom)
    return (Prepared(sid, variant, "ok", angle, edge_ok, (bottom - top) / ck.STAFF_SPACES),
            canonical_input(crop, x0s))


def _worker_init() -> None:
    cv2.setNumThreads(1)


def work_chunk(dirs: Sequence[str]) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Optional[np.ndarray]]]]:
    out = []
    for d in dirs:
        p = Path(d)
        try:
            truth = parse_truth(p)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"skip {p.name}: label read failed: {exc}", flush=True)
            continue
        preps: dict[str, Any] = {}
        inputs: dict[str, Optional[np.ndarray]] = {}
        for v in VARIANTS:
            prep, x = prepare(p, v)
            preps[v] = asdict(prep)
            inputs[v] = x
        out.append((asdict(truth), preps, inputs))
    return out


# ==============================================================================================
# Statistics
# ==============================================================================================
def wilson(k: int, n: int, z: float = 1.959964) -> Optional[list[float]]:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, mid - half), min(1.0, mid + half)]


def cluster_bootstrap(correct: np.ndarray, clusters: np.ndarray, rng: np.random.Generator) -> Optional[list[float]]:
    """95% CI resampling whole source pieces: incipits of one piece are not independent draws."""
    if len(correct) == 0:
        return None
    ids, inv = np.unique(clusters, return_inverse=True)
    k = np.bincount(inv, weights=correct.astype(np.float64), minlength=len(ids))
    n = np.bincount(inv, minlength=len(ids)).astype(np.float64)
    draws = rng.integers(0, len(ids), size=(BOOTSTRAP_REPS, len(ids)))
    acc = k[draws].sum(axis=1) / n[draws].sum(axis=1)
    return [float(np.percentile(acc, 2.5)), float(np.percentile(acc, 97.5))]


def rate(correct: np.ndarray, clusters: np.ndarray, rng: np.random.Generator) -> dict[str, Any]:
    k, n = int(correct.sum()), int(len(correct))
    return {"k": k, "n": n, "acc": (k / n) if n else None, "wilson95": wilson(k, n),
            "piece_bootstrap95": cluster_bootstrap(correct, clusters, rng)}


# ==============================================================================================
# Main
# ==============================================================================================
@dataclass
class Model:
    net: Any
    clef_t: float
    key_t: float
    clef_thr: float
    key_thr: float
    meta: dict[str, Any] = field(default_factory=dict)


def load_model(path: Path, device: torch.device) -> Model:
    ckpt: dict[str, Any] = torch.load(path, map_location="cpu", weights_only=False)
    if ckpt.get("smoke_test"):
        raise RuntimeError(f"{path} is a smoke-test checkpoint")
    if ckpt["crop_spec_version"] != ck.CROP_SPEC_VERSION:
        raise RuntimeError(f"crop spec {ckpt['crop_spec_version']} != core {ck.CROP_SPEC_VERSION}")
    core = _lf_sha256(CORE_PATH)
    if ckpt["core_sha256"] != core:
        raise RuntimeError(f"clef_key_core.py sha {core} != checkpoint core_sha256 {ckpt['core_sha256']}: "
                           f"upload the core file the checkpoint was trained with")
    net = ck.ClefKeyNet(width=ckpt["arch"]["width"], dropout=ckpt["arch"]["dropout"])
    net.load_state_dict(ckpt["model_state"])
    net.to(device).eval()
    meta = {k: ckpt.get(k) for k in ("seed", "best_epoch", "created_utc", "core_sha256", "crop_spec_version",
                                     "g8vb_reliable")}
    return Model(net, float(ckpt["clef_temperature"]), float(ckpt["key_temperature"]),
                 float(ckpt["clef_threshold"]), float(ckpt["key_threshold"]), meta)


def list_samples(corpus: Path) -> list[Path]:
    dirs = sorted(Path(e.path) for e in os.scandir(corpus) if e.is_dir())
    if SAMPLE_N is not None and SAMPLE_N < len(dirs):
        dirs = sorted(random.Random(SAMPLE_SEED).sample(dirs, SAMPLE_N))
    return dirs


def summarise(rows: list[dict[str, Any]], variant: str, rng: np.random.Generator) -> dict[str, Any]:
    vr = [r for r in rows if r["variant"] == variant]
    other = ck.CLEF_CLASSES.index("other")
    status = {s: sum(r["status"] == s for r in vr) for s in ("ok", "no_image", "no_lines", "no_edge")}
    out: dict[str, Any] = {"n_samples": len(vr), "status": status,
                           "edge_fallback_used": sum(r["status"] == "ok" and not r["edge_ok"] for r in vr)}

    def clef_block(sel: list[dict[str, Any]]) -> dict[str, Any]:
        ok = [r for r in sel if r["status"] == "ok"]
        cl = np.array([r["piece_id"] for r in ok])
        corr = np.array([r["pred_clef"] == r["clef"] for r in ok], bool)
        itt_corr = np.array([r["status"] == "ok" and r["pred_clef"] == r["clef"] for r in sel], bool)
        sure = np.array([r["clef_sure"] for r in ok], bool)
        return {
            "scored": rate(corr, cl, rng),
            "all_incl_pipeline_failures_as_wrong": rate(itt_corr, np.array([r["piece_id"] for r in sel]), rng),
            "coverage_sure": float(sure.mean()) if len(sure) else None,
            "acc_when_sure": rate(corr[sure], cl[sure], rng),
            "confidently_wrong_rate": float((sure & ~corr).mean()) if len(sure) else None,
        }

    labelled = [r for r in vr if r["clef"] is not None]
    in_scope = [r for r in labelled if r["clef"] in ("G", "F")]
    out["clef_in_scope_G2_F4"] = clef_block(in_scope)
    out["clef_all_4class"] = clef_block(labelled)
    by_src: dict[str, Any] = {}
    for src in sorted({r["source_clef"] for r in labelled}):
        sel = [r for r in labelled if r["source_clef"] == src and r["status"] == "ok"]
        preds = {c: sum(r["pred_clef"] == c for r in sel) for c in ck.CLEF_CLASSES}
        by_src[src] = {"label": IN_SCOPE_SOURCE_CLEFS.get(src, "other"), "n_scored": len(sel),
                       "acc": (sum(r["pred_clef"] == r["clef"] for r in sel) / len(sel)) if sel else None,
                       "predicted": preds}
    out["clef_by_source_clef"] = by_src
    ok_l = [r for r in labelled if r["status"] == "ok"]
    out["clef_confusion_rows_true_cols_pred"] = {
        t: {p: sum(r["clef"] == t and r["pred_clef"] == p for r in ok_l) for p in ck.CLEF_CLASSES}
        for t in ck.CLEF_CLASSES}
    out["clef_other_predicted_on_in_scope"] = sum(r["pred_clef"] == ck.CLEF_CLASSES[other]
                                                  for r in in_scope if r["status"] == "ok")

    out["n_without_key_label_semantic_agnostic_disagree"] = sum(r["key"] is None for r in vr)
    # Split by clef: accidentals sit at clef-dependent heights, and the model never saw a C1/C2/G1
    # staff, so key errors there say nothing about PiyaNota's G/G8vb/F scope.
    out["key_in_scope_G2_F4"] = key_block([r for r in vr if r["clef"] in ("G", "F")], rng)
    out["key_other_clefs"] = key_block([r for r in vr if r["clef"] == "other"], rng)
    out["key"] = key_block(vr, rng)
    both = [r for r in in_scope if r["key"] is not None]
    out["clef_and_key_both_right_in_scope_incl_failures"] = rate(
        np.array([r["status"] == "ok" and r["pred_clef"] == r["clef"] and r["pred_key"] == r["key"] for r in both],
                 bool), np.array([r["piece_id"] for r in both]), rng)
    return out


def key_block(sel: list[dict[str, Any]], rng: np.random.Generator) -> dict[str, Any]:
    kl = [r for r in sel if r["key"] is not None]
    ok_k = [r for r in kl if r["status"] == "ok"]
    cl = np.array([r["piece_id"] for r in ok_k])
    corr = np.array([r["pred_key"] == r["key"] for r in ok_k], bool)
    sure = np.array([r["key_sure"] for r in ok_k], bool)
    return {
        "scored": rate(corr, cl, rng),
        "all_incl_pipeline_failures_as_wrong": rate(
            np.array([r["status"] == "ok" and r["pred_key"] == r["key"] for r in kl], bool),
            np.array([r["piece_id"] for r in kl]), rng),
        "coverage_sure": float(sure.mean()) if len(sure) else None,
        "acc_when_sure": rate(corr[sure], cl[sure], rng),
        "confidently_wrong_rate": float((sure & ~corr).mean()) if len(sure) else None,
        "acc_by_true_key": {int(k): {"n": sum(r["key"] == k for r in ok_k),
                                     "acc": float(np.mean([r["pred_key"] == k for r in ok_k if r["key"] == k]))}
                            for k in sorted({r["key"] for r in ok_k})},
        "off_by_one_share_of_errors": (float(np.mean([abs(r["pred_key"] - r["key"]) == 1
                                                      for r in ok_k if r["pred_key"] != r["key"]]))
                                       if (~corr).any() else None),
    }


def _pct(block: Optional[dict[str, Any]]) -> str:
    if not block or block.get("acc") is None:
        return "n/a"
    lo, hi = block["piece_bootstrap95"] or block["wilson95"]
    return f"{100 * block['acc']:.2f}% [{100 * lo:.2f}-{100 * hi:.2f}] (n={block['n']})"


def save_montage(images: list[np.ndarray], captions: list[str], path: Path) -> None:
    if not images:
        return
    cols = 6
    rows_n = math.ceil(len(images) / cols)
    tile_h, tile_w = ck.INPUT_H * 2 + 18, ck.INPUT_W * 2
    canvas = np.full((rows_n * tile_h, cols * tile_w), 255, np.uint8)
    for i, (im, cap) in enumerate(zip(images, captions)):
        r, c = divmod(i, cols)
        tile = cv2.resize((255 - im * 255).clip(0, 255).astype(np.uint8), (tile_w, ck.INPUT_H * 2),
                          interpolation=cv2.INTER_NEAREST)
        canvas[r * tile_h:r * tile_h + ck.INPUT_H * 2, c * tile_w:(c + 1) * tile_w] = tile
        cv2.putText(canvas, cap, (c * tile_w + 2, r * tile_h + ck.INPUT_H * 2 + 13), cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, 0, 1, cv2.LINE_AA)
    cv2.imwrite(str(path), canvas)


def main() -> None:
    t_start = time.time()
    corpus = _find_corpus()
    ckpt_path = _find_one("clef_key_classifier.pt", CHECKPOINT, "ClefKeyNet checkpoint")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(ckpt_path, device)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dirs = list_samples(corpus)
    print(f"corpus {corpus}: {len(dirs)} samples; checkpoint {ckpt_path}; device {device}; workers {WORKERS}",
          flush=True)

    rows: list[dict[str, Any]] = []
    errors: dict[str, list[tuple[np.ndarray, str]]] = {v: [] for v in VARIANTS}
    chunks = [[str(d) for d in dirs[i:i + CHUNK]] for i in range(0, len(dirs), CHUNK)]
    ctx = mp.get_context("fork") if hasattr(os, "fork") else mp.get_context("spawn")
    done = 0
    with ctx.Pool(WORKERS, initializer=_worker_init) as pool:
        for result in pool.imap(work_chunk, chunks):
            batch_x: list[np.ndarray] = []
            batch_ref: list[dict[str, Any]] = []
            for truth, preps, inputs in result:
                for v in VARIANTS:
                    row = {**truth, **preps[v], "pred_clef": None, "p_clef": None, "clef_sure": False,
                           "pred_key": None, "p_key": None, "key_sure": False}
                    rows.append(row)
                    if inputs[v] is not None:
                        batch_x.append(inputs[v])
                        batch_ref.append(row)
            if batch_x:
                with torch.no_grad():
                    pc, pk = ck.predict_probs(model.net, np.stack(batch_x), model.clef_t, model.key_t, device=device)
                for row, x, c, k in zip(batch_ref, batch_x, pc, pk):
                    ci, ki = int(c.argmax()), int(k.argmax())
                    row["pred_clef"], row["p_clef"] = ck.CLEF_CLASSES[ci], float(c[ci])
                    row["clef_sure"] = row["pred_clef"] != "other" and row["p_clef"] >= model.clef_thr
                    row["pred_key"], row["p_key"] = ck.index_to_key(ki), float(k[ki])
                    row["key_sure"] = row["p_key"] >= model.key_thr
                    v = row["variant"]
                    if (row["clef"] is not None and row["pred_clef"] != row["clef"]
                            and len(errors[v]) < SAVE_ERROR_EXAMPLES):
                        errors[v].append((x, f"{row['source_clef']}->{row['pred_clef']} {row['p_clef']:.2f}"))
            done += len(result)
            if done % (CHUNK * 20) < CHUNK or done == len(dirs):
                print(f"  {done}/{len(dirs)} samples  {time.time() - t_start:.0f}s", flush=True)

    rng = np.random.default_rng(SAMPLE_SEED)
    report: dict[str, Any] = {
        "what": "ClefKeyNet (frozen) on Camera-PrIMuS; out-of-source (never trained on CPM)",
        "checkpoint": str(ckpt_path), "checkpoint_meta": model.meta, "core_sha256": _lf_sha256(CORE_PATH),
        "thresholds": {"clef": model.clef_thr, "key": model.key_thr},
        "temperatures": {"clef": model.clef_t, "key": model.key_t},
        "corpus": str(corpus), "sample_n": len(dirs), "sample_seed": SAMPLE_SEED if SAMPLE_N else None,
        "device": str(device), "torch": torch.__version__, "opencv": cv2.__version__,
        "source_clef_counts": {s: sum(1 for r in rows if r["variant"] == VARIANTS[0] and r["source_clef"] == s)
                               for s in sorted({str(r["source_clef"]) for r in rows})},
        "results": {v: summarise(rows, v, rng) for v in VARIANTS},
        "seconds": round(time.time() - t_start, 1),
    }
    (OUT_DIR / "results.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    with open(OUT_DIR / "per_sample.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for v in VARIANTS:
        save_montage([e[0] for e in errors[v]], [e[1] for e in errors[v]], OUT_DIR / f"clef_errors_{v}.png")

    print("\n=== ClefKeyNet on Camera-PrIMuS (accuracy [95% CI, piece bootstrap]) ===")
    for v in VARIANTS:
        r = report["results"][v]
        print(f"\n[{v}] samples {r['n_samples']}  status {r['status']}  edge fallback {r['edge_fallback_used']}")
        print(f"  clef, in scope (G2->G, F4->F), scored        : {_pct(r['clef_in_scope_G2_F4']['scored'])}")
        print(f"  clef, in scope, failures counted wrong        : "
              f"{_pct(r['clef_in_scope_G2_F4']['all_incl_pipeline_failures_as_wrong'])}")
        print(f"  clef, in scope, coverage sure / acc when sure : "
              f"{r['clef_in_scope_G2_F4']['coverage_sure']} / {_pct(r['clef_in_scope_G2_F4']['acc_when_sure'])}")
        print(f"  clef, all 4 classes, scored                   : {_pct(r['clef_all_4class']['scored'])}")
        ki = r["key_in_scope_G2_F4"]
        print(f"  key, in scope, scored                         : {_pct(ki['scored'])}")
        print(f"  key, in scope, failures counted wrong         : {_pct(ki['all_incl_pipeline_failures_as_wrong'])}")
        print(f"  key, in scope, coverage sure / acc when sure  : {ki['coverage_sure']} / {_pct(ki['acc_when_sure'])}")
        print(f"  key, other clefs (C1..), scored               : {_pct(r['key_other_clefs']['scored'])}")
        print(f"  key, all clefs, scored                        : {_pct(r['key']['scored'])}")
        print(f"  in-scope clef predicted 'other' (unsure)      : {r['clef_other_predicted_on_in_scope']}")
        print(f"  clef AND key right (in scope, failures wrong) : "
              f"{_pct(r['clef_and_key_both_right_in_scope_incl_failures'])}")
        print("  by source clef:", {k: (b["n_scored"], None if b["acc"] is None else round(b["acc"], 4))
                                    for k, b in r["clef_by_source_clef"].items()})
    print(f"\nwrote {OUT_DIR}/results.json, per_sample.csv, clef_errors_<variant>.png  ({report['seconds']}s)")


if __name__ == "__main__":
    main()
