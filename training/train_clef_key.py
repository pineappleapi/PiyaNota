"""Local (terminal) training for the clef / key-signature staff-start classifier (PIYA-106).

Faithful port of training/piyanota-clef-keysig-kaggle.ipynb (which stays frozen as the Kaggle
fallback), with the 2026-09-26 amendment (docs/decisions/piya-106-clef-keysig-detector-plan.md,
"2026-09-26 amendment", part D and D.2) applied:

* The crop contract and the network come from the repo-root ``clef_key_core.py`` (imported, never
  copied), so Stage 3 and training cannot drift apart.
* Why a script and not the notebook: Windows multiprocessing uses spawn, which needs picklable top-level
  functions in an importable module behind an ``if __name__ == "__main__":`` guard. A terminal process
  with a log file and atomic per-epoch checkpoints also survives a GPU driver hang (2026-09-23).
* Real photos are never read here. The real-capture set is check-only and is scored by
  ``training/eval_clef_key_realval.py`` after the run is frozen. Temperatures, thresholds, epoch
  selection and ``g8vb_reliable`` are fitted on the DS2 / synthetic validation splits only.
* Pencil-stroke augmentation added (amendment A.6 item 3). It was motivated by looking at the
  validation photos; that disclosure is recorded in the checkpoint metadata.

Phases (``--phase``): ``prep`` (DS2 records + crops, synthetic renders, clean eval inputs, all cached),
``train`` (resumable), ``calibrate`` (temperatures / thresholds / G8vb gate on val only), ``eval`` (test and
stress metrics, export, parity fixture), or ``all``. Calibrate and eval load the best-epoch state from
``last.pt``, so a hang there never costs training.

Usage (from the repo root):
    python training/train_clef_key.py --smoke --device cpu --phase all
    python training/train_clef_key.py --seed 20260926 --device cuda --phase all
    python training/train_clef_key.py --resume training/clef_key_artifacts/<run_id> --phase all
"""
from __future__ import annotations

import os

# Must be set before torch is imported, or cuBLAS picks a non-deterministic workspace.
CUBLAS_WORKSPACE = ":4096:8"
os.environ["CUBLAS_WORKSPACE_CONFIG"] = CUBLAS_WORKSPACE

import argparse
import copy
import gc
import hashlib
import importlib.metadata
import inspect
import json
import logging
import math
import platform
import random
import re
import subprocess
import sys
import time
import warnings
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import clef_key_core as ck  # noqa: E402  (needs REPO_ROOT on sys.path)

try:  # Imported at module level so spawned worker processes get them too; checked in main().
    import verovio
except ImportError:  # reported with the exact pip command by check_render_versions()
    verovio = None
try:
    import resvg_py
except ImportError:
    resvg_py = None

logger = logging.getLogger("train_clef_key")

# ----------------------------------------------------------------------------------------------
# Settings (notebook cell 3). Anything here that changes the data or the training is part of a hash.
# ----------------------------------------------------------------------------------------------
DEFAULT_SEED = 20260926
DEFAULT_DS2 = Path(r"D:\PiyaNota\datasets\ds2_dense")
DEFAULT_ARTIFACTS = REPO_ROOT / "training" / "clef_key_artifacts"
DEFAULT_CACHE = REPO_ROOT / "training" / "clef_key_cache"
# The script must never write deployable weights; the user copies them there after review.
FORBIDDEN_OUTPUT_DIR = REPO_ROOT / "music_symbol_detection"
# The real-capture set is check-only (amendment A.4); this script must not read it.
FORBIDDEN_INPUT_MARKER = "piyanota_dataset"

VEROVIO_VERSION = "6.3.0"
RESVG_VERSION = "0.5.0"
PIP_INSTALL_CMD = f'"{sys.executable}" -m pip install verovio=={VEROVIO_VERSION} resvg-py=={RESVG_VERSION}'

N_SYNTH_SYSTEMS_FULL, N_SYNTH_SYSTEMS_SMOKE = 3000, 24
MAX_DS2_IMAGES_SMOKE = 24            # full run: all DS2 pages
EPOCHS_FULL, EPOCHS_SMOKE = 24, 2
BATCH_SIZE = 128                     # fp32; ~1.5 GB activations, fits a display-attached 4 GB GTX 1650
EVAL_BATCH = 256                     # not 512: leaves headroom on the 4 GB card
LR = 1e-3
WEIGHT_DECAY = 1e-4
N_PROC = 8                           # crop-extraction / render processes
NUM_WORKERS = 0                      # per-sample RNG makes augmentation worker-independent anyway
INLINE_BELOW = 256                   # smaller jobs are cheaper inline than spawning 8 processes
GPU_MEMORY_FRACTION = 0.85           # a leak fails as a Python OOM instead of pushing the driver
NVIDIA_SMI_TIMEOUT_S = 30
EXIT_BAD_ENV, EXIT_OOM, EXIT_GPU_HANG, EXIT_REFUSED = 2, 3, 4, 5

TRAIN_BUCKETS = 70
VAL_BUCKETS = 15
DS2_UNSEEN_FONT = "gonville"
SYNTH_TRAIN_FONTS = ("Leland", "Bravura", "Leipzig", "Petaluma")
SYNTH_UNSEEN_FONT = "Gootville"
SYNTH_UNSEEN_FONT_PERCENT = 15
SYNTH_TRAIN_PERCENT, SYNTH_VAL_PERCENT_END = 80, 90

# Pre-registered decision rules (fixed BEFORE any result; do not tune after a run).
CLEF_SELECTIVE_TARGET = 0.995
KEY_SELECTIVE_TARGET = 0.99
MIN_SELECTED_FOR_THRESHOLD = 20
G8VB_MIN_RECALL = 0.95
G8VB_MAX_G_CONFUSION = 0.02
G8VB_MIN_SUPPORT = 30
UNSURE_THRESHOLD = 1.01              # "always unsure" when a target cannot be reached

# ----------------------------------------------------------------------------------------------
# DS2 label rules (notebook cell 13)
# ----------------------------------------------------------------------------------------------
PIECE_RE = re.compile(r"^lg-(.+?)-aug-([a-z0-9]+)-")
CLEF_CATS = {"clefG": "G", "clefF": "F", "clefCAlto": "C", "clefCTenor": "C", "clefUnpitchedPercussion": "perc"}
WANTED = set(CLEF_CATS) | {"clef8", "clef15", "keySharp", "keyFlat", "keyNatural", "staff"}
KEY_IGNORE = ck.KEY_IGNORE_INDEX

# ----------------------------------------------------------------------------------------------
# Stored crop format and Stage 1-like binarisation (notebook cell 17)
# ----------------------------------------------------------------------------------------------
STORE_PPS = 12
STORE_LEFT, STORE_RIGHT, STORE_ABOVE, STORE_BELOW = 4.0, 19.0, 7.0, 7.0
STORE_W = int(round((STORE_LEFT + STORE_RIGHT) * STORE_PPS))                    # 276
STORE_H = int(round((STORE_ABOVE + ck.STAFF_SPACES + STORE_BELOW) * STORE_PPS))  # 216
STORE_TOP = STORE_ABOVE * STORE_PPS - 0.5
STORE_BOTTOM = STORE_TOP + ck.STAFF_SPACES * STORE_PPS
STORE_X0 = STORE_LEFT * STORE_PPS - 0.5

CANON_BLOCK_SPACES = 2.5
CANON_C = 10.0
CANON_UPSCALE = 2.0
BLUR_SPACES = 0.035
BG_KERNEL_SPACES = 1.5

# ----------------------------------------------------------------------------------------------
# Synthetic systems (notebook cell 21)
# ----------------------------------------------------------------------------------------------
SYNTH_CLEFS = {
    "G": ("G", 2, None, None, "G", 4 * 7 + 2),
    "G8vb": ("G", 2, 8, "below", "G8vb", 3 * 7 + 2),
    "F": ("F", 4, None, None, "F", 2 * 7 + 4),
    "C3": ("C", 3, None, None, "other", 3 * 7 + 3),
    "C4": ("C", 4, None, None, "other", 3 * 7 + 1),
    "G8va": ("G", 2, 8, "above", "other", 5 * 7 + 2),
    "F8vb": ("F", 4, 8, "below", "other", 1 * 7 + 4),
}
SYNTH_CLEF_WEIGHTS = {"G": 0.30, "G8vb": 0.25, "F": 0.30, "C3": 0.05, "C4": 0.05, "G8va": 0.03, "F8vb": 0.02}
SYNTH_LABELS = ["Soprano", "Alto", "Tenor", "Bass", "S.", "A.", "T.", "B.", "Sop.", "Ten.", "Soloist",
                "Solo", "Voice", "Choir", "Men", "Women", "S 1", "T 2", "Bar.", "Mezzo", "", "", ""]
SYLLABLES = ["la", "ah", "oh", "sing", "Glo", "ri", "a", "praise", "the", "Lord", "ma", "hal", "le",
             "lu", "ja", "love", "ka", "sa", "ma", "mo", "Pa", "sko", "ng", "ta", "yo"]
PNAMES = "cdefgab"
KEY_VALUES = np.arange(ck.KEY_MIN, ck.KEY_MAX + 1)
KEY_WEIGHTS = np.where(np.abs(KEY_VALUES) <= 4, 1.0, 0.5)
KEY_WEIGHTS = KEY_WEIGHTS / KEY_WEIGHTS.sum()
SYNTH_TARGET_SP = (14.0, 28.0)
SP_CALIBRATION_FONT = "Leipzig"

# ----------------------------------------------------------------------------------------------
# Augmentation (notebook cell 25) plus the amendment's pencil strokes
# ----------------------------------------------------------------------------------------------
GEO_DX, GEO_DY, GEO_SCALE, GEO_ANGLE = 0.6, 0.3, (0.9, 1.1), 1.5
# Pencil strokes (amendment A.6 item 3). MOTIVATED BY LOOKING AT THE VALIDATION PHOTOS (Livin' on a
# Prayer pg09 pencil loops crossing staff starts, Dormi Jesu circled dynamics): design-level exposure,
# not a parameter fit; the values below were chosen from general pencil geometry, not measured on them.
PENCIL_PROB = 0.3
PENCIL_MAX_STROKES = 3
PENCIL_THICKNESS_PX = (1, 3)         # at STORE_PPS = 12 px/space: ~0.08-0.25 staff space
PENCIL_GREY = (30, 171)              # dark graphite to light grey (upper bound exclusive)
PENCIL_CTRL_OVERSHOOT = 0.15         # control points may lie this fraction outside the crop
PENCIL_CURVE_POINTS = 48
PENCIL_DISCLOSURE = ("pencil_stroke augmentation added 2026-09-26 per amendment A.6 item 3; motivated by "
                     "viewing the real validation photos (Livin' on a Prayer pencil loops, Dormi Jesu circled "
                     "dynamics); design-level exposure, parameters not fitted to those photos")

STRESS_SEED_OFFSET = 1000
FIXTURE_PER_SET = 8
RELOAD_ATOL = 1e-4


# ==============================================================================================
# Small helpers
# ==============================================================================================
def sha256_bytes(data: bytes) -> str:
    """Hex sha256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text_file(path: Path) -> str:
    """sha256 of a text file with CRLF normalised to LF.

    Why: the repo has core.autocrlf=true, so a fresh Windows checkout rewrites LF files as CRLF.
    Hashing raw bytes would make the same code look different depending on how it was checked out.
    """
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    """Streaming sha256 of a (possibly large) binary file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def stable_hash(obj: Any) -> str:
    """sha256 of a canonical JSON dump (sorted keys), for config/cache keys."""
    return sha256_bytes(json.dumps(obj, sort_keys=True, default=str).encode("utf-8"))


def source_hash(funcs: Iterable[Callable[..., Any]]) -> str:
    """Hash of function source texts, so editing prep code invalidates the cache instead of reusing it."""
    return sha256_bytes("\n".join(inspect.getsource(f) for f in funcs).encode("utf-8"))


CORE_PATH = REPO_ROOT / "clef_key_core.py"
CORE_SHA256 = sha256_text_file(CORE_PATH)
SCRIPT_SHA256 = sha256_text_file(Path(__file__).resolve())


