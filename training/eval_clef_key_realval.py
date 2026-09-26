"""One-time real-photo check of a FROZEN clef/key classifier (plan amendment A.4/A.5, D.1).

SKELETON, NOT YET RUN. Run it once, after ``train_clef_key.py`` has produced a reviewed, frozen
``clef_key_classifier.pt``; it refuses to overwrite an existing ``realval_metrics.json``.

What it does, and why each rule exists:

* **Check-only.** Nothing here fits anything. Temperatures, thresholds and ``g8vb_reliable`` are read
  from the checkpoint and never written back (A.4). The checkpoint file is opened read-only.
* **Deployment-path inputs (A.5.5).** Every crop comes from Stage 1 (``keep_unmasked=True``) + Stage 2
  boxes + ``staff_left_edge()`` + ``make_input()``. Nothing is hand-cropped. A labelled staff that
  Stage 2 never produced is a ``pipeline_miss``; a produced staff without usable geometry is
  ``no_staff_geometry``. Both stay in the coverage denominators; neither is ever silently dropped.
* **Matching by position, never by voice name.** Stage 2 assigns S/A/T/B by position in groups of 4.
  That is wrong on Dormi's 5-staff systems (solo obligato above SATB) and on every Flashlight system
  (Solo/S/A/T(G8vb), no Bass). Stage-2 boxes are therefore matched to label bboxes by vertical overlap
  in the same pixel frame, and clef/key are scored against the label whatever voice Stage 2 printed.
  The voice-vs-clef rule (plan 3.3 rule 6) is reported separately as ``clef_voice_mismatch``.
* **Start-of-staff only.** Only the ``clef`` and ``key_signature`` fields (the staff start) are
  scored; ``mid_staff_changes`` are ignored. The classifier only ever sees the staff start.
* **Labels marked "unsure" are excluded** from scoring (listed in the output).
* **Duplicates.** ``livin_on_a_prayer_pg10`` and ``_pg10_b`` are two photos of one printed page. The
  gate statistics (n, Wilson, bootstrap) use unique staves only (the first photo of each group); the
  duplicate photo is scored separately as a consistency check. Bootstrap clusters are physical pages.
* **Only the validation pieces are opened.** The image folder also holds TEST pieces (DSMN, Honneur,
  ...). Any page not in ``VALIDATION_PIECES`` is refused before it is read.

Known limitations (skeleton; see the open problems in the hand-off report):

1. Label bboxes are in the EXIF-upright photo frame; Stage 2 boxes are in the Stage 1 page frame
   (perspective-corrected, dewarped, maybe grid-rotated). Stage 1 does not expose its geometry, so
   ``label_rows_in_native()`` re-derives only the downscale and the perspective matrix (by calling
   Stage 1's own ``_correct_perspective`` on the identically downscaled photo). Dewarp row shifts and
   the grid rotation are NOT inverted; matching tolerates them via overlap, and the per-page residual
   between mapped labels and tracked staves is reported so a bad map is visible, not silent.
2. ``strip_staves`` are not rotated when Stage 1 applies the grid rotation to a non-dewarped page
   (Stage 1 rotates the page but not the band list), so band rows can be off by up to
   ``x * sin(angle)``. Such staves typically end up ``no_staff_geometry`` or misread; the page's
   Stage 1 angle is recorded per staff so this can be audited.
3. ``strip_unmasked`` only exists when the non-staff mask was applied; otherwise every staff on that
   page is ``no_staff_geometry`` (reason ``no_unmasked_page``).
4. Stage 2 raises ``ValueError`` on staff counts not divisible by 4 (e.g. Dormi pages with a 5-staff
   system); every labelled staff on such a page is ``pipeline_miss`` (reason
   ``unsupported_staff_layout``). That is a Stage 2 coverage fact, not a classifier error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import cv2
import numpy as np
import torch
from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import clef_key_core as ck  # noqa: E402
import stage1_preprocessing as s1  # noqa: E402
from stage2_detection import detect_staff_regions  # noqa: E402

logger = logging.getLogger("eval_clef_key_realval")

# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------
LABEL_DIR = REPO_ROOT / "data" / "val_clefkey"
LABEL_FILES: tuple[tuple[str, str], ...] = (("labels.json", "labels.sha256"),
                                            ("labels_flashlight.json", "labels_flashlight.sha256"))
DEFAULT_YOLO = REPO_ROOT / "staff_detector_files" / "weights" / "best.pt"
CORE_PATH = REPO_ROOT / "clef_key_core.py"
OUTPUT_NAME = "realval_metrics.json"
INPUTS_NAME = "realval_inputs.npz"

# page-file prefix -> piece name. Anything else in the image folder is a TEST piece and is refused.
VALIDATION_PIECES: dict[str, str] = {"dormi_jesu": "Dormi", "livin_on_a_prayer": "Livin",
                                     "flashlight": "Flashlight"}
PAGE_RE = re.compile(r"^(?P<prefix>.+)_pg(?P<page>\d+)(?P<suffix>_[a-z])?\.jpg$")
# Photos of the same printed page: first entry is canonical (counted), the rest are consistency checks.
DUPLICATE_PAGE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("livin_on_a_prayer_pg10.jpg", "livin_on_a_prayer_pg10_b.jpg"),)

# The label coordinate frame (schema "coordinate_frame"): EXIF-upright 3024 wide x 4032 tall.
UPRIGHT_SIZE_WH = (3024, 4032)

# ---------------------------------------------------------------------------------------------
# Matching / geometry
# ---------------------------------------------------------------------------------------------
MIN_MATCH_IOU = 0.3          # vertical IoU; staves are ~8+ spacings apart, dewarp shifts are < 1 staff
BAND_MAX_OFFSET_SPACINGS = 1.0  # plan 3.1: nearest tracked band within 1 spacing of the box centre
STAFF_HALF_HEIGHT_SPACINGS = 2.0  # outer lines = centre -/+ 2 spacings
RESIDUAL_WARN_SPACINGS = 1.0

# ---------------------------------------------------------------------------------------------
# Gate (plan section 4 + amendment A.2/A.5; fixed before any result)
# ---------------------------------------------------------------------------------------------
GATE_MIN_ACC = 0.99
GATE_MIN_WILSON_LB = 0.97
GATE_MAX_CONFIDENT_WRONG = 0.01
GATE_MIN_AUROC = 0.90
AUROC_MIN_WRONG = 10
GATE_MIN_SURE_N = 125
G8VB_MIN_REAL_SUPPORT = 30
WILSON_Z = 1.959963984540054
BOOTSTRAP_REPS = 10000
BOOTSTRAP_SEED = 20260926
BOOTSTRAP_ALPHA = 0.05

# Plan 3.3 rule 6: clefs allowed per (pipeline) voice. "treble" = G/G8vb collapsed (g8vb_reliable False).
ALLOWED_CLEFS: dict[str, frozenset[str]] = {
    "Soprano": frozenset({"G", "treble"}), "Alto": frozenset({"G", "treble"}),
    "Tenor": frozenset({"G", "G8vb", "F", "treble"}), "Bass": frozenset({"F"})}
LABEL_CLEF_MAP: dict[str, str] = {"G": "G", "G8vb": "G8vb", "F": "F", "OTHER": "other"}

INFER_BATCH = 64


# =============================================================================================
# Small helpers
# =============================================================================================
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text_file(path: Path) -> str:
    """LF-normalised sha256, identical to train_clef_key.py (autocrlf would otherwise change it)."""
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serialisable: {type(o)}")


def page_info(page_file: str) -> tuple[str, str]:
    """(piece name, cluster id). Refuses any page outside the validation pieces."""
    m = PAGE_RE.match(page_file)
    if m is None or m.group("prefix") not in VALIDATION_PIECES:
        raise ValueError(f"{page_file!r} is not a validation page; refusing to read it (test pieces "
                         "must never be opened by this script)")
    cluster = page_file
    for group in DUPLICATE_PAGE_GROUPS:
        if page_file in group:
            cluster = group[0]
    return VALIDATION_PIECES[m.group("prefix")], cluster


def is_duplicate_photo(page_file: str) -> bool:
    return any(page_file in g[1:] for g in DUPLICATE_PAGE_GROUPS)


# =============================================================================================
# Labels
# =============================================================================================
@dataclass
class StaffLabel:
    page_file: str
    piece: str
    cluster: str
    system_index: int
    staff_index: int
    voice: str
    clef: str                 # model class name (G | G8vb | F | other)
    key: int
    bbox: tuple[float, float, float, float]  # EXIF-upright frame
    sure: bool
    duplicate_photo: bool

    @property
    def sid(self) -> str:
        return f"{self.page_file}:s{self.system_index}:t{self.staff_index}"


def load_labels() -> tuple[list[StaffLabel], str, dict[str, str]]:
    """Loads and hash-verifies every label file (read-only). Returns labels, image_dir, hashes."""
    labels: list[StaffLabel] = []
    hashes: dict[str, str] = {}
    image_dirs: set[str] = set()
    for name, sha_name in LABEL_FILES:
        path = LABEL_DIR / name
        raw = path.read_bytes()
        expected = (LABEL_DIR / sha_name).read_text(encoding="utf-8").split()[0].strip()
        actual = sha256_bytes(raw)
        if actual != expected:
            raise RuntimeError(f"{name}: sha256 {actual} != {sha_name} {expected}; labels changed since "
                               "they were frozen, refusing to score")
        hashes[name] = actual
        doc = json.loads(raw.decode("utf-8"))
        image_dirs.add(doc["schema"]["image_dir"])
        for r in doc["staves"]:
            piece, cluster = page_info(r["page_file"])
            if r["clef"] not in LABEL_CLEF_MAP:
                raise ValueError(f"unknown label clef {r['clef']!r} in {name}")
            labels.append(StaffLabel(
                page_file=r["page_file"], piece=piece, cluster=cluster,
                system_index=int(r["system_index"]), staff_index=int(r["staff_index"]), voice=r["voice"],
                clef=LABEL_CLEF_MAP[r["clef"]], key=int(r["key_signature"]),
                bbox=tuple(float(v) for v in r["bbox"]),  # type: ignore[arg-type]
                sure=r["confidence"] == "sure", duplicate_photo=is_duplicate_photo(r["page_file"])))
    if len(image_dirs) != 1:
        raise ValueError(f"label files disagree on image_dir: {sorted(image_dirs)}")
    sids = [lab.sid for lab in labels]
    if len(sids) != len(set(sids)):
        raise ValueError("duplicate (page, system, staff) label entries")
    return labels, image_dirs.pop(), hashes


# =============================================================================================
# Geometry
# =============================================================================================
def verify_upright_frame(photo: Path) -> None:
    """Checks the label frame (PIL exif_transpose) and Stage 1's frame (cv2.imread) agree.

    Why: the JPEGs are stored 4032x3024 with EXIF orientation 6. Stage 1 uses cv2.imread with
    default flags, which applies EXIF orientation; if that ever stopped being true every label
    bbox would be in a different frame from the pipeline and the matching would be meaningless.
    """
    with Image.open(photo) as im:
        upright = ImageOps.exif_transpose(im).size
    img = cv2.imread(str(photo))
    if img is None:
        raise ValueError(f"cannot read {photo}")
    cv_wh = (img.shape[1], img.shape[0])
    if upright != UPRIGHT_SIZE_WH or cv_wh != UPRIGHT_SIZE_WH:
        raise RuntimeError(f"{photo.name}: EXIF-upright {upright}, cv2.imread {cv_wh}, labels expect "
                           f"{UPRIGHT_SIZE_WH}")


def native_perspective(photo: Path) -> tuple[np.ndarray, tuple[float, float]]:
    """Re-derives Stage 1's upright-photo -> native-page map (downscale + perspective only).

    Mirrors stage1_preprocessing.preprocess_score_page Step 0 / 0.5 exactly, because Stage 1 does
    not return its matrix and Stage 1 must not be modified here. If Stage 1's Step 0 changes, this
    silently diverges; the per-page residual check in match_page() is the guard.

    Returns:
        (3x3 matrix mapping upright-photo px -> native page px, native/upright scale (sx, sy)).
    """
    full = cv2.imread(str(photo))
    ph, pw = full.shape[:2]
    bgr = full
    if max(ph, pw) > s1.DETECT_MAX_DIM:
        sc = s1.DETECT_MAX_DIM / max(ph, pw)
        bgr = cv2.resize(full, (int(pw * sc), int(ph * sc)), interpolation=cv2.INTER_AREA)
    hi_w, hi_h = pw, ph
    if max(ph, pw) > s1.STRIP_SOURCE_MAX_DIM:
        sc = s1.STRIP_SOURCE_MAX_DIM / max(ph, pw)
        hi_w, hi_h = int(pw * sc), int(ph * sc)
    pre_k = (hi_w / bgr.shape[1], hi_h / bgr.shape[0])
    _, persp = s1._correct_perspective(bgr)  # noqa: SLF001 (read-only reuse, see docstring)
    photo_to_hi = np.diag([hi_w / pw, hi_h / ph, 1.0])
    if persp is None:
        return photo_to_hi, (hi_w / pw, hi_h / ph)
    s_m = np.diag([pre_k[0], pre_k[1], 1.0])
    return (s_m @ persp @ np.linalg.inv(s_m)) @ photo_to_hi, (hi_w / pw, hi_h / ph)


def label_rows_in_native(bbox: Sequence[float], m: np.ndarray) -> tuple[float, float]:
    """Top/bottom rows of a label bbox in the native page, measured on its vertical centre line."""
    x0, y0, x1, y1 = bbox
    xc = (x0 + x1) / 2.0
    pts = cv2.perspectiveTransform(np.array([[[xc, y0], [xc, y1]]], dtype=np.float64), m)[0]
    return float(min(pts[:, 1])), float(max(pts[:, 1]))


def vertical_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


# =============================================================================================
# Per-staff record
# =============================================================================================
@dataclass
class StaffResult:
    label: StaffLabel
    status: str = "pending"          # scored | pipeline_miss | no_staff_geometry | label_unsure
    reason: Optional[str] = None
    pipeline_voice: Optional[str] = None
    match_iou: Optional[float] = None
    page_angle: Optional[float] = None
    clef_probs: Optional[list[float]] = None
    key_probs: Optional[list[float]] = None
    extra: dict[str, Any] = field(default_factory=dict)


def run_page(photo: Path, labels: list[StaffLabel], yolo: Path, work: Path,
             inputs_out: dict[str, np.ndarray]) -> tuple[list[StaffResult], dict[str, Any]]:
    """Stage 1 + Stage 2 on one page, then matches Stage 2 boxes to that page's labels."""
    results = [StaffResult(lab) for lab in labels]
    page_diag: dict[str, Any] = {"page_file": photo.name}
    for r in results:
        if not r.label.sure:
            r.status, r.reason = "label_unsure", "label confidence unsure"
    todo = [r for r in results if r.status == "pending"]

    def miss_all(status: str, reason: str) -> tuple[list[StaffResult], dict[str, Any]]:
        for r in todo:
            r.status, r.reason = status, reason
        page_diag["page_failure"] = reason
        return results, page_diag

    verify_upright_frame(photo)
    try:
        page = s1.preprocess_score_page(str(photo), keep_unmasked=True)
    except (ValueError, RuntimeError, cv2.error) as exc:
        return miss_all("pipeline_miss", f"stage1_error: {exc}")
    page_diag["stage1_angle"] = float(page.angle)
    page_diag["mask_applied"] = bool(page.mask_applied)
    manifest_path = work / f"{photo.stem}_manifest.json"
    try:
        detect_staff_regions([(page.detect, 0, page.strip_source)], model_weights=str(yolo),
                             output_dir=str(work / "strips"), save_strips=False, save_viz=False,
                             manifest_path=str(manifest_path))
    except ValueError as exc:
        return miss_all("pipeline_miss", f"unsupported_staff_layout: {exc}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    page_diag["n_stage2_boxes"] = len(manifest)
    if not manifest:
        return miss_all("pipeline_miss", "stage2_no_boxes")

    unmasked, staves = page.strip_unmasked, page.strip_staves or []
    det_h, det_w = page.detect.shape[:2]
    ref = unmasked if unmasked is not None else page.strip_source
    sy = (ref.shape[0] / det_h) if ref is not None else 1.0
    boxes = [((b["box"]["y1"] + 0.5) * sy - 0.5, (b["box"]["y2"] + 0.5) * sy - 0.5, b["voice"], b["box"]["x1"])
             for b in manifest]

    m, _ = native_perspective(photo)
    lab_rows = {r.label.sid: label_rows_in_native(r.label.bbox, m) for r in todo}
    pairs = sorted(((vertical_iou(lab_rows[r.label.sid], (b[0], b[1])), i, j)
                    for i, r in enumerate(todo) for j, b in enumerate(boxes)), reverse=True)
    used_r: set[int] = set()
    used_b: set[int] = set()
    for iou, i, j in pairs:
        if iou < MIN_MATCH_IOU:
            break
        if i in used_r or j in used_b:
            continue
        used_r.add(i)
        used_b.add(j)
        todo[i].match_iou, todo[i].pipeline_voice = float(iou), boxes[j][2]
        todo[i].extra["box_native_rows"] = [boxes[j][0], boxes[j][1]]
        todo[i].extra["box_left_detect"] = boxes[j][3]
    page_diag["unmatched_stage2_boxes"] = len(boxes) - len(used_b)

    # Map-quality guard: label centre vs nearest tracked staff, in spacings.
    residuals = []
    for r in todo:
        rows = lab_rows[r.label.sid]
        c = (rows[0] + rows[1]) / 2.0
        if staves:
            s = min(staves, key=lambda st: abs(st.center - c))
            residuals.append(abs(s.center - c) / s.spacing)
    page_diag["label_to_staff_residual_spacings_median"] = float(np.median(residuals)) if residuals else None
    if residuals and float(np.median(residuals)) > RESIDUAL_WARN_SPACINGS:
        logger.warning("%s: label->native map residual %.2f spacings; matching may be unreliable",
                       photo.name, float(np.median(residuals)))

    for i, r in enumerate(todo):
        r.page_angle = page_diag["stage1_angle"]
        if i not in used_r:
            r.status, r.reason = "pipeline_miss", "no stage2 box overlaps the label"
            continue
        if unmasked is None:
            r.status, r.reason = "no_staff_geometry", "no_unmasked_page (non-staff mask not applied)"
            continue
        top_b, bot_b = r.extra["box_native_rows"]
        centre = (top_b + bot_b) / 2.0
        band = min(staves, key=lambda st: abs(st.center - centre)) if staves else None
        if band is None or abs(band.center - centre) > BAND_MAX_OFFSET_SPACINGS * band.spacing:
            r.status, r.reason = "no_staff_geometry", "no tracked band within 1 spacing of the box"
            continue
        top = band.center - STAFF_HALF_HEIGHT_SPACINGS * band.spacing
        bottom = band.center + STAFF_HALF_HEIGHT_SPACINGS * band.spacing
        sx = unmasked.shape[1] / det_w
        x0 = ck.staff_left_edge(unmasked, top, bottom, search_from_x=int(r.extra["box_left_detect"] * sx))
        if x0 is None:
            r.status, r.reason = "no_staff_geometry", "staff_left_edge found no staff start"
            continue
        inputs_out[r.label.sid] = ck.make_input(unmasked, x0, top, bottom)
        r.extra["geometry"] = {"x0": int(x0), "top": float(top), "bottom": float(bottom)}
        r.status = "scored"
    return results, page_diag


# =============================================================================================
# Statistics
# =============================================================================================
def wilson(k: int, n: int) -> Optional[tuple[float, float]]:
    if n == 0:
        return None
    p = k / n
    z2 = WILSON_Z ** 2
    den = 1 + z2 / n
    mid = (p + z2 / (2 * n)) / den
    half = WILSON_Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def auroc(conf: np.ndarray, correct: np.ndarray) -> Optional[float]:
    """Mann-Whitney AUROC of confidence for right (positive) vs wrong, ties counted half."""
    pos, neg = conf[correct], conf[~correct]
    if len(pos) == 0 or len(neg) == 0:
        return None
    greater = (pos[:, None] > neg[None, :]).sum()
    ties = (pos[:, None] == neg[None, :]).sum()
    return float((greater + 0.5 * ties) / (len(pos) * len(neg)))


def cluster_bootstrap(clusters: np.ndarray, sure: np.ndarray, correct: np.ndarray
                      ) -> Optional[tuple[float, float]]:
    """Percentile CI of accuracy-when-sure, resampling physical pages with replacement."""
    ids = np.unique(clusters)
    if len(ids) == 0 or not sure.any():
        return None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    k_c = np.array([(sure & correct & (clusters == c)).sum() for c in ids])
    n_c = np.array([(sure & (clusters == c)).sum() for c in ids])
    accs = []
    for _ in range(BOOTSTRAP_REPS):
        pick = rng.integers(0, len(ids), len(ids))
        n = n_c[pick].sum()
        if n:
            accs.append(k_c[pick].sum() / n)
    if not accs:
        return None
    lo, hi = np.quantile(accs, [BOOTSTRAP_ALPHA / 2, 1 - BOOTSTRAP_ALPHA / 2])
    return float(lo), float(hi)


def head_metrics(conf: np.ndarray, sure: np.ndarray, correct: np.ndarray, clusters: np.ndarray
                 ) -> dict[str, Any]:
    """Accuracy-when-sure, coverage, confident-wrong, AUROC for one head on one staff set."""
    n = len(conf)
    n_sure, k_sure = int(sure.sum()), int((sure & correct).sum())
    n_wrong = int((~correct).sum())
    cw = int((sure & ~correct).sum())
    au = auroc(conf, correct)
    return {
        "n_scored": n, "n_sure": n_sure, "coverage": n_sure / n if n else None,
        "accuracy_when_sure": k_sure / n_sure if n_sure else None,
        "wilson95_when_sure": wilson(k_sure, n_sure),
        "page_bootstrap95_when_sure": cluster_bootstrap(clusters, sure, correct),
        "accuracy_all": float(correct.mean()) if n else None,
        "confident_wrong": cw, "confident_wrong_rate": cw / n if n else None,
        "n_wrong": n_wrong,
        "auroc": au if n_wrong >= AUROC_MIN_WRONG else None,
        "auroc_note": None if n_wrong >= AUROC_MIN_WRONG else f"AUROC not estimable ({n_wrong} wrong)",
        "auroc_raw_for_info": au,
    }


def gate(m: dict[str, Any]) -> dict[str, Any]:
    """Pre-registered gate for one head on the pooled unique set (A.2/A.5)."""
    if m["n_sure"] < GATE_MIN_SURE_N:
        return {"verdict": "not proven", "why": f"pooled sure-n {m['n_sure']} < {GATE_MIN_SURE_N}"}
    lb = m["wilson95_when_sure"][0]
    checks = {"accuracy_when_sure>=0.99": m["accuracy_when_sure"] >= GATE_MIN_ACC,
              "wilson_lb>=0.97": lb >= GATE_MIN_WILSON_LB,
              "confident_wrong_rate<=0.01": m["confident_wrong_rate"] <= GATE_MAX_CONFIDENT_WRONG}
    if m["auroc"] is not None:
        checks["auroc>=0.90"] = m["auroc"] >= GATE_MIN_AUROC
    else:
        checks["auroc"] = "not estimable on real set; must be checked on DS2/synthetic stress sets (A.5.1)"
    passed = all(v is True for v in checks.values() if isinstance(v, bool))
    verdict = "fail" if not passed else ("pass" if m["auroc"] is not None
                                         else "pass on real-set criteria; AUROC still to check on stress sets")
    return {"verdict": verdict, "checks": checks}


# =============================================================================================
# Scoring
# =============================================================================================
def collapse(name: str, g8vb_reliable: bool) -> str:
    return "treble" if (not g8vb_reliable and name in ("G", "G8vb")) else name


def score(results: list[StaffResult], ckpt: dict[str, Any]) -> dict[str, Any]:
    g8r = bool(ckpt["g8vb_reliable"])
    clef_t, key_t = float(ckpt["clef_threshold"]), float(ckpt["key_threshold"])
    classes = list(ckpt["clef_classes"])
    other = classes.index("other")
    scored = [r for r in results if r.status == "scored"]
    for r in scored:
        pc, pk = np.array(r.clef_probs), np.array(r.key_probs)
        pred_c = classes[int(pc.argmax())]
        pred_k = ck.index_to_key(int(pk.argmax()))
        # Pipeline rule 1: raw top probability vs the val-fitted threshold; "other" is never sure.
        r.extra.update({
            "pred_clef": pred_c, "clef_conf": float(pc.max()),
            "clef_sure": bool(pc.argmax() != other and pc.max() >= clef_t),
            "clef_correct": collapse(pred_c, g8r) == collapse(r.label.clef, g8r),
            "pred_key": pred_k, "key_conf": float(pk.max()), "key_sure": bool(pk.max() >= key_t),
            "key_correct": pred_k == r.label.key,
        })
        allowed = ALLOWED_CLEFS.get(r.pipeline_voice or "", frozenset())
        r.extra["clef_voice_mismatch_pred"] = collapse(pred_c, g8r) not in allowed
        r.extra["clef_voice_mismatch_label"] = collapse(r.label.clef, g8r) not in allowed
        r.extra["pipeline_voice_differs_from_label"] = r.pipeline_voice != r.label.voice

    def block(rs: list[StaffResult], all_rs: list[StaffResult]) -> dict[str, Any]:
        sc = [r for r in rs if r.status == "scored"]
        cl = np.array([r.label.cluster for r in sc])
        out: dict[str, Any] = {
            "n_labelled": len(all_rs),
            "n_label_unsure": sum(r.status == "label_unsure" for r in all_rs),
            "pipeline_miss": sum(r.status == "pipeline_miss" for r in all_rs),
            "no_staff_geometry": sum(r.status == "no_staff_geometry" for r in all_rs),
            "n_scored": len(sc)}
        denom = out["n_labelled"] - out["n_label_unsure"]
        out["pipeline_miss_rate"] = out["pipeline_miss"] / denom if denom else None
        out["no_staff_geometry_rate"] = out["no_staff_geometry"] / denom if denom else None
        for head in ("clef", "key"):
            out[head] = head_metrics(np.array([r.extra[f"{head}_conf"] for r in sc]),
                                     np.array([r.extra[f"{head}_sure"] for r in sc], dtype=bool),
                                     np.array([r.extra[f"{head}_correct"] for r in sc], dtype=bool), cl)
        out["clef_voice_mismatch"] = {
            "pred_vs_pipeline_voice": sum(r.extra["clef_voice_mismatch_pred"] for r in sc),
            "label_clef_vs_pipeline_voice": sum(r.extra["clef_voice_mismatch_label"] for r in sc),
            "pipeline_voice_differs_from_label_voice": sum(r.extra["pipeline_voice_differs_from_label"]
                                                           for r in sc)}
        g8 = [r for r in sc if r.label.clef == "G8vb"]
        gg = [r for r in sc if r.label.clef == "G"]
        out["g8vb"] = {"n_g8vb": len(g8), "n_g": len(gg),
                       "g8vb_recall": (sum(r.extra["pred_clef"] == "G8vb" for r in g8) / len(g8)) if g8 else None,
                       "g_called_g8vb": (sum(r.extra["pred_clef"] == "G8vb" for r in gg) / len(gg)) if gg else None}
        per_key: dict[str, dict[str, int]] = {}
        for r in sc:
            d = per_key.setdefault(str(r.label.key), {"n": 0, "correct": 0, "sure": 0, "sure_correct": 0})
            d["n"] += 1
            d["correct"] += int(r.extra["key_correct"])
            d["sure"] += int(r.extra["key_sure"])
            d["sure_correct"] += int(r.extra["key_sure"] and r.extra["key_correct"])
        out["per_key_value"] = dict(sorted(per_key.items(), key=lambda kv: int(kv[0])))
        return out

    unique = [r for r in results if not r.label.duplicate_photo]
    dup = [r for r in results if r.label.duplicate_photo]
    pieces = sorted({r.label.piece for r in results})
    report: dict[str, Any] = {
        "unique_staves": len(unique), "duplicate_photo_staves": len(dup),
        "per_piece": {p: block([r for r in unique if r.label.piece == p],
                               [r for r in unique if r.label.piece == p]) for p in pieces},
        "pooled": block(unique, unique),
        "duplicate_photo_consistency": block(dup, dup) if dup else None,
    }
    report["gate"] = {h: gate(report["pooled"][h]) for h in ("clef", "key")}
    g8n = report["pooled"]["g8vb"]["n_g8vb"]
    report["g8vb_real_evidence"] = {
        "n_real_g8vb": g8n, "sufficient_for_gate": g8n >= G8VB_MIN_REAL_SUPPORT,
        "note": "reported only; this script never changes g8vb_reliable in the checkpoint (A.4)"}
    return report


# =============================================================================================
# Main
# =============================================================================================
def load_frozen(ckpt_path: Path, allow_smoke: bool) -> tuple[ck.ClefKeyNet, dict[str, Any]]:
    ckpt: dict[str, Any] = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    if ckpt.get("smoke_test") and not allow_smoke:
        raise RuntimeError("checkpoint is a smoke-test model; pass --allow-smoke only for a dry run")
    if ckpt["crop_spec_version"] != ck.CROP_SPEC_VERSION:
        raise RuntimeError(f"crop spec {ckpt['crop_spec_version']} != core {ck.CROP_SPEC_VERSION}")
    core = sha256_text_file(CORE_PATH)
    if ckpt["core_sha256"] != core:
        raise RuntimeError(f"clef_key_core.py sha {core} != checkpoint core_sha256 {ckpt['core_sha256']}")
    model = ck.ClefKeyNet(width=ckpt["arch"]["width"], dropout=ckpt["arch"]["dropout"])
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model, ckpt


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--checkpoint", type=Path, required=True,
                   help="frozen training/clef_key_artifacts/<run_id>/clef_key_classifier.pt")
    p.add_argument("--yolo", type=Path, default=DEFAULT_YOLO)
    p.add_argument("--image-dir", type=Path, default=None, help="override the labels' image_dir")
    p.add_argument("--device", default="cpu",
                   help="cpu by default: the local GPU produced corrupted outputs in the S2 smoke test")
    p.add_argument("--allow-smoke", action="store_true", help="dry run against a smoke checkpoint")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    run_dir = args.checkpoint.resolve().parent
    out_path = run_dir / OUTPUT_NAME
    if out_path.exists():
        raise SystemExit(f"{out_path} exists: the real-set check is run once per frozen checkpoint")
    if "music_symbol_detection" in run_dir.parts:
        raise SystemExit("refusing to write under music_symbol_detection")

    model, ckpt = load_frozen(args.checkpoint, args.allow_smoke)
    device = torch.device(args.device)
    model.to(device)
    labels, image_dir, label_hashes = load_labels()
    image_dir_path = args.image_dir or Path(image_dir)

    by_page: dict[str, list[StaffLabel]] = {}
    for lab in labels:
        by_page.setdefault(lab.page_file, []).append(lab)

    results: list[StaffResult] = []
    pages: list[dict[str, Any]] = []
    inputs: dict[str, np.ndarray] = {}
    with tempfile.TemporaryDirectory(prefix="realval_") as tmp:
        for page_file in sorted(by_page):
            page_info(page_file)  # refuses non-validation pages before the file is opened
            photo = image_dir_path / page_file
            logger.info("page %s (%d labelled staves)", page_file, len(by_page[page_file]))
            rs, diag = run_page(photo, by_page[page_file], args.yolo, Path(tmp), inputs)
            results.extend(rs)
            pages.append(diag)

    sids = [r.label.sid for r in results if r.status == "scored"]
    lookup = {r.label.sid: r for r in results}
    for start in range(0, len(sids), INFER_BATCH):
        chunk = sids[start:start + INFER_BATCH]
        pc, pk = ck.predict_probs(model, np.stack([inputs[s] for s in chunk]), ckpt["clef_temperature"],
                                  ckpt["key_temperature"], device)
        for s, c, k in zip(chunk, pc, pk):
            lookup[s].clef_probs, lookup[s].key_probs = c.tolist(), k.tolist()

    report = score(results, ckpt)
    out = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checkpoint": str(args.checkpoint), "checkpoint_sha256": sha256_bytes(args.checkpoint.read_bytes()),
        "core_sha256": ckpt["core_sha256"], "label_sha256": label_hashes,
        "thresholds_from_checkpoint": {k: ckpt[k] for k in ("clef_temperature", "key_temperature",
                                                           "clef_threshold", "key_threshold", "g8vb_reliable")},
        "smoke_checkpoint": bool(ckpt.get("smoke_test")),
        "scoring": {"fields": "start-of-staff clef and key_signature only; mid_staff_changes ignored",
                    "clef_mode": "exact 4-class" if ckpt["g8vb_reliable"] else "G/G8vb collapsed to treble",
                    "gate_set": "unique staves (duplicate photos scored separately)",
                    "matching": "Stage 2 box <-> label bbox by vertical IoU in the native page frame"},
        "report": report, "pages": pages,
        "staves": [{"sid": r.label.sid, "piece": r.label.piece, "label_voice": r.label.voice,
                    "label_clef": r.label.clef, "label_key": r.label.key, "status": r.status, "reason": r.reason,
                    "pipeline_voice": r.pipeline_voice, "match_iou": r.match_iou, "page_angle": r.page_angle,
                    "clef_probs": r.clef_probs, "key_probs": r.key_probs, **r.extra} for r in results],
        "adjudication": "every model/label disagreement must be re-inspected from the image and logged in "
                        "data/val_clefkey/adjudication.json (A.5.4); this script does not write it",
    }
    tmp_out = out_path.with_name(out_path.name + ".tmp")
    tmp_out.write_text(json.dumps(out, indent=1, default=json_default), encoding="utf-8")
    tmp_out.replace(out_path)
    if inputs:
        np.savez_compressed(run_dir / INPUTS_NAME, sids=np.array(list(inputs)),
                            inputs=np.stack(list(inputs.values())).astype(np.float16))
    logger.info("wrote %s; gate clef=%s key=%s", out_path, report["gate"]["clef"]["verdict"],
                report["gate"]["key"]["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