def atomic_write_text(path: Path, text: str) -> None:
    """Write-then-rename so a crash never leaves a half-written file behind."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_torch_save(obj: Any, path: Path) -> None:
    """torch.save to a temp file then os.replace (atomic on the same volume)."""
    tmp = path.with_name(path.name + ".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def json_default(o: Any) -> Any:
    """JSON encoder fallback for numpy scalars/arrays (notebook cell 35)."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def seed_everything(seed: int) -> None:
    """Seeds python, numpy and torch (CPU + all CUDA devices)."""
    random.seed(seed)
    np.random.seed(seed % (2 ** 32))
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def guard_paths(*paths: Path) -> None:
    """Refuses any input/output path inside piyanota_dataset or music_symbol_detection."""
    forbidden_out = FORBIDDEN_OUTPUT_DIR.resolve()
    for p in paths:
        rp = p.resolve()
        if FORBIDDEN_INPUT_MARKER in {part.lower() for part in rp.parts}:
            raise SystemExit(f"Refusing path {rp}: piyanota_dataset is never read or written by training.")
        if rp == forbidden_out or forbidden_out in rp.parents:
            raise SystemExit(f"Refusing path {rp}: training never writes to {forbidden_out}.")


# ==============================================================================================
# Run configuration
# ==============================================================================================
@dataclass
class RunConfig:
    """Everything that decides the data and the training. Hashed into every checkpoint."""
    seed: int
    smoke: bool
    n_synth_systems: int
    max_ds2_images: Optional[int]
    epochs: int
    batch_size: int = BATCH_SIZE
    eval_batch: int = EVAL_BATCH
    lr: float = LR
    weight_decay: float = WEIGHT_DECAY
    num_workers: int = NUM_WORKERS

    @classmethod
    def build(cls, seed: int, smoke: bool) -> "RunConfig":
        return cls(seed=seed, smoke=smoke,
                   n_synth_systems=N_SYNTH_SYSTEMS_SMOKE if smoke else N_SYNTH_SYSTEMS_FULL,
                   max_ds2_images=MAX_DS2_IMAGES_SMOKE if smoke else None,
                   epochs=EPOCHS_SMOKE if smoke else EPOCHS_FULL)

    def hash_payload(self) -> dict[str, Any]:
        """Config + every training/selection constant; a resumed run must match it exactly."""
        return {
            "run": self.__dict__,
            "splits": [TRAIN_BUCKETS, VAL_BUCKETS, DS2_UNSEEN_FONT, SYNTH_TRAIN_FONTS, SYNTH_UNSEEN_FONT,
                       SYNTH_UNSEEN_FONT_PERCENT, SYNTH_TRAIN_PERCENT, SYNTH_VAL_PERCENT_END],
            "rules": [CLEF_SELECTIVE_TARGET, KEY_SELECTIVE_TARGET, MIN_SELECTED_FOR_THRESHOLD, G8VB_MIN_RECALL,
                      G8VB_MAX_G_CONFUSION, G8VB_MIN_SUPPORT],
            "aug": [GEO_DX, GEO_DY, GEO_SCALE, GEO_ANGLE, PENCIL_PROB, PENCIL_MAX_STROKES, PENCIL_THICKNESS_PX,
                    PENCIL_GREY, PENCIL_CTRL_OVERSHOOT, PENCIL_CURVE_POINTS],
            "canon": [CANON_BLOCK_SPACES, CANON_C, CANON_UPSCALE, BLUR_SPACES, BG_KERNEL_SPACES],
            "cublas": CUBLAS_WORKSPACE,
        }

    def config_hash(self) -> str:
        return stable_hash(self.hash_payload())


# ==============================================================================================
# Environment checks
# ==============================================================================================
def _dist_version(*names: str) -> Optional[str]:
    for n in names:
        try:
            return importlib.metadata.version(n)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def check_render_versions() -> dict[str, str]:
    """Asserts the pinned Verovio / resvg-py versions (a different renderer changes the synthetic pixels).

    Exits with EXIT_BAD_ENV and the exact pip command if they are missing or wrong.
    """
    problems: list[str] = []
    vv = "missing"
    if verovio is None:
        problems.append("verovio is not installed")
    else:
        vv = verovio.toolkit().getVersion()
        if not vv.startswith(VEROVIO_VERSION):
            problems.append(f"verovio {vv} != {VEROVIO_VERSION}")
    rv = _dist_version("resvg-py", "resvg_py") or "missing"
    if resvg_py is None:
        problems.append("resvg-py is not installed")
    elif rv != RESVG_VERSION:
        problems.append(f"resvg-py {rv} != {RESVG_VERSION}")
    if problems:
        print("ERROR: " + "; ".join(problems), file=sys.stderr)
        print(f"Install the pinned versions with:\n    {PIP_INSTALL_CMD}", file=sys.stderr)
        raise SystemExit(EXIT_BAD_ENV)
    return {"verovio": vv, "resvg_py": rv}


def query_nvidia_smi() -> str:
    """Runs nvidia-smi once, with a timeout, before any CUDA work.

    Why: the driver wedged on 2026-09-23; a hanging nvidia-smi is the early warning, so GPU work
    stops here instead of in the middle of training.
    """
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total",
                            "--format=csv"], capture_output=True, text=True, timeout=NVIDIA_SMI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        logger.error("nvidia-smi did not answer within %ds: the GPU driver may be wedged. Stopping GPU work; "
                     "restart the PC, then --resume.", NVIDIA_SMI_TIMEOUT_S)
        raise SystemExit(EXIT_GPU_HANG)
    except FileNotFoundError:
        return "nvidia-smi not found"
    if r.returncode != 0:
        return f"nvidia-smi failed (rc={r.returncode}): {r.stderr.strip()}"
    return r.stdout.strip()


def setup_device(device_arg: str) -> tuple[torch.device, dict[str, Any]]:
    """Picks the device, applies determinism switches and the GPU memory cap, and records the GPU."""
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)
    cv2.setNumThreads(1)
    info: dict[str, Any] = {"cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG")}
    if device_arg == "cuda":
        smi = query_nvidia_smi()
        info["nvidia_smi"] = smi
        if not torch.cuda.is_available():
            logger.error("--device cuda requested but torch.cuda.is_available() is False.")
            raise SystemExit(EXIT_BAD_ENV)
        device = torch.device("cuda")
        torch.cuda.set_per_process_memory_fraction(GPU_MEMORY_FRACTION, 0)
        info["gpu_name"] = torch.cuda.get_device_name(0)
        info["memory_fraction"] = GPU_MEMORY_FRACTION
        logger.info("nvidia-smi: %s", smi.replace("\n", " | "))
    else:
        device = torch.device("cpu")
    info.update({"device_type": device.type, "torch": torch.__version__, "cuda": torch.version.cuda,
                 "cudnn": torch.backends.cudnn.version()})
    logger.info("device %s | gpu %s | torch %s | cuda %s | cudnn %s", device.type, info.get("gpu_name", "-"),
                torch.__version__, torch.version.cuda, torch.backends.cudnn.version())
    return device, info


def build_versions(device: torch.device, render: dict[str, str]) -> dict[str, Any]:
    """Same keys as the notebook's VERSIONS (cell 7)."""
    return {"python": platform.python_version(), "torch": torch.__version__, "cuda": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(), "opencv": cv2.__version__, "numpy": np.__version__,
            "verovio": render["verovio"], "resvg_py": render["resvg_py"],
            "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu"}


# ==============================================================================================
# DS2 labels (notebook cell 13)
# ==============================================================================================
def _small_ink_near(clef_box: Sequence[float], boxes: list[list[float]], sp: float, where: str) -> bool:
    """True if any small box (a DS2 clef8/clef15) sits directly below/above the clef box."""
    cx0, cy0, cx1, cy1 = clef_box
    for b in boxes:
        bx = 0.5 * (b[0] + b[2])
        if not (cx0 - 0.5 * sp <= bx <= cx1 + 0.5 * sp):
            continue
        if where == "below" and cy1 - 1.0 * sp <= b[1] <= cy1 + 1.5 * sp:
            return True
        if where == "above" and cy0 - 1.5 * sp <= b[3] <= cy0 + 1.0 * sp:
            return True
    return False


def ds2_staff_records(json_path: Path, tag: str) -> tuple[list[dict[str, Any]], Counter]:
    """Opening clef + key-signature label for every DS2 staff box of one annotation JSON.

    The JSON (226 MB for train) is parsed here and released before returning; the caller calls
    gc.collect() before parsing the next one, so peak RAM holds only one parsed file.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    name_by_id = {k: v["name"] for k, v in d["categories"].items() if v["annotation_set"] == "deepscores"}
    stats: Counter = Counter()
    records: list[dict[str, Any]] = []
    for im in d["images"]:
        m = PIECE_RE.match(im["filename"])
        if not m:
            stats["bad_filename"] += 1
            continue
        piece, font = m.group(1), m.group(2)
        objs: dict[str, list[list[float]]] = defaultdict(list)
        for aid in im["ann_ids"]:
            a = d["annotations"][aid]
            names = {name_by_id[c] for c in a["cat_id"] if c in name_by_id}
            for n in names & WANTED:
                objs[n].append([float(v) for v in a["a_bbox"]])
        clefs = [(n, b) for n in CLEF_CATS for b in objs[n]]
        for si, sb in enumerate(sorted(objs["staff"], key=lambda b: b[1])):
            x0, y0, x1, y1 = sb
            sp = (y1 - y0) / 4.0
            if sp <= 2:
                stats["tiny_staff"] += 1
                continue
            cand = [(n, b) for n, b in clefs
                    if b[0] < x0 + 5 * sp and b[2] > x0 - 1 * sp and y0 - sp <= 0.5 * (b[1] + b[3]) <= y1 + sp]
            if not cand:
                stats["no_opening_clef"] += 1
                continue
            cname, cb = min(cand, key=lambda t: t[1][0])
            base = CLEF_CATS[cname]
            below8 = _small_ink_near(cb, objs["clef8"], sp, "below")
            above8 = _small_ink_near(cb, objs["clef8"], sp, "above")
            any15 = (_small_ink_near(cb, objs["clef15"], sp, "below")
                     or _small_ink_near(cb, objs["clef15"], sp, "above"))
            if base == "G" and below8 and not above8 and not any15:
                clef = "G8vb"
            elif base == "G" and not (below8 or above8 or any15):
                clef = "G"
            elif base == "F" and not (below8 or above8 or any15):
                clef = "F"
            else:
                clef = "other"

            def _in_key_zone(b: list[float]) -> bool:
                cx, cy = 0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3])
                return cb[2] - 0.3 * sp <= cx <= cb[2] + 10 * sp and y0 - 2 * sp <= cy <= y1 + 2 * sp

            ns = sum(_in_key_zone(b) for b in objs["keySharp"])
            nf = sum(_in_key_zone(b) for b in objs["keyFlat"])
            nn_ = sum(_in_key_zone(b) for b in objs["keyNatural"])
            if nn_ or (ns and nf) or max(ns, nf) > ck.KEY_MAX:
                key, key_note = KEY_IGNORE, "ambiguous"
                stats["key_ignored"] += 1
            else:
                key, key_note = (ns if ns else -nf), "ok"
            stats[f"clef_{clef}"] += 1
            records.append({"source": "ds2", "json": tag, "filename": im["filename"], "piece": piece,
                            "font": font, "staff_idx": si, "bbox": sb, "clef": clef, "clef_raw": cname,
                            "key": key, "key_note": key_note})
    del d
    return records, stats


# ==============================================================================================
# Splits (notebook cell 15)
# ==============================================================================================
def bucket(key: str) -> int:
    """Stable 0-99 bucket of a string (sha1), independent of Python's hash seed."""
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % 100


def split_for_bucket(b: int) -> str:
    return "train" if b < TRAIN_BUCKETS else ("val" if b < TRAIN_BUCKETS + VAL_BUCKETS else "test")


def assign_ds2_splits(records: list[dict[str, Any]], max_images: Optional[int]) -> list[dict[str, Any]]:
    """Piece-level split, gonville test-only, then the smoke subset (a few pages from every split)."""
    for r in records:
        s: Optional[str] = split_for_bucket(bucket("ds2:" + r["piece"]))
        if r["font"] == DS2_UNSEEN_FONT:
            s = "test_unseen_font" if s == "test" else None
        r["split"] = s
    records = [r for r in records if r["split"] is not None]
    official: dict[str, set[str]] = defaultdict(set)
    for r in records:
        official[r["json"]].add(r["piece"])
    logger.info("pieces in BOTH official DS2 train and test: %d (this is why we re-split)",
                len(official["official_train"] & official["official_test"]))
    if max_images is not None:
        keep: set[str] = set()
        by_split: dict[str, list[str]] = defaultdict(list)
        for fn, s in sorted({(r["filename"], r["split"]) for r in records}):
            by_split[s].append(fn)
        for s, fns in by_split.items():
            keep |= set(sorted(fns, key=lambda x: bucket("pick:" + x))[:max(1, max_images // 4)])
        records = [r for r in records if r["filename"] in keep]
    piece_split: dict[str, set[str]] = defaultdict(set)
    for r in records:
        piece_split[r["piece"]].add("test" if r["split"].startswith("test") else r["split"])
    if not all(len(v) == 1 for v in piece_split.values()):
        raise RuntimeError("a DS2 piece landed in two splits")
    logger.info("DS2 split counts: %s", dict(Counter(r["split"] for r in records)))
    return records


# ==============================================================================================
# Binarisation and stored crops (notebook cell 17)
# ==============================================================================================
def _odd(v: float) -> int:
    return max(3, int(round(v)) | 1)


def binarize_like_stage1(gray: np.ndarray, sp_px: float, block_spaces: float = CANON_BLOCK_SPACES,
                         c: float = CANON_C) -> np.ndarray:
    """Background-normalise, blur, adaptive Gaussian threshold. Returns ink = 0, paper = 255.

    Mirrors stage1_preprocessing._build_strip_source (divide by background, Gaussian blur, adaptive
    Gaussian threshold, C = 10) with the window expressed in staff spaces instead of fixed pixels.
    """
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


def store_crop(gray_page: np.ndarray, x0: float, top: float, bottom: float) -> tuple[np.ndarray, float, bool]:
    """Grey storage crop plus the staff-start column found the way Stage 3 finds it."""
    crop = ck.warp_staff_region(gray_page, x0, top, bottom, STORE_PPS, STORE_LEFT, STORE_RIGHT,
                                STORE_ABOVE, STORE_BELOW)
    edge = ck.staff_left_edge(binarize_like_stage1(crop, STORE_PPS), STORE_TOP, STORE_BOTTOM)
    if edge is None or abs(edge - STORE_X0) > 2 * STORE_PPS:
        return crop, float(STORE_X0), False
    return crop, float(edge), True


def refine_staff_lines(gray: np.ndarray, bbox: Sequence[float]) -> tuple[float, float, bool]:
    """Centre rows of the top and bottom staff line inside a DS2 staff box."""
    x0, y0, x1, y1 = bbox
    h = gray.shape[0]
    pad = 4
    ya, yb = max(0, int(y0) - pad), min(h, int(math.ceil(y1)) + pad + 1)
    xa, xb = int(x0 + 0.1 * (x1 - x0)), int(x1 - 0.1 * (x1 - x0))
    frac = (gray[ya:yb, xa:xb] < 128).mean(axis=1)
    rows = np.nonzero(frac > 0.5)[0]
    groups = np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1) if len(rows) else []
    if len(groups) == 5:
        c = [ya + float(g.mean()) for g in groups]
        return c[0], c[-1], True
    return y0 + 1.0, y1 - 1.0, False


def _init_prep_worker() -> None:
    """Spawned workers: one OpenCV thread each, so 8 processes do not oversubscribe the CPU."""
    cv2.setNumThreads(1)


def process_ds2_image(job: tuple[str, str, list[tuple[int, list[float]]]]
                      ) -> tuple[str, list[tuple[int, np.ndarray, float, bool, bool]]]:
    """Worker: one DS2 page -> grey stored crops of its labelled staves (notebook cell 19)."""
    image_dir, fn, recs = job
    gray = cv2.imread(str(Path(image_dir) / fn), cv2.IMREAD_GRAYSCALE)
    out: list[tuple[int, np.ndarray, float, bool, bool]] = []
    if gray is None:
        return fn, out
    for row, bbox in recs:
        top, bottom, lines_ok = refine_staff_lines(gray, bbox)
        crop, x0s, edge_ok = store_crop(gray, bbox[0], top, bottom)
        out.append((row, crop, x0s, lines_ok, edge_ok))
    return fn, out


# ==============================================================================================
# Synthetic systems (notebook cell 21); seed is an argument instead of a notebook global
# ==============================================================================================
def _note_xml(rng: np.random.Generator, bottom_diatonic: int, dur: str, dots: str, lyric: bool) -> str:
    if rng.random() < 0.10:
        return f'<rest dur="{dur}"{dots}/>'
    pos = int(rng.integers(-3, 12))
    d = bottom_diatonic + pos
    accid = ""
    if rng.random() < 0.12:
        accid = f' accid="{rng.choice(["s", "f", "n"])}"'
    syl = f'<verse n="1"><syl>{rng.choice(SYLLABLES)}</syl></verse>' if lyric else ""
    return f'<note pname="{PNAMES[d % 7]}" oct="{d // 7}" dur="{dur}"{dots}{accid}>{syl}</note>'


def _measure_xml(rng: np.random.Generator, beats: int, bottom_diatonic: int, lyric: bool) -> str:
    left, parts = float(beats), []
    while left > 1e-6:
        opts = [(q, dur, dots) for q, dur, dots in ((4, "1", ""), (3, "2", ' dots="1"'), (2, "2", ""),
                                                   (1, "4", ""), (0.5, "8", "")) if q <= left + 1e-6]
        q, dur, dots = opts[int(rng.integers(len(opts)))]
        if q == 0.5:
            parts += [_note_xml(rng, bottom_diatonic, "8", "", lyric) for _ in range(2)]
            left -= 1.0
        else:
            parts.append(_note_xml(rng, bottom_diatonic, dur, dots, lyric))
            left -= q
    return "".join(parts)


def make_system(sys_id: int, seed: int) -> tuple[str, list[dict[str, Any]], dict[str, Any], float]:
    """One synthetic 4-staff system: (MEI text, per-staff labels, Verovio options, target staff space)."""
    rng = np.random.default_rng([seed, 7, sys_id])
    names = list(SYNTH_CLEF_WEIGHTS)
    p = np.array([SYNTH_CLEF_WEIGHTS[n] for n in names])
    clefs = [names[i] for i in rng.choice(len(names), size=4, p=p / p.sum())]
    key = int(rng.choice(KEY_VALUES, p=KEY_WEIGHTS))
    sig = "0" if key == 0 else f"{abs(key)}{'s' if key > 0 else 'f'}"
    beats = int(rng.choice([2, 3, 4]))
    meter_vis = "" if rng.random() < 0.5 else ' visible="false"'
    n_measures = int(rng.integers(2, 4))
    lyric_staff = [rng.random() < 0.4 for _ in range(4)]
    staff_defs, labels = [], []
    for n, cname in enumerate(clefs, start=1):
        shape, line, dis, place, cls, _ = SYNTH_CLEFS[cname]
        dis_xml = f' dis="{dis}" dis.place="{place}"' if dis else ""
        lab = SYNTH_LABELS[int(rng.integers(len(SYNTH_LABELS)))]
        lab_xml = f"<label>{lab}</label>" if lab else ""
        staff_defs.append(f'<staffDef n="{n}" lines="5">{lab_xml}<clef shape="{shape}" line="{line}"{dis_xml}/>'
                          f'<keySig sig="{sig}"/><meterSig count="{beats}" unit="4"{meter_vis}/></staffDef>')
        labels.append({"clef_name": cname, "clef": cls, "key": key, "label": lab, "lyrics": lyric_staff[n - 1]})
    measures = []
    for m in range(1, n_measures + 1):
        staves = "".join(f'<staff n="{n}"><layer n="1">'
                         f'{_measure_xml(rng, beats, SYNTH_CLEFS[c][5], lyric_staff[n - 1])}</layer></staff>'
                         for n, c in enumerate(clefs, start=1))
        dyn = ""
        if m == 1 and rng.random() < 0.3:
            dyn = f'<dynam staff="{int(rng.integers(1, 5))}" tstamp="1">{rng.choice(["p", "mf", "f", "mp"])}</dynam>'
        measures.append(f'<measure n="{m}">{staves}{dyn}</measure>')
    symbol = rng.choice(["bracket", "brace", "none"])
    grp_attr = f' symbol="{symbol}"' if symbol != "none" else ""
    mei = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0">'
           '<meiHead><fileDesc><titleStmt><title>s</title></titleStmt><pubStmt/></fileDesc></meiHead>'
           '<music><body><mdiv><score><scoreDef>'
           f'<staffGrp{grp_attr} bar.thru="{"true" if rng.random() < 0.3 else "false"}">'
           + "".join(staff_defs) + '</staffGrp></scoreDef><section>' + "".join(measures)
           + '</section></score></mdiv></body></music></mei>')
    options = {"breaks": "none", "adjustPageHeight": True, "header": "none", "footer": "none",
               "scale": 100, "spacingStaff": int(rng.integers(7, 15)),
               "spacingLinear": float(rng.uniform(0.2, 0.35)), "spacingNonLinear": float(rng.uniform(0.5, 0.7)),
               "staffLineWidth": float(rng.uniform(0.12, 0.25)), "stemWidth": float(rng.uniform(0.15, 0.3)),
               "lyricSize": float(rng.uniform(3.5, 5.0))}
    target_sp = float(rng.uniform(*SYNTH_TARGET_SP))
    return mei, labels, options, target_sp


def find_staves_clean(gray: np.ndarray) -> list[tuple[float, float]]:
    """Top/bottom line centre rows of each staff in a clean render (row-projection)."""
    frac = (gray < 128).mean(axis=1)
    if frac.max() <= 0:
        return []
    rows = np.nonzero(frac > 0.5 * frac.max())[0]
    groups = np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1) if len(rows) else []
    lines = [float(g.mean()) for g in groups]
    staves, i = [], 0
    while i + 5 <= len(lines):
        gaps = np.diff(lines[i:i + 5])
        if gaps.min() > 2 and gaps.max() / gaps.min() <= 1.2:
            staves.append((lines[i], lines[i + 4]))
            i += 5
        else:
            i += 1
    return staves


_TK: Any = None  # one Verovio toolkit per process (safe under spawn: each worker makes its own)


def _toolkit() -> Any:
    global _TK
    if _TK is None:
        _TK = verovio.toolkit()
    return _TK


def render_gray(mei: str, options: dict[str, Any], font: str, zoom: float) -> np.ndarray:
    """MEI -> SVG (Verovio) -> grey pixels (resvg)."""
    tk = _toolkit()
    tk.setOptions({**options, "font": font})
    if not tk.loadData(mei):
        raise ValueError("verovio could not load the MEI")
    svg = tk.renderToSVG(1)
    png = resvg_py.svg_to_bytes(svg_string=svg, background="#ffffff", zoom=float(zoom))
    return cv2.imdecode(np.frombuffer(bytes(png), np.uint8), cv2.IMREAD_GRAYSCALE)


def staff_space_at_zoom1(seed: int) -> float:
    """Measured once: staff space in pixels at zoom 1 (Verovio scale 100)."""
    mei, _, opts, _ = make_system(0, seed)
    g = render_gray(mei, opts, SP_CALIBRATION_FONT, 1.0)
    st = find_staves_clean(g)
    if not st:
        raise RuntimeError("calibration render has no staves")
    return float(np.median([(b - t) / 4.0 for t, b in st]))


def synth_font_and_split(sys_id: int, seed: int) -> tuple[str, str]:
    if bucket(f"synthfont:{seed}:{sys_id}") < SYNTH_UNSEEN_FONT_PERCENT:
        return SYNTH_UNSEEN_FONT, "test_unseen_font"
    rng = np.random.default_rng([seed, 8, sys_id])
    font = SYNTH_TRAIN_FONTS[int(rng.integers(len(SYNTH_TRAIN_FONTS)))]
    b = bucket(f"synthsplit:{seed}:{sys_id}")
    return font, ("train" if b < SYNTH_TRAIN_PERCENT else ("val" if b < SYNTH_VAL_PERCENT_END else "test"))


def process_synth_system(sys_id: int, seed: int, sp_zoom1: float
                         ) -> tuple[int, Optional[list[tuple[np.ndarray, dict[str, Any]]]], str]:
    """Worker: render one synthetic system and cut its 4 stored crops."""
    mei, labels, opts, target_sp = make_system(sys_id, seed)
    font, split = synth_font_and_split(sys_id, seed)
    try:
        gray = render_gray(mei, opts, font, target_sp / sp_zoom1)
    except (ValueError, RuntimeError) as e:
        return sys_id, None, f"render_error:{e}"
    staves = find_staves_clean(gray)
    if len(staves) != 4:
        return sys_id, None, f"found_{len(staves)}_staves"
    out = []
    for si, ((top, bottom), lab) in enumerate(zip(staves, labels)):
        x0 = ck.staff_left_edge(gray, top, bottom)
        if x0 is None:
            return sys_id, None, "no_staff_start"
        crop, x0s, _edge_ok = store_crop(gray, x0, top, bottom)
        out.append((crop, {"source": "synth", "sys_id": sys_id, "staff_idx": si, "font": font,
                           "split": split, "x0_store": x0s, **lab}))
    return sys_id, out, "ok"


# ==============================================================================================
# Augmentation and inputs (notebook cell 25 + pencil strokes)
# ==============================================================================================
def pencil_strokes(g: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Draws 1-PENCIL_MAX_STROKES thin grey cubic Bezier curves across a grey uint8 crop, in place.

    Amendment A.6 item 3: choir scores carry singers' pencil marks crossing staff starts. MOTIVATED BY
    LOOKING AT THE VALIDATION PHOTOS (disclosed in the checkpoint metadata). Control points may lie
    outside the crop so strokes can enter from an edge, and a cubic can self-intersect into a loop.
    """
    h, w = g.shape
    t = np.linspace(0.0, 1.0, PENCIL_CURVE_POINTS)[:, None]
    for _ in range(int(rng.integers(1, PENCIL_MAX_STROKES + 1))):
        ox, oy = PENCIL_CTRL_OVERSHOOT * w, PENCIL_CTRL_OVERSHOOT * h
        ctrl = np.stack([rng.uniform(-ox, w + ox, 4), rng.uniform(-oy, h + oy, 4)], axis=1)
        pts = ((1 - t) ** 3 * ctrl[0] + 3 * (1 - t) ** 2 * t * ctrl[1]
               + 3 * (1 - t) * t ** 2 * ctrl[2] + t ** 3 * ctrl[3])
        thickness = int(rng.integers(PENCIL_THICKNESS_PX[0], PENCIL_THICKNESS_PX[1] + 1))
        grey = int(rng.integers(*PENCIL_GREY))
        cv2.polylines(g, [np.round(pts).astype(np.int32).reshape(-1, 1, 2)], False, grey, thickness,
                      lineType=cv2.LINE_AA)
    return g


def photometric_augment(g: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Camera-style damage on the grey crop, before binarisation (like a real photo before Stage 1)."""
    g = np.array(g, dtype=np.uint8, copy=True)
    # Pencil first: it is on the paper, so lighting, fading, blur, noise and JPEG must act on it too.
    if rng.random() < PENCIL_PROB:
        g = pencil_strokes(g, rng)
    g = g.astype(np.float32)
    h, w = g.shape
    if rng.random() < 0.5:   # uneven lighting
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        a = rng.uniform(0, 2 * np.pi)
        ramp = np.cos(a) * xx / w + np.sin(a) * yy / h
        ramp = (ramp - ramp.min()) / (np.ptp(ramp) + 1e-6)
        g = g * (1.0 - rng.uniform(0.0, 0.45) * ramp)
    if rng.random() < 0.3:   # faded ink / low contrast
        g = 255.0 - (255.0 - g) * rng.uniform(0.45, 0.9)
    if rng.random() < 0.3:   # paper tone
        g = g * rng.uniform(0.75, 1.0)
    if rng.random() < 0.4:   # focus blur
        g = cv2.GaussianBlur(g, (0, 0), rng.uniform(0.3, 1.2))
    if rng.random() < 0.3:   # low resolution
        f = rng.uniform(0.4, 0.9)
        small = cv2.resize(g, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA)
        g = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    if rng.random() < 0.5:   # sensor noise
        g = g + rng.normal(0.0, rng.uniform(2.0, 12.0), g.shape).astype(np.float32)
    g = np.clip(g, 0, 255).astype(np.uint8)
    if rng.random() < 0.4:   # JPEG
        ok, enc = cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(30, 91))])
        if ok:
            g = cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE)
    if rng.random() < 0.2:   # dust specks
        for _ in range(int(rng.integers(3, 30))):
            cv2.circle(g, (int(rng.integers(w)), int(rng.integers(h))), int(rng.integers(0, 2)),
                       int(rng.integers(0, 120)), -1)
    return g


def build_input(raw: np.ndarray, x0_store: float, rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """Stored grey crop -> binarised, resampled (INPUT_H, INPUT_W) float32 input (ink = 1)."""
    aug = rng is not None
    g = photometric_augment(raw, rng) if aug else np.asarray(raw)
    f = rng.uniform(1.0, 2.5) if aug else CANON_UPSCALE
    g2 = cv2.resize(g, (int(round(STORE_W * f)), int(round(STORE_H * f))), interpolation=cv2.INTER_CUBIC)
    fx, fy = g2.shape[1] / STORE_W, g2.shape[0] / STORE_H
    block = rng.uniform(1.8, 3.5) if aug else CANON_BLOCK_SPACES
    c = rng.uniform(6.0, 14.0) if aug else CANON_C
    b = binarize_like_stage1(g2, STORE_PPS * fy, block, c)
    if aug and rng.random() < 0.3:
        kernel = np.ones((2, 2), np.uint8)
        b = cv2.erode(b, kernel) if rng.random() < 0.5 else cv2.dilate(b, kernel)
    geo: dict[str, float] = {}
    if aug:
        geo = {"dx_spaces": rng.uniform(-GEO_DX, GEO_DX), "dy_spaces": rng.uniform(-GEO_DY, GEO_DY),
               "scale": rng.uniform(*GEO_SCALE), "angle_deg": rng.uniform(-GEO_ANGLE, GEO_ANGLE)}
    return ck.make_input(b, (x0_store + 0.5) * fx - 0.5, (STORE_TOP + 0.5) * fy - 0.5,
                         (STORE_BOTTOM + 0.5) * fy - 0.5, **geo)


def _open_npy(path: Path) -> np.ndarray:
    """Memory-maps a cached .npy; an empty array cannot be mmapped, so it is loaded normally."""
    with open(path, "rb") as f:
        version = np.lib.format.read_magic(f)
        read_header = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        shape, _, _ = read_header(f)
    if shape[0] == 0:
        return np.load(path)
    return np.load(path, mmap_mode="r")


class RawStore:
    """Indexes the DS2 and synthetic memmaps as one array (DS2 rows first), without concatenating 2 GB."""

    def __init__(self, ds2_path: Path, synth_path: Path) -> None:
        self.ds2 = _open_npy(ds2_path)
        self.synth = _open_npy(synth_path)
        self.n_ds2 = int(self.ds2.shape[0])

    def __len__(self) -> int:
        return self.n_ds2 + int(self.synth.shape[0])

    def __getitem__(self, i: int) -> np.ndarray:
        i = int(i)
        return np.array(self.ds2[i] if i < self.n_ds2 else self.synth[i - self.n_ds2])


# Per-process state for eval-input workers (set by _init_input_worker; also used inline).
_W_RAW: Optional[RawStore] = None
_W_X0S: Optional[np.ndarray] = None
_W_SEED: int = 0


def _init_input_worker(ds2_path: str, synth_path: str, x0s: np.ndarray, seed: int) -> None:
    global _W_RAW, _W_X0S, _W_SEED
    cv2.setNumThreads(1)
    _W_RAW, _W_X0S, _W_SEED = RawStore(Path(ds2_path), Path(synth_path)), x0s, seed


def _canon_one(i: int) -> np.ndarray:
    return build_input(_W_RAW[i], float(_W_X0S[i]), None).astype(np.float16)


def _stress_one(i: int) -> np.ndarray:
    rng = np.random.default_rng([_W_SEED + STRESS_SEED_OFFSET, 0, int(i)])
    return build_input(_W_RAW[i], float(_W_X0S[i]), rng).astype(np.float16)


# ==============================================================================================
# Cached data preparation
# ==============================================================================================
PREP_FUNCS: tuple[Callable[..., Any], ...] = (
    ds2_staff_records, _small_ink_near, bucket, split_for_bucket, assign_ds2_splits, _odd,
    binarize_like_stage1, store_crop, refine_staff_lines, process_ds2_image, _note_xml, _measure_xml,
    make_system, find_staves_clean, render_gray, staff_space_at_zoom1, synth_font_and_split,
    process_synth_system)
EVAL_INPUT_FUNCS: tuple[Callable[..., Any], ...] = (build_input, binarize_like_stage1, _canon_one)


@dataclass
class Data:
    """Everything the train / calibrate / eval phases need, loaded from the cache."""
    cache_dir: Path
    cache_key: str
    meta: list[dict[str, Any]]
    raw: RawStore
    clef_y: np.ndarray
    key_y: np.ndarray
    x0s: np.ndarray
    src: np.ndarray
    split: np.ndarray
    eval_sets: dict[str, np.ndarray]
    eval_inputs: dict[str, np.ndarray]
    train_idx: np.ndarray
    split_manifest_sha256: str
    synth_status: dict[str, int]
    data_rows: list[tuple[Any, ...]]
    prep_stats: dict[str, Any] = field(default_factory=dict)

    VAL_SETS: tuple[str, ...] = ("val_ds2", "val_synth")


def compute_cache_key(cfg: RunConfig, ds2_train_json: Path, ds2_test_json: Path, render: dict[str, str]
                      ) -> tuple[str, dict[str, Any]]:
    """Key of everything that decides the cached crops; a mismatch means rebuild, never reuse."""
    t0 = time.time()
    payload = {
        "core_sha256": CORE_SHA256,
        "store": [STORE_PPS, STORE_LEFT, STORE_RIGHT, STORE_ABOVE, STORE_BELOW],
        "seed": cfg.seed, "n_synth_systems": cfg.n_synth_systems, "max_ds2_images": cfg.max_ds2_images,
        "verovio": render["verovio"], "resvg_py": render["resvg_py"],
        "ds2_train_json_sha256": sha256_file(ds2_train_json),
        "ds2_test_json_sha256": sha256_file(ds2_test_json),
        "prep_code_sha256": source_hash(PREP_FUNCS),
        "prep_constants": stable_hash([sorted(CLEF_CATS.items()), sorted(WANTED), SYNTH_CLEFS, SYNTH_CLEF_WEIGHTS,
                                       SYNTH_LABELS, SYLLABLES, KEY_WEIGHTS.tolist(), SYNTH_TARGET_SP,
                                       SP_CALIBRATION_FONT, TRAIN_BUCKETS, VAL_BUCKETS, DS2_UNSEEN_FONT,
                                       SYNTH_TRAIN_FONTS, SYNTH_UNSEEN_FONT, SYNTH_UNSEEN_FONT_PERCENT,
                                       SYNTH_TRAIN_PERCENT, SYNTH_VAL_PERCENT_END, BLUR_SPACES,
                                       BG_KERNEL_SPACES, CANON_BLOCK_SPACES, CANON_C]),
    }
    logger.info("cache key computed in %.1fs (hashes both DS2 JSONs)", time.time() - t0)
    return stable_hash(payload), payload


def _prepare_ds2(cache: Path, cfg: RunConfig, ds2_dir: Path, stats_out: dict[str, Any]) -> None:
    """DS2 labels (one JSON at a time) and grey crops (8 processes, into a uint8 memmap)."""
    rec_path, raw_path = cache / "ds2_records.json", cache / "ds2_raw.npy"
    if rec_path.exists() and raw_path.exists():
        logger.info("prep-ds2: cache hit")
        return
    t0 = time.time()
    records: list[dict[str, Any]] = []
    for name, tag in (("deepscores_train.json", "official_train"), ("deepscores_test.json", "official_test")):
        t1 = time.time()
        recs, st = ds2_staff_records(ds2_dir / name, tag)
        gc.collect()  # the parsed JSON is gone; free it before the next one is parsed
        records += recs
        logger.info("prep-ds2: %s %d staves with an opening clef; %s (%.0fs)", tag, len(recs), dict(st),
                    time.time() - t1)
        stats_out[f"ds2_parse_{tag}"] = dict(st)
    records = assign_ds2_splits(records, cfg.max_ds2_images)

    jobs_by_file: dict[str, list[tuple[int, list[float]]]] = defaultdict(list)
    for i, r in enumerate(records):
        jobs_by_file[r["filename"]].append((i, r["bbox"]))
    jobs = [(str(ds2_dir / "images"), fn, recs) for fn, recs in sorted(jobs_by_file.items())]

    tmp_raw = cache / "ds2_raw.tmp.npy"
    raw = np.lib.format.open_memmap(tmp_raw, mode="w+", dtype=np.uint8, shape=(len(records), STORE_H, STORE_W))
    got = np.zeros(len(records), dtype=bool)
    missing_files: list[str] = []
    n_lines_fb = n_edge_fb = 0
    t1 = time.time()
    with ProcessPoolExecutor(max_workers=N_PROC, initializer=_init_prep_worker) as ex:
        for fn, out in ex.map(process_ds2_image, jobs, chunksize=4):
            if not out:
                missing_files.append(fn)
            for i, crop, x0s, lines_ok, edge_ok in out:
                raw[i] = crop
                records[i]["x0_store"] = x0s
                n_lines_fb += not lines_ok
                n_edge_fb += not edge_ok
                got[i] = True
    raw.flush()
    if missing_files:
        logger.warning("prep-ds2: %d DS2 image files could not be read, e.g. %s", len(missing_files),
                       missing_files[:3])
    keep_idx = np.nonzero(got)[0]
    if len(keep_idx) != len(records):  # compact: drop rows whose page could not be read
        compact = np.lib.format.open_memmap(cache / "ds2_raw.tmp2.npy", mode="w+", dtype=np.uint8,
                                            shape=(len(keep_idx), STORE_H, STORE_W))
        for j, i in enumerate(keep_idx):
            compact[j] = raw[i]
        compact.flush()
        del raw, compact
        os.remove(tmp_raw)
        os.replace(cache / "ds2_raw.tmp2.npy", tmp_raw)
    else:
        del raw
    records = [records[i] for i in keep_idx]
    os.replace(tmp_raw, raw_path)
    atomic_write_text(rec_path, json.dumps(records))
    stats_out.update({"ds2_crops": len(records), "ds2_staff_line_fallback": n_lines_fb,
                      "ds2_staff_start_fallback": n_edge_fb, "ds2_missing_files": len(missing_files),
                      "ds2_crop_seconds": round(time.time() - t1, 1), "ds2_total_seconds": round(time.time() - t0, 1)})
    logger.info("prep-ds2: %d crops in %.0fs (crop extraction %.0fs, %d processes); staff-line fallback %d, "
                "staff-start fallback %d", len(records), time.time() - t0, time.time() - t1, N_PROC,
                n_lines_fb, n_edge_fb)


def _prepare_synth(cache: Path, cfg: RunConfig, stats_out: dict[str, Any]) -> None:
    """Synthetic Verovio systems (8 processes, one toolkit each) into a uint8 memmap."""
    rec_path, raw_path, st_path = cache / "synth_records.json", cache / "synth_raw.npy", cache / "synth_status.json"
    if rec_path.exists() and raw_path.exists() and st_path.exists():
        logger.info("prep-synth: cache hit")
        return
    t0 = time.time()
    sp_zoom1 = staff_space_at_zoom1(cfg.seed)
    logger.info("prep-synth: staff space at zoom 1: %.2f px", sp_zoom1)
    fn = partial(process_synth_system, seed=cfg.seed, sp_zoom1=sp_zoom1)
    # Results are kept in memory only until the memmap is written: ~0.7 GB on the full run.
    with ProcessPoolExecutor(max_workers=N_PROC, initializer=_init_prep_worker) as ex:
        results = list(ex.map(fn, range(cfg.n_synth_systems), chunksize=8))
    status = Counter(s for _, _, s in results)
    n = sum(len(out) for _, out, _ in results if out)
    tmp_raw = cache / "synth_raw.tmp.npy"
    raw = np.lib.format.open_memmap(tmp_raw, mode="w+", dtype=np.uint8, shape=(n, STORE_H, STORE_W))
    records: list[dict[str, Any]] = []
    for _, out, _ in results:
        if out:
            for crop, meta in out:
                raw[len(records)] = crop
                records.append(meta)
    raw.flush()
    del raw, results
    os.replace(tmp_raw, raw_path)
    atomic_write_text(rec_path, json.dumps(records))
    atomic_write_text(st_path, json.dumps({"status": dict(status), "sp_zoom1": sp_zoom1}))
    stats_out.update({"synth_staves": n, "synth_status": dict(status), "synth_seconds": round(time.time() - t0, 1)})
    logger.info("prep-synth: %d staves from %d systems in %.0fs (%d processes); %s", n, cfg.n_synth_systems,
                time.time() - t0, N_PROC, dict(status))


def _build_many(fn: Callable[[int], np.ndarray], idx: np.ndarray, cache: Path, x0s: np.ndarray, seed: int
                ) -> np.ndarray:
    """Builds float16 inputs for rows idx, with 8 processes unless the job is small."""
    if len(idx) == 0:
        return np.zeros((0, ck.INPUT_H, ck.INPUT_W), np.float16)
    init_args = (str(cache / "ds2_raw.npy"), str(cache / "synth_raw.npy"), x0s, seed)
    if len(idx) < INLINE_BELOW:
        _init_input_worker(*init_args)
        return np.stack([fn(int(i)) for i in idx])
    with ProcessPoolExecutor(max_workers=N_PROC, initializer=_init_input_worker, initargs=init_args) as ex:
        return np.stack(list(ex.map(fn, [int(i) for i in idx], chunksize=64)))


def load_data(cfg: RunConfig, ds2_dir: Path, cache_root: Path, render: dict[str, str], build: bool) -> Data:
    """Loads (and, if build, creates) the cached prep outputs for this config."""
    ds2_train, ds2_test = ds2_dir / "deepscores_train.json", ds2_dir / "deepscores_test.json"
    key, payload = compute_cache_key(cfg, ds2_train, ds2_test, render)
    cache = cache_root / key[:16]
    cache.mkdir(parents=True, exist_ok=True)
    key_file = cache / "cache_key.json"
    if key_file.exists():
        stored = json.loads(key_file.read_text(encoding="utf-8"))
        if stored.get("key") != key:  # a 16-hex prefix collision or a hand-edited cache: never reuse
            raise SystemExit(f"Cache {cache} holds key {stored.get('key')}, expected {key}. Delete it and rerun.")
    else:
        atomic_write_text(key_file, json.dumps({"key": key, "payload": payload}, indent=1, sort_keys=True))
    logger.info("cache %s", cache)

    stats: dict[str, Any] = {}
    stats_path = cache / "prep_stats.json"
    if build:
        _prepare_ds2(cache, cfg, ds2_dir, stats)
        _prepare_synth(cache, cfg, stats)
        if stats:
            old = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}
            atomic_write_text(stats_path, json.dumps({**old, **stats}, indent=1))
    for p in ("ds2_records.json", "ds2_raw.npy", "synth_records.json", "synth_raw.npy", "synth_status.json"):
        if not (cache / p).exists():
            raise SystemExit(f"Cache is missing {p}; run --phase prep (or all) first.")
    if stats_path.exists():
        stats = json.loads(stats_path.read_text(encoding="utf-8"))

    ds2_records = json.loads((cache / "ds2_records.json").read_text(encoding="utf-8"))
    synth_records = json.loads((cache / "synth_records.json").read_text(encoding="utf-8"))
    synth_status = json.loads((cache / "synth_status.json").read_text(encoding="utf-8"))["status"]
    raw = RawStore(cache / "ds2_raw.npy", cache / "synth_raw.npy")
    if raw.n_ds2 != len(ds2_records) or len(raw) != len(ds2_records) + len(synth_records):
        raise SystemExit(f"Cache {cache} is inconsistent (array rows vs records); delete it and rerun.")

    # Notebook cell 23
    meta = ds2_records + synth_records
    clef_y = np.array([ck.CLEF_CLASSES.index(m["clef"]) for m in meta], dtype=np.int64)
    key_y = np.array([KEY_IGNORE if m["key"] == KEY_IGNORE else ck.key_to_index(m["key"]) for m in meta],
                     dtype=np.int64)
    x0s = np.array([m["x0_store"] for m in meta], dtype=np.float32)
    src = np.array([m["source"] for m in meta])
    split = np.array([m["split"] for m in meta])
    eval_sets = {
        "val_ds2": np.nonzero((src == "ds2") & (split == "val"))[0],
        "val_synth": np.nonzero((src == "synth") & (split == "val"))[0],
        "test_ds2_seen_fonts": np.nonzero((src == "ds2") & (split == "test"))[0],
        "test_ds2_unseen_font_gonville": np.nonzero((src == "ds2") & (split == "test_unseen_font"))[0],
        "test_synth_seen_fonts": np.nonzero((src == "synth") & (split == "test"))[0],
        "test_synth_unseen_font_gootville": np.nonzero((src == "synth") & (split == "test_unseen_font"))[0],
    }
    train_idx = np.nonzero(split == "train")[0]

    rows: list[tuple[Any, ...]] = []
    for name, idx in [("train_ds2", train_idx[src[train_idx] == "ds2"]),
                      ("train_synth", train_idx[src[train_idx] == "synth"])] + list(eval_sets.items()):
        cc = Counter(ck.CLEF_CLASSES[c] for c in clef_y[idx])
        rows.append((name, len(idx), *[cc.get(c, 0) for c in ck.CLEF_CLASSES], int((key_y[idx] != KEY_IGNORE).sum())))

    groups = sorted({("ds2", m["piece"], m["split"]) for m in ds2_records}
                    | {("synth", str(m["sys_id"]), m["split"]) for m in synth_records})
    manifest = {"seed": cfg.seed,
                "rule": "ds2: sha1('ds2:'+piece)%100 (<70 train, <85 val, else test; gonville test-only); "
                        "synth: see synth_font_and_split()",
                "groups": [{"source": s, "group": g, "split": sp} for s, g, sp in groups]}
    manifest_text = json.dumps(manifest, sort_keys=True)
    split_sha = sha256_bytes(manifest_text.encode("utf-8"))
    atomic_write_text(cache / "clef_key_splits.json", manifest_text)

    # Clean eval inputs (float16), cached under their own key: they depend on build_input's canonical path.
    ev_key = stable_hash([key, source_hash(EVAL_INPUT_FUNCS), CANON_UPSCALE, CANON_BLOCK_SPACES, CANON_C])[:16]
    ev_path = cache / f"eval_inputs_{ev_key}.npz"
    if ev_path.exists():
        with np.load(ev_path) as z:
            eval_inputs = {n: z[n] for n in eval_sets}
        logger.info("prep-eval: cache hit %s", ev_path.name)
    elif build:
        t0 = time.time()
        eval_inputs = {n: _build_many(_canon_one, idx, cache, x0s, cfg.seed) for n, idx in eval_sets.items()}
        tmp = cache / f"eval_inputs_{ev_key}.tmp.npz"
        np.savez(tmp, **eval_inputs)
        os.replace(tmp, ev_path)
        logger.info("prep-eval: clean eval inputs built in %.0fs: %s", time.time() - t0,
                    {k: len(v) for k, v in eval_inputs.items()})
    else:
        raise SystemExit(f"Cache is missing {ev_path.name}; run --phase prep (or all) first.")

    return Data(cache_dir=cache, cache_key=key, meta=meta, raw=raw, clef_y=clef_y, key_y=key_y, x0s=x0s,
                src=src, split=split, eval_sets=eval_sets, eval_inputs=eval_inputs, train_idx=train_idx,
                split_manifest_sha256=split_sha, synth_status=synth_status, data_rows=rows, prep_stats=stats)


def log_data_table(data: Data) -> None:
    logger.info("%-36s %6s %s  key_labelled", "set", "n", " ".join(f"{c:>6s}" for c in ck.CLEF_CLASSES))
    for r in data.data_rows:
        logger.info("%-36s %6d %s  %6d", r[0], r[1], " ".join(f"{v:6d}" for v in r[2:6]), r[6])
    logger.info("split manifest sha256 %s", data.split_manifest_sha256)


# ==============================================================================================
# Datasets and model helpers (notebook cells 25, 29)
# ==============================================================================================
class StaffStartDataset(Dataset):
    """Training set. The random stream of sample i in epoch e is seeded by (seed, e, i)."""

    def __init__(self, data: Data, indices: np.ndarray, seed: int) -> None:
        self.data = data
        self.indices = np.asarray(indices)
        self.seed = seed
        self.epoch = 0

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, k: int) -> tuple[torch.Tensor, int, int]:
        i = int(self.indices[k])
        rng = np.random.default_rng([self.seed, self.epoch, i])
        x = build_input(self.data.raw[i], float(self.data.x0s[i]), rng)
        return torch.from_numpy(x)[None], int(self.data.clef_y[i]), int(self.data.key_y[i])


def sampler_weights(data: Data, idx: np.ndarray) -> np.ndarray:
    """DS2 and synthetic each ~half of an epoch; within a source a class's weight grows like sqrt(size)."""
    src, clef_y = data.src, data.clef_y
    w = np.zeros(len(idx), dtype=np.float64)
    for s in np.unique(src[idx]):
        m_src = src[idx] == s
        for c in np.unique(clef_y[idx][m_src]):
            m = m_src & (clef_y[idx] == c)
            w[m] = 1.0 / math.sqrt(m.sum())
        w[m_src] *= 0.5 / w[m_src].sum()
    return w


@torch.no_grad()
def logits_for(model: nn.Module, inputs: np.ndarray, device: torch.device, batch: int = EVAL_BATCH
               ) -> tuple[torch.Tensor, torch.Tensor]:
    model.eval()
    cl, kl = [], []
    for s in range(0, len(inputs), batch):
        x = torch.from_numpy(inputs[s:s + batch].astype(np.float32))[:, None].to(device)
        a, b = model(x)
        cl.append(a.float().cpu())
        kl.append(b.float().cpu())
    if not cl:
        return torch.zeros(0, len(ck.CLEF_CLASSES)), torch.zeros(0, len(ck.KEY_CLASSES))
    return torch.cat(cl), torch.cat(kl)


def quick_scores(model: nn.Module, data: Data, name: str, device: torch.device) -> Optional[dict[str, float]]:
    idx = data.eval_sets[name]
    if len(idx) == 0:
        return None
    cl, kl = logits_for(model, data.eval_inputs[name], device)
    yc, yk = data.clef_y[idx], data.key_y[idx]
    pc = cl.argmax(1).numpy()
    recalls = [float((pc[yc == c] == c).mean()) for c in range(len(ck.CLEF_CLASSES)) if (yc == c).any()]
    mk = yk != KEY_IGNORE
    key_acc = float((kl.argmax(1).numpy()[mk] == yk[mk]).mean()) if mk.any() else float("nan")
    return {"clef_acc": float((pc == yc).mean()), "clef_macro_recall": float(np.mean(recalls)), "key_acc": key_acc}


def worker_init(worker_id: int, seed: int) -> None:
    """Kept from the notebook for a future --workers N; unused while NUM_WORKERS = 0."""
    cv2.setNumThreads(1)
    np.random.seed((seed + worker_id) % (2 ** 32))
    random.seed(seed + worker_id)


# ==============================================================================================
# Previews (notebook cells 21 and 27)
# ==============================================================================================
def write_previews(data: Data, cfg: RunConfig, run_dir: Path) -> None:
    """preview_synthetic_systems.png and preview_inputs.png, for the S4 crop-geometry check."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sp_zoom1 = json.loads((data.cache_dir / "synth_status.json").read_text(encoding="utf-8"))["sp_zoom1"]
    fig, axes = plt.subplots(1, 4, figsize=(16, 6))
    for ax, sid in zip(axes, range(4)):
        mei, labs, opts, tsp = make_system(sid, cfg.seed)
        fnt, _ = synth_font_and_split(sid, cfg.seed)
        ax.imshow(render_gray(mei, opts, fnt, tsp / sp_zoom1), cmap="gray")
        ax.set_title(f"{fnt}: " + ", ".join(lb["clef_name"] for lb in labs) + f" key {labs[0]['key']}", fontsize=8)
        ax.axis("off")
    plt.tight_layout()
    plt.savefig(run_dir / "preview_synthetic_systems.png", dpi=80)
    plt.close(fig)

    preview = StaffStartDataset(data, data.train_idx[:: max(1, len(data.train_idx) // 16)][:16], cfg.seed)
    fig, axes = plt.subplots(3, 8, figsize=(18, 7))
    for k, ax in enumerate(axes[:2].ravel()):
        if k < len(preview):
            x, c, kk = preview[k]
            ax.imshow(x[0].numpy(), cmap="gray", vmin=0, vmax=1)
            ax.set_title(f"{ck.CLEF_CLASSES[c]} key {ck.index_to_key(kk) if kk >= 0 else 'ign'}", fontsize=8)
        ax.axis("off")
    vi = data.eval_sets["val_synth"][:4].tolist() + data.eval_sets["val_ds2"][:4].tolist()
    n_synth_shown = min(4, len(data.eval_sets["val_synth"]))
    for ax, (j, i) in zip(axes[2], enumerate(vi)):
        name = "val_synth" if j < n_synth_shown else "val_ds2"
        pos = int(np.nonzero(data.eval_sets[name] == i)[0][0])
        ax.imshow(data.eval_inputs[name][pos].astype(np.float32), cmap="gray", vmin=0, vmax=1)
        ax.set_title(f"val {data.src[i]} {ck.CLEF_CLASSES[data.clef_y[i]]}", fontsize=8)
        ax.axis("off")
    plt.tight_layout()
    plt.savefig(run_dir / "preview_inputs.png", dpi=80)
    plt.close(fig)
    logger.info("previews written to %s", run_dir)


# ==============================================================================================
# Training (notebook cell 29) with atomic per-epoch checkpoints and resume
# ==============================================================================================
def run_hashes(cfg: RunConfig, data: Data) -> dict[str, str]:
    """Hashes a resumed run must match: config, code (script + core) and data (cache + split manifest)."""
    return {"config_hash": cfg.config_hash(), "script_sha256": SCRIPT_SHA256, "core_sha256": CORE_SHA256,
            "cache_key": data.cache_key, "split_manifest_sha256": data.split_manifest_sha256}


def _rng_states(device: torch.device, sampler_gen: torch.Generator, loader_gen: torch.Generator) -> dict[str, Any]:
    return {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if device.type == "cuda" else None,
            "sampler_gen": sampler_gen.get_state(), "loader_gen": loader_gen.get_state()}


def _restore_rng_states(st: dict[str, Any], device: torch.device, sampler_gen: torch.Generator,
                        loader_gen: torch.Generator) -> None:
    random.setstate(st["python"])
    np.random.set_state(st["numpy"])
    torch.set_rng_state(st["torch"])
    if device.type == "cuda":
        torch.cuda.set_rng_state_all(st["cuda"])
    sampler_gen.set_state(st["sampler_gen"])
    loader_gen.set_state(st["loader_gen"])


def load_checkpoint(path: Path) -> dict[str, Any]:
    """Loads our own checkpoint (contains RNG tuples and numpy state, hence weights_only=False)."""
    return torch.load(path, map_location="cpu", weights_only=False)


def train_phase(cfg: RunConfig, data: Data, device: torch.device, run_dir: Path, resume: bool,
                stop_after_epoch: Optional[int]) -> bool:
    """Trains (or resumes) and writes last.pt / epoch_NNN.pt after every epoch.

    Returns:
        True if training reached cfg.epochs, False if stopped early by --stop-after-epoch.
    """
    hashes = run_hashes(cfg, data)
    last_path = run_dir / "last.pt"
    seed_everything(cfg.seed)
    model = ck.ClefKeyNet().to(device)
    train_ds = StaffStartDataset(data, data.train_idx, cfg.seed)
    sampler_gen = torch.Generator().manual_seed(cfg.seed)
    sampler = WeightedRandomSampler(torch.as_tensor(sampler_weights(data, data.train_idx)),
                                    num_samples=len(data.train_idx), replacement=True, generator=sampler_gen)
    loader_gen = torch.Generator().manual_seed(cfg.seed + 1)
    steps_per_epoch = max(1, len(data.train_idx) // cfg.batch_size)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=cfg.epochs * steps_per_epoch)
    clef_loss_fn = nn.CrossEntropyLoss()
    key_loss_fn = nn.CrossEntropyLoss(ignore_index=KEY_IGNORE)

    history: list[dict[str, Any]] = []
    best: dict[str, Any] = {"score": -1.0, "epoch": None, "state": None}
    start_epoch = 1
    if resume:
        ckpt = load_checkpoint(last_path)
        mismatched = {k: (ckpt["hashes"].get(k), v) for k, v in hashes.items() if ckpt["hashes"].get(k) != v}
        if mismatched:
            logger.error("REFUSING to resume: hashes differ (checkpoint, now): %s", mismatched)
            raise SystemExit(EXIT_REFUSED)
        if ckpt["device_type"] != device.type:
            logger.error("REFUSING to resume: checkpoint was trained on %s, this run is on %s",
                         ckpt["device_type"], device.type)
            raise SystemExit(EXIT_REFUSED)
        model.load_state_dict(ckpt["model"])
        opt.load_state_dict(ckpt["optimizer"])
        sched.load_state_dict(ckpt["scheduler"])
        history, best = ckpt["history"], ckpt["best"]
        _restore_rng_states(ckpt["rng"], device, sampler_gen, loader_gen)
        start_epoch = int(ckpt["epoch"]) + 1
        logger.info("RESUMED at epoch %d (last completed %d, device %s)", start_epoch, ckpt["epoch"],
                    ckpt["device_name"])
        del ckpt
    if start_epoch > cfg.epochs:
        logger.info("training already complete (%d epochs)", cfg.epochs)
        return True
    logger.info("training %d rows, %d steps/epoch, epochs %d..%d, batch %d fp32, lr %g",
                len(data.train_idx), steps_per_epoch, start_epoch, cfg.epochs, cfg.batch_size, cfg.lr)

    device_name = torch.cuda.get_device_name(0) if device.type == "cuda" else platform.processor() or "cpu"
    for epoch in range(start_epoch, cfg.epochs + 1):
        t0 = time.time()
        train_ds.epoch = epoch
        loader = DataLoader(train_ds, batch_size=cfg.batch_size, sampler=sampler, num_workers=cfg.num_workers,
                            worker_init_fn=partial(worker_init, seed=cfg.seed), generator=loader_gen,
                            drop_last=True, persistent_workers=False, pin_memory=device.type == "cuda")
        model.train()
        tot, nb = 0.0, 0
        for x, yc, yk in loader:
            x, yc, yk = x.to(device), yc.to(device), yk.to(device)
            cl, kl = model(x)
            loss = clef_loss_fn(cl, yc)
            if (yk != KEY_IGNORE).any():
                loss = loss + key_loss_fn(kl, yk)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            tot += float(loss)
            nb += 1
        val = {n: quick_scores(model, data, n, device) for n in Data.VAL_SETS}
        parts = [0.5 * (v["clef_macro_recall"] + (v["key_acc"] if not math.isnan(v["key_acc"]) else 0.0))
                 for v in val.values() if v is not None]
        score = float(np.mean(parts)) if parts else 0.0
        history.append({"epoch": epoch, "train_loss": tot / max(1, nb), "val": val, "val_score": score})
        if score > best["score"]:
            best = {"score": score, "epoch": epoch,
                    "state": copy.deepcopy({k: v.cpu() for k, v in model.state_dict().items()})}
        state = {"epoch": epoch, "epochs": cfg.epochs, "model": model.state_dict(), "optimizer": opt.state_dict(),
                 "scheduler": sched.state_dict(), "history": history, "best": best,
                 "rng": _rng_states(device, sampler_gen, loader_gen), "hashes": hashes,
                 "config": cfg.hash_payload(), "device_type": device.type, "device_name": device_name}
        atomic_torch_save(state, run_dir / f"epoch_{epoch:03d}.pt")
        atomic_torch_save(state, last_path)
        atomic_write_text(run_dir / "clef_key_history.json", json.dumps(history, indent=1))
        logger.info("epoch %2d loss %.4f val_score %.4f %s (%.0fs)", epoch, tot / max(1, nb), score,
                    " | ".join(f"{n}: clef {v['clef_macro_recall']:.3f} key {v['key_acc']:.3f}"
                               for n, v in val.items() if v), time.time() - t0)
        if stop_after_epoch is not None and epoch >= stop_after_epoch and epoch < cfg.epochs:
            logger.info("stopping after epoch %d as requested (--stop-after-epoch); resume with --resume", epoch)
            return False
    logger.info("best epoch %s val score %.4f", best["epoch"], best["score"])
    return True


def load_best_model(cfg: RunConfig, data: Data, device: torch.device, run_dir: Path) -> tuple[nn.Module, dict[str, Any]]:
    """Loads the best-epoch weights from a finished run's last.pt, after checking every hash."""
    last_path = run_dir / "last.pt"
    if not last_path.exists():
        raise SystemExit(f"{last_path} not found: run --phase train first.")
    ckpt = load_checkpoint(last_path)
    hashes = run_hashes(cfg, data)
    mismatched = {k: (ckpt["hashes"].get(k), v) for k, v in hashes.items() if ckpt["hashes"].get(k) != v}
    if mismatched:
        logger.error("REFUSING: this run dir was trained with different hashes (checkpoint, now): %s", mismatched)
        raise SystemExit(EXIT_REFUSED)
    if int(ckpt["epoch"]) < cfg.epochs:
        logger.error("REFUSING: training stopped at epoch %d of %d; --resume it first.", ckpt["epoch"], cfg.epochs)
        raise SystemExit(EXIT_REFUSED)
    model = ck.ClefKeyNet().to(device)
    model.load_state_dict(ckpt["best"]["state"])
    model.eval()
    info = {"best_epoch": ckpt["best"]["epoch"], "best_score": ckpt["best"]["score"], "history": ckpt["history"],
            "device_type": ckpt["device_type"]}
    return model, info


# ==============================================================================================
# Calibration (notebook cell 31): val only
# ==============================================================================================
THRESH_GRID = np.concatenate([np.arange(0.30, 0.995, 0.005), [0.995, 0.998, 0.999]])


def fit_temperature(logits: torch.Tensor, y: torch.Tensor) -> float:
    if len(y) == 0:
        return 1.0
    log_t = torch.zeros(1, requires_grad=True)
    opt_t = torch.optim.LBFGS([log_t], lr=0.1, max_iter=200)

    def closure() -> torch.Tensor:
        opt_t.zero_grad()
        loss = F.cross_entropy(logits / log_t.exp(), y)
        loss.backward()
        return loss

    opt_t.step(closure)
    return float(log_t.exp().clamp(0.05, 20.0))


def lowest_threshold(conf: np.ndarray, correct: np.ndarray, target: float) -> Optional[float]:
    for t in THRESH_GRID:
        m = conf >= t
        if m.sum() >= MIN_SELECTED_FOR_THRESHOLD and correct[m].mean() >= target:
            return float(t)
    return None


def calibrate_phase(cfg: RunConfig, data: Data, device: torch.device, run_dir: Path) -> dict[str, Any]:
    """Temperatures, "unsure" thresholds and the G8vb gate, fitted on DS2/synthetic val only."""
    model, info = load_best_model(cfg, data, device, run_dir)
    val_logits = {n: logits_for(model, data.eval_inputs[n], device) for n in Data.VAL_SETS}
    all_cl = torch.cat([val_logits[n][0] for n in Data.VAL_SETS])
    all_kl = torch.cat([val_logits[n][1] for n in Data.VAL_SETS])
    all_yc = torch.as_tensor(np.concatenate([data.clef_y[data.eval_sets[n]] for n in Data.VAL_SETS]))
    all_yk = torch.as_tensor(np.concatenate([data.key_y[data.eval_sets[n]] for n in Data.VAL_SETS]))
    mk = all_yk != KEY_IGNORE
    clef_t = fit_temperature(all_cl, all_yc)
    key_t = fit_temperature(all_kl[mk], all_yk[mk])
    logger.info("temperatures: clef %.3f key %.3f", clef_t, key_t)

    threshold_evidence: dict[str, Any] = {}
    clef_ts, key_ts = [], []
    other = ck.CLEF_CLASSES.index("other")
    for n in Data.VAL_SETS:
        idx = data.eval_sets[n]
        if len(idx) == 0:
            continue
        pc = torch.softmax(val_logits[n][0] / clef_t, 1).numpy()
        pk = torch.softmax(val_logits[n][1] / key_t, 1).numpy()
        yc, yk = data.clef_y[idx], data.key_y[idx]
        # A confident "other" is still unsure for PiyaNota, so only in-scope predictions count as "sure".
        in_scope = pc.argmax(1) != other
        tc = lowest_threshold(np.where(in_scope, pc.max(1), 0.0), pc.argmax(1) == yc, CLEF_SELECTIVE_TARGET)
        m = yk != KEY_IGNORE
        tk_ = lowest_threshold(pk.max(1)[m], pk.argmax(1)[m] == yk[m], KEY_SELECTIVE_TARGET) if m.any() else None
        threshold_evidence[n] = {"clef_threshold": tc, "key_threshold": tk_, "n": int(len(idx)), "n_key": int(m.sum())}
        clef_ts.append(UNSURE_THRESHOLD if tc is None else tc)
        key_ts.append(UNSURE_THRESHOLD if tk_ is None else tk_)
    clef_threshold = float(max(clef_ts)) if clef_ts else UNSURE_THRESHOLD
    key_threshold = float(max(key_ts)) if key_ts else UNSURE_THRESHOLD
    for name, t in (("clef", clef_threshold), ("key", key_threshold)):
        if t > 1.0:
            logger.warning("the %s target was not reached on some validation source: every %s answer will be "
                           "marked unsure. Report this; do not lower the target to make it pass.", name, name)
    logger.info("thresholds: clef %s key %s %s", clef_threshold, key_threshold, threshold_evidence)

    g_i, g8_i = ck.CLEF_CLASSES.index("G"), ck.CLEF_CLASSES.index("G8vb")
    g8vb_evidence: dict[str, Any] = {}
    for n in Data.VAL_SETS:
        idx = data.eval_sets[n]
        yc = data.clef_y[idx]
        pred = val_logits[n][0].argmax(1).numpy() if len(idx) else np.zeros(0, int)
        n8, ng = int((yc == g8_i).sum()), int((yc == g_i).sum())
        g8vb_evidence[n] = {"n_g8vb": n8, "n_g": ng,
                            "g8vb_recall": float((pred[yc == g8_i] == g8_i).mean()) if n8 else None,
                            "g_called_g8vb": float((pred[yc == g_i] == g8_i).mean()) if ng else None}
    qualifying = [e for e in g8vb_evidence.values() if e["n_g8vb"] >= G8VB_MIN_SUPPORT and e["n_g"] > 0]
    g8vb_reliable = bool(qualifying) and all(e["g8vb_recall"] >= G8VB_MIN_RECALL
                                             and e["g_called_g8vb"] <= G8VB_MAX_G_CONFUSION for e in qualifying)
    logger.info("g8vb_reliable = %s %s", g8vb_reliable, g8vb_evidence)
    calib = {"clef_temperature": clef_t, "key_temperature": key_t, "clef_threshold": clef_threshold,
             "key_threshold": key_threshold, "threshold_evidence_val": threshold_evidence,
             "g8vb_reliable": g8vb_reliable, "g8vb_evidence_val": g8vb_evidence,
             "fitted_on": list(Data.VAL_SETS), "best_epoch": info["best_epoch"],
             "hashes": run_hashes(cfg, data)}
    atomic_write_text(run_dir / "calibration.json", json.dumps(calib, indent=1, default=json_default))
    return calib


# ==============================================================================================
# Evaluation and export (notebook cells 33 and 35)
# ==============================================================================================
def wilson(k: int, n: int, z: float = 1.96) -> tuple[Optional[float], Optional[float]]:
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def auroc(score: np.ndarray, positive: np.ndarray) -> Optional[float]:
    pos, neg = score[positive], score[~positive]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    allv = np.concatenate([pos, neg])
    for v in np.unique(allv):  # average ranks for ties
        m = allv == v
        ranks[m] = ranks[m].mean()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def ece(conf: np.ndarray, correct: np.ndarray, bins: int = 15) -> Optional[float]:
    if len(conf) == 0:
        return None
    e, edges = 0.0, np.linspace(0, 1, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            e += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(e)


def evaluate(model: nn.Module, data: Data, calib: dict[str, Any], idx: np.ndarray, inputs: np.ndarray,
             device: torch.device) -> dict[str, Any]:
    if len(idx) == 0:
        return {"n": 0}
    cl, kl = logits_for(model, inputs, device)
    pc = torch.softmax(cl / calib["clef_temperature"], 1).numpy()
    pk = torch.softmax(kl / calib["key_temperature"], 1).numpy()
    yc, yk = data.clef_y[idx], data.key_y[idx]
    pred_c, conf_c = pc.argmax(1), pc.max(1)
    ok_c = pred_c == yc
    other = ck.CLEF_CLASSES.index("other")
    g_i, g8_i = ck.CLEF_CLASSES.index("G"), ck.CLEF_CLASSES.index("G8vb")
    sure_c = (conf_c >= calib["clef_threshold"]) & (pred_c != other)

    def fam(a: np.ndarray) -> np.ndarray:
        return np.where(a == g8_i, g_i, a)

    k_c = int(ok_c.sum())
    res: dict[str, Any] = {
        "n": int(len(idx)),
        "clef_acc": k_c / len(idx), "clef_acc_ci95": wilson(k_c, len(idx)),
        "clef_acc_treble_family": float((fam(pred_c) == fam(yc)).mean()),
        "clef_macro_recall": float(np.mean([(pred_c[yc == c] == c).mean()
                                            for c in range(len(ck.CLEF_CLASSES)) if (yc == c).any()])),
        "clef_confusion_rows_true_cols_pred": [[int(((yc == a) & (pred_c == b)).sum())
                                                for b in range(len(ck.CLEF_CLASSES))]
                                               for a in range(len(ck.CLEF_CLASSES))],
        "clef_coverage_sure": float(sure_c.mean()),
        "clef_acc_when_sure": float(ok_c[sure_c].mean()) if sure_c.any() else None,
        "clef_confident_wrong_rate": float((sure_c & ~ok_c).mean()),
        "clef_auroc": auroc(conf_c, ok_c), "clef_ece": ece(conf_c, ok_c)}
    m = yk != KEY_IGNORE
    if m.any():
        pred_k, conf_k = pk.argmax(1)[m], pk.max(1)[m]
        ok_k = pred_k == yk[m]
        sure_k = conf_k >= calib["key_threshold"]
        res.update({"n_key": int(m.sum()), "key_acc": float(ok_k.mean()),
                    "key_acc_ci95": wilson(int(ok_k.sum()), int(m.sum())),
                    "key_off_by_one": float((np.abs(pred_k - yk[m]) == 1).mean()),
                    "key_coverage_sure": float(sure_k.mean()),
                    "key_acc_when_sure": float(ok_k[sure_k].mean()) if sure_k.any() else None,
                    "key_confident_wrong_rate": float((sure_k & ~ok_k).mean()),
                    "key_auroc": auroc(conf_k, ok_k), "key_ece": ece(conf_k, ok_k)})
    return res


def _fmt(v: Any) -> str:
    return "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def eval_phase(cfg: RunConfig, data: Data, device: torch.device, run_dir: Path, versions: dict[str, Any],
               render: dict[str, str]) -> None:
    """Test + stress metrics (looked at once), parity fixture, and the exported classifier."""
    model, info = load_best_model(cfg, data, device, run_dir)
    calib_path = run_dir / "calibration.json"
    if not calib_path.exists():
        raise SystemExit(f"{calib_path} not found: run --phase calibrate first.")
    calib = json.loads(calib_path.read_text(encoding="utf-8"))
    if calib["hashes"] != run_hashes(cfg, data):
        logger.error("REFUSING: calibration.json was fitted with different hashes.")
        raise SystemExit(EXIT_REFUSED)

    test_sets = [n for n in data.eval_sets if n.startswith("test")]
    metrics: dict[str, dict[str, Any]] = {
        "val": {n: evaluate(model, data, calib, data.eval_sets[n], data.eval_inputs[n], device) for n in Data.VAL_SETS},
        "test": {}, "stress": {}}
    for n in test_sets:
        idx = data.eval_sets[n]
        metrics["test"][n] = evaluate(model, data, calib, idx, data.eval_inputs[n], device)
        stress_inputs = _build_many(_stress_one, idx, data.cache_dir, data.x0s, cfg.seed)
        metrics["stress"][n] = evaluate(model, data, calib, idx, stress_inputs, device)
    logger.info("%-44s %5s %6s %6s %6s %6s %7s %6s %6s %7s %6s", "set", "n", "clef", "ci_lo", "bal", "cov",
                "cWrong", "cAUC", "key", "kWrong", "kAUC")
    for group in ("val", "test", "stress"):
        for n, r in metrics[group].items():
            if r["n"] == 0:
                logger.info("%-44s (empty)", group + ":" + n)
                continue
            logger.info("%-44s %5d %6s %6s %6s %6s %7s %6s %6s %7s %6s", group + ":" + n, r["n"],
                        _fmt(r["clef_acc"]), _fmt(r["clef_acc_ci95"][0]), _fmt(r["clef_macro_recall"]),
                        _fmt(r["clef_coverage_sure"]), _fmt(r["clef_confident_wrong_rate"]),
                        _fmt(r["clef_auroc"]), _fmt(r.get("key_acc")), _fmt(r.get("key_confident_wrong_rate")),
                        _fmt(r.get("key_auroc")))
    for n, r in metrics["test"].items():
        if r["n"]:
            logger.info("%s clef confusion (rows = true %s): %s", n, ck.CLEF_CLASSES,
                        r["clef_confusion_rows_true_cols_pred"])

    # Parity fixture (cell 35)
    fixture_idx = (data.eval_sets["test_ds2_seen_fonts"][:FIXTURE_PER_SET].tolist()
                   + data.eval_sets["test_synth_seen_fonts"][:FIXTURE_PER_SET].tolist())
    fx_bin, fx_geom, fx_inputs_l = [], [], []
    for i in fixture_idx:
        g2 = cv2.resize(data.raw[i], (int(round(STORE_W * CANON_UPSCALE)), int(round(STORE_H * CANON_UPSCALE))),
                        interpolation=cv2.INTER_CUBIC)
        fx, fy = g2.shape[1] / STORE_W, g2.shape[0] / STORE_H
        b = binarize_like_stage1(g2, STORE_PPS * fy, CANON_BLOCK_SPACES, CANON_C)
        geom = ((float(data.x0s[i]) + 0.5) * fx - 0.5, (STORE_TOP + 0.5) * fy - 0.5, (STORE_BOTTOM + 0.5) * fy - 0.5)
        fx_bin.append(b)
        fx_geom.append(geom)
        fx_inputs_l.append(ck.make_input(b, *geom))
    fx_inputs = np.stack(fx_inputs_l) if fx_inputs_l else np.zeros((0, ck.INPUT_H, ck.INPUT_W), np.float32)
    fx_cl, fx_kl = logits_for(model, fx_inputs, device)
    np.savez_compressed(run_dir / "clef_key_parity_fixture.npz",
                        binary=np.stack(fx_bin) if fx_bin else np.zeros((0, 1, 1), np.uint8),
                        geometry=np.array(fx_geom, dtype=np.float64).reshape(-1, 3), inputs=fx_inputs,
                        clef_logits=fx_cl.numpy(), key_logits=fx_kl.numpy(),
                        clef_labels=data.clef_y[fixture_idx], key_labels=data.key_y[fixture_idx])

    data_summary = {r[0]: {"n": r[1], **{c: v for c, v in zip(ck.CLEF_CLASSES, r[2:6])}, "key_labelled": r[6]}
                    for r in data.data_rows}
    # Keys and values exactly as notebook cell 35 builds them ...
    checkpoint: dict[str, Any] = {
        "model_state": {k: v.cpu() for k, v in model.state_dict().items()},
        "arch": {"name": "ClefKeyNet", "width": 32, "dropout": 0.3},
        "crop_spec_version": ck.CROP_SPEC_VERSION,
        "crop_spec": {"px_per_space": ck.PX_PER_SPACE, "left": ck.CROP_LEFT_SPACES, "right": ck.CROP_RIGHT_SPACES,
                      "above": ck.CROP_ABOVE_SPACES, "below": ck.CROP_BELOW_SPACES,
                      "input_h": ck.INPUT_H, "input_w": ck.INPUT_W},
        "core_sha256": CORE_SHA256,
        "input_contract": ("Binary page (uint8, ink=0, paper=255) = Stage 1 native adaptive-threshold strip source "
                           "BEFORE non_staff_ink_mask (PreprocessedPage.strip_unmasked). x0 = staff_left_edge(); "
                           "top/bottom = centre rows of the outer staff lines in the same pixel grid."),
        "clef_classes": list(ck.CLEF_CLASSES), "key_classes": list(ck.KEY_CLASSES),
        "clef_temperature": calib["clef_temperature"], "key_temperature": calib["key_temperature"],
        "clef_threshold": calib["clef_threshold"], "key_threshold": calib["key_threshold"],
        "clef_selective_target": CLEF_SELECTIVE_TARGET, "key_selective_target": KEY_SELECTIVE_TARGET,
        "threshold_evidence_val": calib["threshold_evidence_val"],
        "g8vb_reliable": calib["g8vb_reliable"], "g8vb_evidence_val": calib["g8vb_evidence_val"],
        "g8vb_rule": {"min_recall": G8VB_MIN_RECALL, "max_g_confusion": G8VB_MAX_G_CONFUSION,
                      "min_support": G8VB_MIN_SUPPORT},
        "seed": cfg.seed, "best_epoch": info["best_epoch"], "epochs": cfg.epochs, "best_val_score": info["best_score"],
        "selection": "best val_score (mean over val_ds2/val_synth of (clef balanced recall + key acc)/2); "
                     "temperatures and thresholds fitted on val only",
        "split_manifest_sha256": data.split_manifest_sha256,
        "metrics": metrics, "data_summary": data_summary, "versions": versions,
        "synthetic": {"n_systems": cfg.n_synth_systems, "train_fonts": list(SYNTH_TRAIN_FONTS),
                      "unseen_font": SYNTH_UNSEEN_FONT, "status": dict(data.synth_status)},
        "ds2_unseen_font": DS2_UNSEEN_FONT,
        "never_used": "piyanota_dataset (incl. Flashlight), DSMN, Both Sides Now: not used for training, "
                      "selection, calibration or thresholds",
        "smoke_test": cfg.smoke,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # ... plus the amendment's required disclosures (D.1: local run is the reference; A.6: pencil strokes).
    checkpoint["augmentation"] = {"pencil_stroke": {
        "prob": PENCIL_PROB, "max_strokes": PENCIL_MAX_STROKES, "thickness_px_at_store": list(PENCIL_THICKNESS_PX),
        "grey": list(PENCIL_GREY), "disclosure": PENCIL_DISCLOSURE}}
    checkpoint["training_run"] = {
        "trainer": "training/train_clef_key.py", "script_sha256": SCRIPT_SHA256, "config_hash": cfg.config_hash(),
        "cache_key": data.cache_key, "device_type": info["device_type"],
        "reference_note": ("The local GTX 1650 run is the reference configuration; a later Kaggle T4 run is a "
                           "different configuration, not a replication.") if info["device_type"] == "cuda"
                          else "CPU run (not the reference configuration).",
        "real_photo_set": "not read: the real-capture validation set is check-only (amendment A.4)",
        "render_versions": render}
    ckpt_path = run_dir / "clef_key_classifier.pt"
    atomic_torch_save(checkpoint, ckpt_path)
    meta_out = {k: v for k, v in checkpoint.items() if k != "model_state"}
    atomic_write_text(run_dir / "clef_key_metrics.json", json.dumps(meta_out, indent=1, default=json_default))
    atomic_write_text(run_dir / "clef_key_history.json", json.dumps(info["history"], indent=1))

    # Reload check: a fresh model from the saved file must give the same logits.
    reloaded = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    fresh = ck.ClefKeyNet(width=reloaded["arch"]["width"], dropout=reloaded["arch"]["dropout"])
    fresh.load_state_dict(reloaded["model_state"])
    fresh.to(device).eval()
    with torch.no_grad():
        rc, rk = fresh(torch.from_numpy(fx_inputs.astype(np.float32))[:, None].to(device))
    if not (torch.allclose(rc.cpu(), fx_cl, atol=RELOAD_ATOL) and torch.allclose(rk.cpu(), fx_kl, atol=RELOAD_ATOL)):
        raise RuntimeError("reload mismatch: the saved classifier does not reproduce the fixture logits")
    logger.info("saved and reload-checked: %s smoke_test=%s", ckpt_path, cfg.smoke)
    for p in sorted(run_dir.iterdir()):
        if p.is_file() and (p.name.startswith("clef_key") or p.name.startswith("preview_")):
            logger.info("%-36s %8.2f MB  sha256 %s", p.name, p.stat().st_size / 1e6, sha256_file(p)[:16])


# ==============================================================================================
# Entry point
# ==============================================================================================
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ds2", type=Path, default=DEFAULT_DS2, help="DS2 dense folder (images/, both JSONs)")
    p.add_argument("--out", type=Path, default=None,
                   help=r"run dir (default training\clef_key_artifacts\<run_id>)")
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="cache root (subfolder per settings hash)")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--smoke", action="store_true", help="tiny run; weights are useless")
    p.add_argument("--device", choices=("cpu", "cuda"), default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--resume", nargs="?", const=True, default=None, metavar="RUN_DIR",
                   help="resume training from RUN_DIR/last.pt (or from --out when no value is given)")
    p.add_argument("--phase", choices=("prep", "train", "calibrate", "eval", "all"), default="all")
    p.add_argument("--stop-after-epoch", type=int, default=None,
                   help="testing aid (resume acceptance test S3): stop after this epoch")
    return p.parse_args(argv)


def setup_logging(run_dir: Path) -> None:
    """Console + run_dir/train.log. FileHandler flushes every record, so each epoch line hits disk."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(run_dir / "train.log", encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)
    logging.captureWarnings(True)  # use_deterministic_algorithms(warn_only=True) warnings land in train.log
    warnings.simplefilter("default")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    cfg = RunConfig.build(args.seed, args.smoke)

    resume = args.resume is not None
    if isinstance(args.resume, str):
        run_dir = Path(args.resume)
    elif args.out is not None:
        run_dir = args.out
    elif resume or args.phase in ("calibrate", "eval"):
        raise SystemExit("--resume / --phase calibrate|eval need an existing run dir (--resume RUN_DIR or --out)")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = DEFAULT_ARTIFACTS / f"{'smoke' if cfg.smoke else 'full'}_seed{cfg.seed}_{stamp}"
    guard_paths(args.ds2, run_dir, args.cache)
    for req in ("images", "deepscores_train.json", "deepscores_test.json"):
        if not (args.ds2 / req).exists():
            raise SystemExit(f"{args.ds2 / req} not found (--ds2 must hold images/ and both DS2 JSONs)")
    trains = args.phase in ("train", "all")
    if trains and not resume and (run_dir / "last.pt").exists():
        raise SystemExit(f"{run_dir} already has last.pt; use --resume or a new --out")
    if resume and not (run_dir / "last.pt").exists():
        raise SystemExit(f"--resume: {run_dir / 'last.pt'} not found")
    run_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(run_dir)
    logger.info("=== train_clef_key.py phase=%s smoke=%s seed=%d device=%s run_dir=%s resume=%s argv=%s",
                args.phase, cfg.smoke, cfg.seed, args.device, run_dir, resume, sys.argv[1:])
    logger.info("core sha256 %s | script sha256 %s | config hash %s", CORE_SHA256, SCRIPT_SHA256, cfg.config_hash())

    render = check_render_versions()
    device, dev_info = setup_device(args.device)
    versions = build_versions(device, render)
    t_all = time.time()
    try:
        t0 = time.time()
        data = load_data(cfg, args.ds2, args.cache, render, build=args.phase in ("prep", "all") or trains)
        log_data_table(data)
        timings = {"load_or_prep_s": round(time.time() - t0, 1)}
        logger.info("PHASE prep/load done in %.1fs", time.time() - t0)
        cfg_path = run_dir / "config.json"
        config_doc = {"args": {k: str(v) for k, v in vars(args).items()}, "config": cfg.hash_payload(),
                      "config_hash": cfg.config_hash(), "hashes": run_hashes(cfg, data), "versions": versions,
                      "device": dev_info, "prep_stats": data.prep_stats}
        if not cfg_path.exists():
            atomic_write_text(cfg_path, json.dumps(config_doc, indent=1, default=str))
        else:  # keep the original; record later invocations next to it
            atomic_write_text(run_dir / f"config_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json",
                              json.dumps(config_doc, indent=1, default=str))
        if args.phase in ("prep", "all") and not resume:
            atomic_write_text(run_dir / "clef_key_splits.json",
                              (data.cache_dir / "clef_key_splits.json").read_text(encoding="utf-8"))
            write_previews(data, cfg, run_dir)
        if trains:
            t0 = time.time()
            done = train_phase(cfg, data, device, run_dir, resume, args.stop_after_epoch)
            timings["train_s"] = round(time.time() - t0, 1)
            logger.info("PHASE train done in %.1fs", time.time() - t0)
            if not done:
                return 0
        if args.phase in ("calibrate", "all"):
            t0 = time.time()
            calibrate_phase(cfg, data, device, run_dir)
            logger.info("PHASE calibrate done in %.1fs", time.time() - t0)
        if args.phase in ("eval", "all"):
            t0 = time.time()
            eval_phase(cfg, data, device, run_dir, versions, render)
            logger.info("PHASE eval done in %.1fs", time.time() - t0)
    except torch.OutOfMemoryError as e:
        logger.error("CUDA out of memory at batch %d (train) / %d (eval): %s. NOT shrinking the batch "
                     "automatically: a batch change changes results and must be a recorded config change.",
                     cfg.batch_size, cfg.eval_batch, e)
        return EXIT_OOM
    logger.info("finished in %.1fs%s", time.time() - t_all, " (SMOKE TEST: weights are NOT usable)" if cfg.smoke else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
