"""Phase 1 corpus cut: camera-augmented photos of the rendered pages, cut by the real Stage 1 + Stage 2 (PIYA-106).

Why this exists (docs/decisions/piya-106-ser-15-plan.md, Phase 1 step 5 and the Step 6 amendments 2-3): the CRNN
is retrained on exactly the strips serving produces, so every training image must come out of the frozen serving
code. Each rendered page (Verovio SVG, labels already checked by svg_check / G1 / G1b) becomes a synthetic phone
photo, then goes through `stage1_preprocessing.preprocess_score_page` and `stage2_detection.detect_staff_regions`
unchanged; the strip Stage 2 returns is the training image and the render's label for that (page, system, voice)
is its target.

Camera augmentation is applied to the PAGE, before Stage 1, so the real normaliser, binariser, mask and grey
strip source produce the real artefacts (ml-cv-lead 2026-09-30: no morphology on strips, no thinning). Ranges are
matched to the measured dev camera page statistics (`camera_page_stats.py`; eval_prelim dev pages, user decision
2026-09-28, which makes Honneur less independent: a stated, accepted trade-off), weighted toward low contrast, and
never to SER. Stroke weight is varied in the vector page (line / stem / barline widths, glyph emboldening) so the
grey path spans the eroded (~0.10 interline) to fused (~0.26+) line regimes after blur.

Train = serve guards:
* `git diff c77ce7b -- stage1_preprocessing.py stage2_detection.py` must be empty (hard fail).
* Strips are the arrays Stage 2 returns from the grey `strip_source`; `paper_fill` is imported to assert the
  serving fill is the one in use (Stage 1 calls it itself; nothing here reimplements it).

Label matching: Stage 2 numbers systems per page top to bottom and voices by position. A page is kept only when the
Stage 2 staff count equals the render's systems x 4 AND every detected box centre lies within
STAFF_MATCH_MAX_SPACINGS of (and nearest to) where the render's staff lands (render -> Stage 1 page registration,
ORB homography), else the page is dropped and logged; nothing is guessed.

Dot/flag/tie survival (plan step-5 amendment; ties added by ml-cv-lead review R2): every drawn dot, flag and tie
gets a contrast z measured on the actual strip source at strip scale, after Stage 1's mask, plus z values of the
same footprint on nearby blank paper (the null). `report` sets the pass threshold so under 1% of null placements
pass, and `manifest` drops a strip whose feature falls below it, so the model never learns to insert a dot or tie
from context. OOV-quarantined strips (amendment 2) are skipped. The validation split is by melody group
(`melody_groups.py`) or mass (`palestrina_groups.py`) (amendment 3). `--variant` gives independent extra photos of a
page (amendment 3: fresh augmentation per targeted repeat).

Usage:
  python training/phase1/cut_corpus.py run --out D:/PiyaNota-training/data/phase1_strips/bach --prefix bach_
      [--limit N] [--smoke N] [--max-minutes M] [--keep-photos] [--stats] [--variant V] [--workers W]
      (pages run in spawned workers recycled every WORKER_MAX_TASKS pages; a smoke runs round-robin by font)
  python training/phase1/cut_corpus.py report --out ... (smoke: null calibration, stats vs camera, bias)
  python training/phase1/cut_corpus.py manifest --out ... --groups .../melody_groups.json --thresholds ...
  python training/phase1/cut_corpus.py tiles --out ... [--n 40]
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import gc
import hashlib
import html
import io
import json
import logging
import math
import multiprocessing
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import psutil
import resvg_py

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage1_preprocessing as s1  # noqa: E402
import stage2_detection as s2  # noqa: E402
from stage1_preprocessing import paper_fill  # noqa: E402,F401  (train = serve: the serving fill, see module doc)
from svg_check import PageGeometry, page_geometry  # noqa: E402

log = logging.getLogger("cut_corpus")

# ── provenance / frozen code ─────────────────────────────────────────────────────────────────────────────────────
FROZEN_COMMIT = "c77ce7b"
FROZEN_FILES: tuple[str, ...] = ("stage1_preprocessing.py", "stage2_detection.py")
CONVERTER = REPO / "training" / "music_to_agnostic.py"
DEFAULT_RENDERS = Path("D:/PiyaNota-training/data/phase1_renders/renders")
DEFAULT_YOLO = Path("D:/PiyaNota/staff_detector_files/weights/best.pt")
VOICES: tuple[str, ...] = ("Soprano", "Alto", "Tenor", "Bass")
STAFFS_PER_SYSTEM = 4
# Verovio leaves a page's last system unjustified, so a chorale's final bar or two can be a system ~0.1-0.2 of the
# page wide. Stage 1 tracks only staves spanning >= s1.STAFF_MIN_SPAN_FRAC of the page, so serving cannot cut it,
# and requiring all systems x 4 dropped every page that ends in one (11% of Bach strips, 227 pages that also hold
# full systems). The expected Stage 2 count is therefore read from the render: systems clearly wider than the
# tracker limit must be found, systems clearly narrower must not, and a system inside the band may go either
# way. Short systems are always last on a page, so the found staves are still a prefix and the nearest-staff
# check in process_page verifies every assignment; nothing is inferred from Stage 2's count alone.
# The band is in render-page widths, but the tracker compares against the image width, which is the whole frame
# when Stage 1 does not rectify the paper (the paper then fills ~0.65-0.9 of it): a 0.42-page system was missed in
# the smoke run. Hence the asymmetric band around s1.STAFF_MIN_SPAN_FRAC (0.3).
SHORT_SPAN_LO = 0.20
SHORT_SPAN_HI = 0.60
# Augmentation / smoke-selection seed. 20261001 was used by smoke50 / smoke50b and the stopped full run; the re-smoke
# after the 2026-10-01 ml-cv-lead review uses a fresh one so its pages are not the ones the ranges were tuned on.
# 20261002 ran bach_smoke100d (recal2) and was used to tune recal3, so recal3 smokes on 20261004.
BASE_SEED = 20261004
SPLIT_SEED = 20261001         # train/val group order; unchanged so the split does not move with the augmentation
VAL_FRACTION = 0.10           # of pieces, filled whole melody group at a time

# ── SVG geometry (Verovio units; interline 180 at every scale) ────────────────────────────────────────────────────
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
SVG_INTERLINE_UNITS = 180.0
STAFF_LINE_UNITS = 13.0
LEDGER_UNITS = 22.0
STEM_UNITS = 18.0
BARLINE_UNITS = 27.0
GLYPH_USE_SCALE = 0.72        # Verovio's `scale(0.72, 0.72)` on every glyph <use>
A4_ASPECT = 2970.0 / 2100.0
FEATURE_CSS: dict[str, str] = {
    "dot": "* {visibility:hidden} .dots, .dots * {visibility:visible}",
    "flag": "* {visibility:hidden} .flag, .flag * {visibility:visible}",
    # Ties and slurs (Camera-PrIMuS `slur.*` tokens are ties): thin curves that vanish at low contrast like dots
    # do, and the largest targeted class (ml-cv-lead review R2).
    "tie": "* {visibility:hidden} .tie, .tie *, .slur, .slur * {visibility:visible}",
}

# ── camera frame ─────────────────────────────────────────────────────────────────────────────────────────────────
FRAME_W, FRAME_H = 3024, 4032          # the dev phone's portrait frame (all 25 dev camera pages)
INTERLINE_RANGE = (18.0, 24.0)          # native px; dev camera p5-p95 18.5-23.4
FIT_MARGIN_SPACINGS = 2.0               # staff content stays this far inside the frame (labels must be complete)
FIT_MAX_ATTEMPTS = 30
FIT_SHRINK = 0.96                       # interline shrink after every 10 failed placements
PAPER_EXT_RANGE = (1.00, 1.30)          # paper sheet larger than the A4 render (octavo margins, frame-filling)
PAGE_POS_RANGE = (0.2, 0.8)             # where the render sits on the larger sheet, x the spare width / height
# Framing mixture (recal2, 2026-10-01): augmented paper_area_frac p50 was 0.90 against camera 1.00 (the dev photos
# fill the frame with paper). "fill" pages use a larger sheet with the render nearer its middle and are accepted
# only when the sheet covers FILL_MIN_PAPER_FRAC of the frame; a rejected draw counts as a failed placement
# attempt (FIT_MAX_ATTEMPTS) and redraws the framing. The remaining pages keep the previous framing.
FRAMING_FILL = "fill"
FRAMING_STANDARD = "standard"
FRAMING_FILL_P = 0.80
FILL_PAPER_EXT_RANGE = (1.30, 1.60)
FILL_PAGE_POS_RANGE = (0.35, 0.65)
FILL_MIN_PAPER_FRAC = 0.97
# Fill-mode vertical placement, computed sheet extension (ml-cv-lead ruling, 2026-10-01; replaces option 2).
# Centring the content left pages whose only system sits near the A4 top (ccy ~0.15 x A4 height) with no sheet
# above the frame top. Option 2 (ty drawn from a coverage interval, plus the retired FILL_PAGE_POS_Y_RANGE) still
# fell back on 6.1% of fill pages with a 1.71x single-system bias, because pos <= 1 caps the sheet above such
# content at (ext_y - 0.85) x A4 height; it is removed. Now ty is drawn with one rule for every page from
# FILL_TY_BAND x FRAME_H (inside the content-fit interval; the plain content-fit interval when the two do not meet),
# and blank paper is added to the sheet above / below the render until it reaches FILL_EDGE_OVERHANG_FRAC x FRAME_H
# plus the rotation / jitter headroom past both frame edges. The extra rows are part of the sheet canvas, so they
# get the same paper grey, texture and illumination (no seam). An extension above FILL_EXTRA_CAP_FRAC x FRAME_H is a
# fill->standard fallback, never clamped. The coverage and content-fit tests in fit_placement stay the arbiters.
# Horizontal (ml-cv-lead ruling (a)+(b), 2026-10-01): the remaining failures were short, left-aligned final systems;
# centring their content pushed the sheet right and left the frame's left side bare. Fill mode now anchors the page
# (not the content) at the drawn horizontal shift, moves it minimally only for content fit, and extends the sheet
# left / right by the same rule as top / bottom (FILL_EDGE_OVERHANG_FRAC x FRAME_W plus headroom, capped likewise).
FILL_TY_BAND = (0.30, 0.70)
FILL_EDGE_OVERHANG_FRAC = 0.035
FILL_HEADROOM_PAD_PX = 2.0
FILL_EXTRA_CAP_FRAC = 1.0
PAPER_EDGE_SAMPLES = 32                 # points per sheet edge for the coverage polygon (curl bends the edges)
SHIFT_FRAC = 0.04                       # content centre jitter, x frame size
ROT_DEG_MAX = 3.0                       # dev pages 1-3 deg
PERSP_JITTER_FRAC = 0.03                # corner jitter, x frame size
CURL_KINDS: tuple[str, ...] = ("none", "bow", "edge")
CURL_KIND_P: tuple[float, ...] = (0.35, 0.35, 0.30)
CURL_AMP_SPACINGS_MAX = 0.6             # inside what the Stage 1 dewarp follows

# ── stroke (vector page) ─────────────────────────────────────────────────────────────────────────────────────────
# Staff-line width x13 units (0.058-0.25 interline before blur). 0.8-2.6 alone gave measured FWHM p95 0.22 against
# camera p95 0.27 (smoke50b). Ruling (d), 2026-10-01: the 2.6-3.4 segment is drawn with reduced weight so that
# 5-20% of lines measure above the camera FWHM p95, not the ~30% a uniform 0.8-3.4 would give.
# Amendment 2026-10-01 (coordinator-approved): the ruled upper bound 3.4 cannot reach the target. FWHM is a whole-pixel
# count at ~21 px interline, and ISP sharpening narrows the profile, so a calibration probe (seed 20261077) put 0/100
# staves above camera p95 at line_mult 3.0-3.4 and 82/100 at 3.6-4.4. Upper bound was 3.4, now 4.2; weight was
# 0.20, now 0.30. Calibration pass: 8% of staves above camera p95.
# Recal2, 2026-10-01 (ml-cv-lead, after bach_smoke100c): the constants below were aimed AT the thresholds, so a
# Monte Carlo of the full smoke predicted failure. Lower bound 0.8 -> 1.2 (11% of staves measured a 2 px FWHM, the
# camera minimum is 3 px); LINE_INK_HIGH, PAPER_GREY_RANGE, TEXTURE_SIGMA and NOISE_SIGMA changed with it. Thick
# segment, sharpening, blur, ink_depth, illumination and the LINE_INK_LOW regime unchanged.
LINE_MULT_RANGE = (1.2, 2.6)
LINE_MULT_THICK_RANGE = (2.6, 4.2)
LINE_MULT_THICK_P = 0.30
STEM_MULT_RANGE = (0.8, 2.0)
BAR_MULT_RANGE = (0.8, 1.8)
LEDGER_REL_RANGE = (0.9, 1.15)          # ledger multiplier relative to the staff-line one
EMBOLDEN_P = 0.5
EMBOLDEN_SPACINGS_MAX = 0.04            # glyph outline stroke, x interline (both sides together)
# Recalibrated 2026-10-01 after smoke-50 (fixed staff-extent measurement): the first ranges gave a measured line
# depth p50 ~0.38 against camera p50 0.84 and put ~75% of staves below the camera p5 (0.46); page drops (tracker
# failures) concentrated in the faintest tertile. Measured depth runs ~0.55-0.85 x nominal (blur, thin lines).
# Ruling (c), 2026-10-01: smoke50b still too faint (93% of staves in the camera's bottom line-depth quartile, 0% in
# the top one). The low regime keeps the faint tail inside LOW_SHARE_BAND; its share was 0.25.
# Calibration pass 1 (with ISP sharpening) left no staff below camera p5 (LOW_SHARE_BAND needs >= 0.05), so the low
# regime is fainter rather than more frequent: p 0.25 -> 0.20, range (0.55, 0.85) -> (0.40, 0.75).
LINE_INK_LOW_P = 0.20
LINE_INK_LOW = (0.40, 0.75)
LINE_INK_HIGH = (0.92, 1.0)            # recal2: was (0.85, 1.0)

# ── photometric (camera frame) ───────────────────────────────────────────────────────────────────────────────────
INK_LOW_P = 0.20                        # weighted toward low contrast (ml-cv-lead); 0.25 until ruling (c)
INK_LOW = (0.55, 0.80)                  # (0.65, 0.85) until 2026-10-01: with sharpening no head fell below camera p5
INK_HIGH = (0.88, 1.0)                  # was (0.85, 0.98): head depth reached camera p50 0.95 on too few staves
PAPER_GREY_RANGE = (230.0, 255.0)       # recal2: was (205, 245), before that (165, 240). Paper-only camera
                                        # p25/p50/p75 215/222/226; measured paper grey runs ~0.90-0.92 x sampled
                                        # (illumination field and tint), not ~0.99 as this comment said before
BG_GREY_RANGE = (40.0, 150.0)           # table / background visible past the sheet
# Recal3 (ml-cv-lead, after bach_smoke100d): the old low band (0.35, 0.72) cited Honneur p3's frame-wide illum
# (0.39, dark table included); its paper-only illum is 0.79 and no camera page has paper-only illum below 0.78, so
# 20% of pages were lit darker than any photo and Stage 1 read their paper as background (paper_area < 0.80 on 20%).
ILLUM_LOW_P = 0.05                      # recal3: was 0.20
ILLUM_LOW = (0.70, 0.75)                # recal3: was (0.35, 0.72)
ILLUM_HIGH = (0.75, 0.83)               # recal3: was (0.72, 0.88); paper-only camera p25/p50/p75 0.798/0.818/0.829.
                                        # Paper-only reads 0.020/0.026/0.037 (p25/p50/p75) above the sampled frame
                                        # ratio in 100d; (0.76, 0.84) put the measured p50 in the camera IQR only
                                        # 79% of resamples, (0.75, 0.83) 99.6% (ml-cv-lead pre-run review)
SHADOW_P = 0.08                         # recal3: was 0.15
SHADOW_DEPTH = (0.60, 0.90)
# Recal3: share of the frame on the shadowed side (a margin shadow). Drawn as a share, not as an offset: the old
# offset was in frame-width units on a portrait frame, so offsets 0.30-0.45 (ml-cv-lead's proposal) shadowed
# 5-28% depending on angle, and the old uniform(-0.4, 0.4) put up to ~90% of the frame in shadow.
SHADOW_COVER = (0.05, 0.15)
SHADOW_SOFT_SPACINGS = (0.5, 4.0)
TEXTURE_SIGMA = (0.006, 0.012)          # relative paper texture; recal2: was (0.004, 0.02)
TEXTURE_SCALE_PX = (1.5, 5.0)
SPECK_MAX = 40
SPECK_DEPTH = (0.2, 0.8)
SPECK_RADIUS_PX = (0.6, 2.0)
BLUR_SPACINGS = (0.015, 0.07)           # optical blur sigma, x interline; was (0.02, 0.10): line FWHM p50 0.22
                                        # vs camera 0.19 with lines far shallower (phone ISP sharpens)
# Relative sensor noise. Calibrated to the corrected camera noise_rel (fixed staff comb, 2026-10-01): p5/p50/p95
# 0.0245/0.0284/0.0343 (the old comment's 0.031-0.051 came from the leaking off-staff columns). Was (0.02, 0.06):
# smoke50b measured noise_rel p50 0.038, above the camera p95. Measured noise includes the ISP sharpening below.
# Calibration fit (2 passes): noise_rel^2 ~ 0.89 (sigma f)^2 + 4.9 (texture f / scale)^2 + 0.016^2, f = 1 + 0.35 x
# sharpen amount; (0.017, 0.024) measured p50 0.031, so the range is lowered.
# recal3: was (0.016, 0.020); 100d noise_rel p50 0.0264 < camera p25 0.0268. (0.019, 0.021) projected a ~14% risk
# of noise share above camera p95 > 0.15; (0.0185, 0.0205) ~7% above-p95 and ~4% IQR risk (fit-extrapolated). Known
# limit, not to be tuned further: augmented noise is wider-spread than camera (texture, sharpening), so sigma alone
# cannot fit both tails.
NOISE_SIGMA = (0.0185, 0.0205)
NOISE_CORR_PX = (0.5, 1.2)              # demosaic/denoise correlation
# Phone ISP sharpening (ruling c): an unsharp mask after demosaic/denoise, before JPEG. It deepens thin lines and
# narrows their profile, which blur + contrast alone could not do (smoke50b line depth p50 0.57 vs camera 0.84).
SHARPEN_P = 0.85
SHARPEN_AMOUNT = (0.3, 1.0)             # 1.2 widened the noise spread past the camera p95
SHARPEN_SIGMA_PX = (0.8, 2.0)           # native px: the ISP works at sensor resolution, not in interlines
TINT_B_RANGE = (0.90, 1.0)              # warm paper / lamp: blue channel lowest
TINT_G_RANGE = (0.96, 1.0)
JPEG_Q_RANGE = (55, 95)

# ── matching and feature survival ────────────────────────────────────────────────────────────────────────────────
ORB_FEATURES = 20000
ORB_WORK_DIM = 2400
ORB_RATIO = 0.8
RANSAC_REPROJ_PX = 4.0
MIN_INLIERS = 80                        # a false homography with 80 RANSAC-consistent matches is implausible
STAFF_MATCH_MAX_SPACINGS = 4.0          # see the staff check in process_page. Identity is decided by the nearest
                                        # mapped staff and the margin below; this bound only rejects gross
                                        # registration failure. At 2.0 it dropped a page whose strips were all
                                        # correct (offset ~1.6 interline); the cause of such offsets is not
                                        # established (correlation with curl amplitude r = 0.14).
IDENTITY_MARGIN_MIN_SPACINGS = 2.0      # ruling (e): second-nearest minus assigned distance; below it the box drops
REFINE_PATCH_SPACINGS = 1.5             # template half-size around a dot/flag
REFINE_SEARCH_X_SPACINGS = 1.0          # after the per-staff offset correction
REFINE_SEARCH_Y_SPACINGS = 0.5          # after the staff offset; staff lines repeat every interline (border-checked)
REFINE_MIN_CORR = 0.3
REFINE_MIN_MARGIN = 0.05                # best peak must beat any peak >= REFINE_PEAK_EXCLUDE away by this much
REFINE_PEAK_EXCLUDE_SPACINGS = 0.3
OTHER_INK_DILATE_SPACINGS = 0.08        # flag footprint excludes the stem it hangs from
CORE_DARK_FRACTION = 0.5                # mean of the darkest half of the core (robust, not a noise extreme)
RING_IN_SPACINGS = 0.15
RING_OUT_SPACINGS = 0.6
RING_MIN_PX = 20
NULL_SAMPLES = 20                       # blank-paper placements per feature (ml-cv-lead R1)
NULL_TRIES = 200
NULL_REACH_SPACINGS = 3.0
NULL_RNG_STREAM = 1
NULL_FALSE_PASS_MAX = 0.01              # threshold = pooled null quantile at 1 - this (set in `report`)
NOISE_HP_SPACINGS = 0.5
NOISE_INK_EXCLUDE_SPACINGS = 0.5
FEATURE_MIN_PX = 4
INK_THRESHOLD = 128


@dataclass
class AugParams:
    """Every random choice for one page, so the photo can be regenerated bit for bit from `seed`."""

    seed: int
    interline_px: float
    render_width_px: int
    paper_ext: tuple[float, float]
    page_pos: tuple[float, float]
    line_mult: float
    ledger_mult: float
    stem_mult: float
    bar_mult: float
    embolden_spacings: float
    line_ink: float
    ink_depth: float
    paper_grey: float
    bg_grey: float
    illum_ratio: float
    illum_field: dict[str, Any]
    shadow: dict[str, float] | None
    texture_sigma: float
    texture_scale_px: float
    specks: int
    rot_deg: float
    shift: tuple[float, float]
    persp_jitter: list[float]
    curl_kind: str
    curl_amp_spacings: float
    curl_u0: float
    blur_spacings: float
    noise_sigma: float
    noise_corr_px: float
    tint_bgr: tuple[float, float, float]
    jpeg_q: int
    sharpen_amount: float = 0.0
    sharpen_sigma_px: float = 0.0
    fit_attempts: int = 0
    variant: int = 0
    framing_requested: str = FRAMING_STANDARD   # drawn mixture component
    framing_used: str = FRAMING_STANDARD        # differs only after a fill -> standard fallback
    paper_frame_frac: float = 0.0       # sheet polygon area inside the frame / frame area, of the accepted placement
    coverage_rejects: int = 0           # fill-mode attempts rejected for covering < FILL_MIN_PAPER_FRAC
    top_extra: int = 0                  # blank sheet rows added above the render's sheet (fill mode), canvas px
    bot_extra: int = 0                  # blank sheet rows added below
    left_extra: int = 0                 # blank sheet columns added left of the render's sheet (fill mode)
    right_extra: int = 0                # blank sheet columns added right
    tx_clamped: bool = False            # fill mode: page-anchored content column moved minimally to fit with margin
    content_x0_frame: float = 0.0       # fill mode: content box left edge in the frame before rotation/jitter, px
    ty_frac: float = 0.0                # drawn content-centre row / FRAME_H (fill mode)
    extra_cap_exceeded: bool = False    # an extension would exceed FILL_EXTRA_CAP_FRAC x FRAME_H -> fallback
    canvas_w_px: int = 0                # sheet canvas of the accepted placement
    canvas_h_px: int = 0


@dataclass
class PageJob:
    font: str
    piece: str
    page: int
    svg: Path
    png: Path
    labels: list[dict[str, Any]]
    meta: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.font}/{self.piece}/page_{self.page}"


@dataclass
class Feature:
    kind: str
    system_on_page: int
    staff_n: str
    mask: np.ndarray          # bool, canvas frame, cropped to bbox
    x0: int
    y0: int


@dataclass
class PageResult:
    key: str
    status: str
    reason: str | None
    seconds: float
    params: dict[str, Any]
    strips: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] | None = None
    rss_mb: float | None = None         # worker process RSS after the page (recal2 memory logging)
    peak_rss_mb: float | None = None    # worker peak working set so far (Windows only; None elsewhere)


def _u(lo_hi: tuple[float, float], rng: np.random.Generator) -> float:
    return float(rng.uniform(lo_hi[0], lo_hi[1]))


def page_seed(font: str, piece: str, page: int, variant: int) -> int:
    """Variant v of a page is an independent photo (amendment 3: fresh augmentation on each targeted repeat)."""
    h = hashlib.sha256(f"{BASE_SEED}|{font}|{piece}|{page}|{variant}".encode()).hexdigest()
    return int(h[:15], 16)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_frozen_code() -> str:
    """Hard-fails unless Stage 1/2 equal the frozen commit (working tree included). Returns HEAD."""
    diff = subprocess.run(["git", "-C", str(REPO), "diff", FROZEN_COMMIT, "--", *FROZEN_FILES],
                          capture_output=True, text=True, check=True).stdout
    if diff.strip():
        raise SystemExit(f"Stage 1/2 differ from frozen {FROZEN_COMMIT}; refusing to cut (train = serve).")
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


# ── jobs ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def load_jobs(renders: Path, prefix: str) -> list[PageJob]:
    jobs: list[PageJob] = []
    for meta_path in sorted(renders.glob(f"*/{prefix}*/meta.json")):
        d = meta_path.parent
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        labels = json.loads((d / "labels.json").read_text(encoding="utf-8"))
        for p in range(1, int(meta["pages"]) + 1):
            jobs.append(PageJob(font=d.parent.name, piece=d.name, page=p, svg=d / f"page_{p}.svg",
                                png=d / f"page_{p}.png", labels=[r for r in labels if r["page"] == p], meta=meta))
    return jobs


# ── vector page edits ────────────────────────────────────────────────────────────────────────────────────────────

def _classes(el: ET.Element) -> list[str]:
    return el.attrib.get("class", "").split()


def _add_style(el: ET.Element, style: str) -> None:
    # Verovio's own <style> sets `path {stroke:currentColor}`, which beats presentation attributes; an inline
    # style beats both.
    old = el.attrib.get("style", "")
    el.attrib["style"] = f"{old};{style}" if old else style


def edit_svg(svg_text: str, p: AugParams) -> str:
    """Applies the stroke-weight and staff-line ink edits to the vector page."""
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    root = ET.fromstring(svg_text)
    tag = f"{{{SVG_NS}}}"
    line_grey = int(round(255 * (1.0 - p.line_ink)))
    line_col = f"rgb({line_grey},{line_grey},{line_grey})"

    def walk(el: ET.Element) -> None:
        cls = _classes(el)
        if "staff" in cls:
            for ch in el:
                if ch.tag == f"{tag}path":
                    _add_style(ch, f"stroke:{line_col};stroke-width:{STAFF_LINE_UNITS * p.line_mult:.1f}")
        if "ledgerLines" in cls:
            for ch in el.iter(f"{tag}path"):
                _add_style(ch, f"stroke:{line_col};stroke-width:{LEDGER_UNITS * p.ledger_mult:.1f}")
        if "stem" in cls:
            for ch in el.iter(f"{tag}path"):
                _add_style(ch, f"stroke-width:{STEM_UNITS * p.stem_mult:.1f}")
        if "barLine" in cls:
            for ch in el.iter(f"{tag}path"):
                _add_style(ch, f"stroke-width:{BARLINE_UNITS * p.bar_mult:.1f}")
        if "system" in cls:
            for ch in el:
                if ch.tag == f"{tag}path":   # the system-start barline
                    _add_style(ch, f"stroke-width:{BARLINE_UNITS * p.bar_mult:.1f}")
        if p.embolden_spacings > 0:
            w = p.embolden_spacings * SVG_INTERLINE_UNITS
            if el.tag == f"{tag}use":
                _add_style(el, f"stroke:currentColor;stroke-width:{w / GLYPH_USE_SCALE:.1f}")
            elif el.tag in (f"{tag}ellipse", f"{tag}polygon"):
                _add_style(el, f"stroke:currentColor;stroke-width:{w:.1f}")
        for ch in el:
            walk(ch)

    walk(root)
    return ET.tostring(root, encoding="unicode")


FEATURE_CLASSES: dict[str, tuple[str, ...]] = {"dot": ("dots",), "flag": ("flag",), "tie": ("tie", "slur")}
HORIZONTAL_KINDS = frozenset({"tie"})   # registered vertically only (see measure_features)


def feature_kinds(svg_text: str) -> set[str]:
    """Kinds of survival-checked features drawn on the page, so a page without any skips their rasterisation."""
    present = {c for el in ET.fromstring(svg_text).iter() for c in _classes(el)}
    return {k for k, classes in FEATURE_CLASSES.items() if present.intersection(classes)}


def rasterise(svg: str, width_px: int, css: str | None = None) -> np.ndarray:
    png = resvg_py.svg_to_bytes(svg_string=svg, width=width_px, background="white", style_sheet=css)
    img = cv2.imdecode(np.frombuffer(bytes(png), np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("resvg returned an undecodable image")
    return img


# ── parameters and photo synthesis ───────────────────────────────────────────────────────────────────────────────

def draw_framing(framing: str, rng: np.random.Generator) -> tuple[tuple[float, float], tuple[float, float]]:
    """Sheet extension (x, y) and render position on the sheet (x, y) for one placement attempt of `framing`."""
    ext_r, pos_r = ((FILL_PAPER_EXT_RANGE, FILL_PAGE_POS_RANGE) if framing == FRAMING_FILL
                    else (PAPER_EXT_RANGE, PAGE_POS_RANGE))
    return (_u(ext_r, rng), _u(ext_r, rng)), (_u(pos_r, rng), _u(pos_r, rng))


_SHADOW_GRID_STEP = 16  # px; the projection quantile only needs to be good to a fraction of a percent of the frame


def shadow_offset_for_cover(angle: float, cover: float) -> float:
    """Shadow offset (frame-width units, as illumination_field uses it) that leaves `cover` of the frame shadowed.

    The shadowed side is where the projection onto the shadow direction exceeds offset x FRAME_W, so the offset is
    the (1 - cover) quantile of that projection over the frame grid (the midpoint of the soft edge).
    """
    yy, xx = np.mgrid[0:FRAME_H:_SHADOW_GRID_STEP, 0:FRAME_W:_SHADOW_GRID_STEP].astype(np.float64)
    proj = (xx - FRAME_W / 2) * math.cos(angle) + (yy - FRAME_H / 2) * math.sin(angle)
    return float(np.quantile(proj, 1.0 - cover) / FRAME_W)


def sample_params(rng: np.random.Generator, seed: int, svg_interline_px_per_width: float) -> AugParams:
    """Draws one page's parameters. `svg_interline_px_per_width`: interline / page width of the render."""
    interline = _u(INTERLINE_RANGE, rng)
    framing = FRAMING_FILL if rng.random() < FRAMING_FILL_P else FRAMING_STANDARD
    paper_ext, page_pos = draw_framing(framing, rng)
    line_mult = _u(LINE_MULT_THICK_RANGE if rng.random() < LINE_MULT_THICK_P else LINE_MULT_RANGE, rng)
    illum_low = rng.random() < ILLUM_LOW_P
    shadow = None
    if rng.random() < SHADOW_P:
        angle, cover = float(rng.uniform(0, 2 * math.pi)), _u(SHADOW_COVER, rng)
        shadow = {"angle": angle, "cover": cover, "offset": shadow_offset_for_cover(angle, cover),
                  "depth": _u(SHADOW_DEPTH, rng), "soft_spacings": _u(SHADOW_SOFT_SPACINGS, rng)}
    curl_kind = str(rng.choice(CURL_KINDS, p=CURL_KIND_P))
    return AugParams(
        seed=seed, interline_px=interline,
        render_width_px=int(round(interline / svg_interline_px_per_width)),
        paper_ext=paper_ext, page_pos=page_pos, framing_requested=framing, framing_used=framing,
        line_mult=line_mult, ledger_mult=line_mult * _u(LEDGER_REL_RANGE, rng),
        stem_mult=_u(STEM_MULT_RANGE, rng), bar_mult=_u(BAR_MULT_RANGE, rng),
        embolden_spacings=float(rng.uniform(0, EMBOLDEN_SPACINGS_MAX)) if rng.random() < EMBOLDEN_P else 0.0,
        line_ink=_u(LINE_INK_LOW if rng.random() < LINE_INK_LOW_P else LINE_INK_HIGH, rng),
        ink_depth=_u(INK_LOW if rng.random() < INK_LOW_P else INK_HIGH, rng),
        paper_grey=_u(PAPER_GREY_RANGE, rng), bg_grey=_u(BG_GREY_RANGE, rng),
        illum_ratio=_u(ILLUM_LOW if illum_low else ILLUM_HIGH, rng),
        illum_field={"gx": float(rng.normal()), "gy": float(rng.normal()),
                     "blobs": [[float(rng.uniform(-0.2, 1.2)), float(rng.uniform(-0.2, 1.2)),
                                float(rng.uniform(0.3, 0.9)), float(rng.choice([-1.0, 1.0]))] for _ in range(3)]},
        shadow=shadow,
        texture_sigma=_u(TEXTURE_SIGMA, rng), texture_scale_px=_u(TEXTURE_SCALE_PX, rng),
        specks=int(rng.integers(0, SPECK_MAX + 1)),
        rot_deg=float(rng.uniform(-ROT_DEG_MAX, ROT_DEG_MAX)),
        shift=(float(rng.uniform(-SHIFT_FRAC, SHIFT_FRAC)), float(rng.uniform(-SHIFT_FRAC, SHIFT_FRAC))),
        persp_jitter=[float(v) for v in rng.uniform(-PERSP_JITTER_FRAC, PERSP_JITTER_FRAC, 8)],
        curl_kind=curl_kind,
        curl_amp_spacings=float(rng.uniform(-CURL_AMP_SPACINGS_MAX, CURL_AMP_SPACINGS_MAX)) if curl_kind != "none"
        else 0.0,
        curl_u0=float(rng.uniform(0.5, 0.8)),
        blur_spacings=_u(BLUR_SPACINGS, rng), noise_sigma=_u(NOISE_SIGMA, rng),
        noise_corr_px=_u(NOISE_CORR_PX, rng),
        tint_bgr=(_u(TINT_B_RANGE, rng), _u(TINT_G_RANGE, rng), 1.0),
        jpeg_q=int(rng.integers(JPEG_Q_RANGE[0], JPEG_Q_RANGE[1] + 1)),
        sharpen_amount=_u(SHARPEN_AMOUNT, rng) if rng.random() < SHARPEN_P else 0.0,
        sharpen_sigma_px=_u(SHARPEN_SIGMA_PX, rng),
    )


@dataclass
class Placement:
    canvas_w: int
    canvas_h: int
    page_x: int
    page_y: int
    H: np.ndarray             # canvas -> frame (before curl)

    def curl(self, u: np.ndarray, p: AugParams) -> np.ndarray:
        amp = p.curl_amp_spacings * p.interline_px
        t = u / max(self.canvas_w, 1)
        if p.curl_kind == "bow":
            return amp * np.sin(np.pi * np.clip(t, 0, 1))
        if p.curl_kind == "edge":
            return amp * np.clip((t - p.curl_u0) / (1 - p.curl_u0), 0, None) ** 2
        return np.zeros_like(u)

    def to_frame(self, pts: np.ndarray, p: AugParams) -> np.ndarray:
        q = pts.astype(np.float64).copy()
        q[:, 1] += self.curl(q[:, 0], p)
        return cv2.perspectiveTransform(q.reshape(-1, 1, 2), self.H).reshape(-1, 2)


def canvas_layout(render_w: int, render_h: int, p: AugParams) -> tuple[int, int, int, int]:
    """Sheet size (cw, ch) and the render's top-left (px, py) on the sheet, in canvas px.

    Includes the fill-mode blank extensions on both axes (p.top_extra / p.bot_extra rows, p.left_extra /
    p.right_extra columns); all are 0 in standard framing.
    """
    a4_h = render_w * A4_ASPECT
    cw, ch = int(round(render_w * p.paper_ext[0])), int(round(max(a4_h, render_h) * p.paper_ext[1]))
    px, py = int((cw - render_w) * p.page_pos[0]), int((ch - a4_h) * p.page_pos[1]) if ch > a4_h else 0
    return (cw + p.left_extra + p.right_extra, ch + p.top_extra + p.bot_extra, px + p.left_extra,
            py + p.top_extra)


def draw_fill_extension(render_w: int, render_h: int, content: tuple[float, float, float, float], p: AugParams,
                        rng: np.random.Generator) -> bool:
    """Fill mode: places the content in the frame and sets the blank sheet needed on each side (rulings 2026-10-01).

    Vertical: ty ~ U(max(m + h_c/2, 0.30 FRAME_H), min(FRAME_H - m - h_c/2, 0.70 FRAME_H)) (FILL_TY_BAND), the plain
    content-fit interval when that band is empty; coverage does not limit ty.
    Horizontal: the PAGE (render) centre is anchored at FRAME_W/2 + shift_x FRAME_W, so a short left-aligned final
    system stays where it sits on the page instead of being centred (which pushed the sheet right and left the frame's
    left side bare). The content-centre column follows from the render, not the extended sheet, so the extension
    cannot move the page; it is moved minimally (p.tx_clamped) only when the content would not fit with margin.
    Canvas px map 1:1 to frame px before rotation and jitter; rotation and jitter are already drawn, so the headroom
    is |sin(rot)| x (the other frame dimension)/2 + the largest corner jitter on that axis + FILL_HEADROOM_PAD_PX.
    x and y extensions are both computed from the same pre-extension layout.

    Returns:
        False when an extension would exceed FILL_EXTRA_CAP_FRAC x the frame dimension on its axis (the page then
        falls back to standard framing; p.extra_cap_exceeded is set and no extension is applied), else True with the
        four extensions, p.ty_frac, p.tx_clamped, p.content_x0_frame and p.shift set.
    """
    p.top_extra = p.bot_extra = p.left_extra = p.right_extra = 0
    p.tx_clamped = False
    cw, ch, px, py = canvas_layout(render_w, render_h, p)
    cx0, cy0, cx1, cy1 = content
    ccx = px + (cx0 + cx1) / 2
    ccy = py + (cy0 + cy1) / 2
    w_c = cx1 - cx0
    h_c = cy1 - cy0
    m = FIT_MARGIN_SPACINGS * p.interline_px
    tx_page = FRAME_W / 2 + p.shift[0] * FRAME_W
    tx = tx_page + ((cx0 + cx1) / 2 - render_w / 2)
    tx_lo, tx_hi = m + w_c / 2, FRAME_W - m - w_c / 2
    if tx_lo <= tx_hi and not tx_lo <= tx <= tx_hi:    # an empty interval is left to place() to reject (no_fit)
        tx = min(max(tx, tx_lo), tx_hi)
        p.tx_clamped = True
    p.content_x0_frame = round(tx - w_c / 2, 1)
    rot_sin = abs(math.sin(math.radians(p.rot_deg)))
    head_x = rot_sin * FRAME_H / 2 + max(abs(v) for v in p.persp_jitter[0::2]) * FRAME_W + FILL_HEADROOM_PAD_PX
    delta_x = FILL_EDGE_OVERHANG_FRAC * FRAME_W
    left = max(0, math.ceil(tx + delta_x + head_x - ccx))
    right = max(0, math.ceil((FRAME_W - tx) + delta_x + head_x - (cw - ccx)))
    fit_lo, fit_hi = m + h_c / 2, FRAME_H - m - h_c / 2
    lo, hi = max(fit_lo, FILL_TY_BAND[0] * FRAME_H), min(fit_hi, FILL_TY_BAND[1] * FRAME_H)
    if lo > hi:
        lo, hi = fit_lo, max(fit_lo, fit_hi)    # an empty content-fit interval is left to place() to reject
    ty = float(rng.uniform(lo, hi))
    jitter_dy = max(abs(v) for v in p.persp_jitter[1::2]) * FRAME_H
    headroom = abs(math.sin(math.radians(p.rot_deg))) * FRAME_W / 2 + jitter_dy + FILL_HEADROOM_PAD_PX
    delta = FILL_EDGE_OVERHANG_FRAC * FRAME_H
    top = max(0, math.ceil(ty + delta + headroom - ccy))
    bot = max(0, math.ceil((FRAME_H - ty) + delta + headroom - (ch - ccy)))
    p.ty_frac = round(ty / FRAME_H, 4)
    if max(top, bot) > FILL_EXTRA_CAP_FRAC * FRAME_H or max(left, right) > FILL_EXTRA_CAP_FRAC * FRAME_W:
        p.extra_cap_exceeded = True
        return False
    p.top_extra, p.bot_extra, p.left_extra, p.right_extra = top, bot, left, right
    p.shift = ((tx - FRAME_W / 2) / FRAME_W, (ty - FRAME_H / 2) / FRAME_H)
    return True


def place(render_w: int, render_h: int, content: tuple[float, float, float, float], p: AugParams,
          rng: np.random.Generator) -> Placement | None:
    """Puts the paper sheet into the frame; None when the staff content would not fit with margin."""
    cw, ch, px, py = canvas_layout(render_w, render_h, p)
    cx0, cy0, cx1, cy1 = content
    ccx, ccy = px + (cx0 + cx1) / 2, py + (cy0 + cy1) / 2
    th = math.radians(p.rot_deg)
    cos, sin = math.cos(th), math.sin(th)
    tx = FRAME_W / 2 + p.shift[0] * FRAME_W
    ty = FRAME_H / 2 + p.shift[1] * FRAME_H
    corners = np.array([[0, 0], [cw, 0], [cw, ch], [0, ch]], dtype=np.float64)
    rel = corners - [ccx, ccy]
    sim = np.stack([cos * rel[:, 0] - sin * rel[:, 1] + tx, sin * rel[:, 0] + cos * rel[:, 1] + ty], axis=1)
    jit = np.array(p.persp_jitter).reshape(4, 2) * [FRAME_W, FRAME_H]
    H = cv2.getPerspectiveTransform(corners.astype(np.float32), (sim + jit).astype(np.float32))
    pl = Placement(canvas_w=cw, canvas_h=ch, page_x=px, page_y=py, H=H)
    n = 16
    xs = np.linspace(px + cx0, px + cx1, n)
    edge = np.concatenate([np.stack([xs, np.full(n, py + cy0)], 1), np.stack([xs, np.full(n, py + cy1)], 1)])
    f = pl.to_frame(edge, p)
    m = FIT_MARGIN_SPACINGS * p.interline_px
    if f[:, 0].min() < m or f[:, 0].max() > FRAME_W - m or f[:, 1].min() < m or f[:, 1].max() > FRAME_H - m:
        return None
    return pl


def _clip_to_frame(poly: np.ndarray) -> np.ndarray:
    """Sutherland-Hodgman clip of a polygon (N x 2) to the frame rectangle.

    The clip window is convex, so the result's area is exact even for the slightly non-convex curled sheet.
    """
    def clip(pts: np.ndarray, axis: int, bound: float, keep_below: bool) -> np.ndarray:
        if len(pts) == 0:
            return pts
        out: list[np.ndarray] = []
        for i in range(len(pts)):
            cur, nxt = pts[i], pts[(i + 1) % len(pts)]
            cur_in = cur[axis] <= bound if keep_below else cur[axis] >= bound
            nxt_in = nxt[axis] <= bound if keep_below else nxt[axis] >= bound
            if cur_in:
                out.append(cur)
            if cur_in != nxt_in:
                t = (bound - cur[axis]) / (nxt[axis] - cur[axis])
                out.append(cur + t * (nxt - cur))
        return np.array(out, dtype=np.float64).reshape(-1, 2)

    q = poly.astype(np.float64)
    for axis, bound, keep_below in ((0, 0.0, False), (0, float(FRAME_W), True), (1, 0.0, False),
                                    (1, float(FRAME_H), True)):
        q = clip(q, axis, bound, keep_below)
    return q


def paper_frame_fraction(pl: Placement, p: AugParams) -> float:
    """Share of the frame covered by the paper sheet (the canvas, curled and projected), 0..1.

    Same quantity, up to Stage 1's background estimate, as camera_page_stats' paper_area_frac (paper pixels / frame
    pixels), computed from geometry so the fill rule costs no rendering.
    """
    n = PAPER_EDGE_SAMPLES
    xs = np.linspace(0.0, pl.canvas_w, n, endpoint=False)
    ys = np.linspace(0.0, pl.canvas_h, n, endpoint=False)
    edge = np.concatenate([np.stack([xs, np.zeros(n)], 1),
                           np.stack([np.full(n, float(pl.canvas_w)), ys], 1),
                           np.stack([xs[::-1] + pl.canvas_w / n, np.full(n, float(pl.canvas_h))], 1),
                           np.stack([np.zeros(n), ys[::-1] + pl.canvas_h / n], 1)])
    q = _clip_to_frame(pl.to_frame(edge, p))
    if len(q) < 3:
        return 0.0
    area = 0.5 * abs(float(np.dot(q[:, 0], np.roll(q[:, 1], -1)) - np.dot(q[:, 1], np.roll(q[:, 0], -1))))
    return area / float(FRAME_W * FRAME_H)


def fit_placement(job: PageJob, p: AugParams, geom: PageGeometry, interline_frac: float,
                  rng: np.random.Generator) -> Placement | None:
    """Places the sheet so all staves fit with margin (and, in fill mode, the sheet fills the frame).

    Mutates `p`: every failed attempt redraws shift, rotation and perspective (fill mode also redraws the sheet
    extension and position, since those decide coverage); the interline shrinks by FIT_SHRINK after every 10
    attempts, but only when some of those 10 failed on content fit. Shrinking makes the sheet smaller, so a run of
    coverage-only rejections must not trigger it. Fill mode draws the vertical content position and extends the
    sheet with blank rows (`draw_fill_extension`); when an extension exceeds its cap, or FIT_MAX_ATTEMPTS fill
    attempts fail, the page falls back to standard framing (framing_used) for up to FIT_MAX_ATTEMPTS more,
    continuing the same generator.

    Args:
        job: the page.
        p: the page's parameters (updated in place with the accepted geometry and attempt counts).
        geom: `svg_check.page_geometry` of the page SVG.
        interline_frac: render interline / render width.
        rng: the page's generator.

    Returns:
        The accepted placement, or None when every attempt failed.
    """
    pl = _fit_attempts(job, p, geom, interline_frac, rng)
    if pl is None and p.framing_used == FRAMING_FILL:
        p.framing_used = FRAMING_STANDARD
        p.top_extra = p.bot_extra = p.left_extra = p.right_extra = 0
        p.paper_ext, p.page_pos = draw_framing(FRAMING_STANDARD, rng)
        p.shift = (float(rng.uniform(-SHIFT_FRAC, SHIFT_FRAC)), float(rng.uniform(-SHIFT_FRAC, SHIFT_FRAC)))
        pl = _fit_attempts(job, p, geom, interline_frac, rng)
    return pl


def _fit_attempts(job: PageJob, p: AugParams, geom: PageGeometry, interline_frac: float,
                  rng: np.random.Generator) -> Placement | None:
    """Up to FIT_MAX_ATTEMPTS placements under `p.framing_used`; see fit_placement."""
    bx = [b for b in job.meta["staff_boxes_px"] if b["page"] == job.page]
    fill = p.framing_used == FRAMING_FILL
    content_failed = False
    for attempt in range(FIT_MAX_ATTEMPTS):
        if attempt and attempt % 10 == 0:
            if content_failed:
                p.interline_px *= FIT_SHRINK
                p.render_width_px = int(round(p.interline_px / interline_frac))
            content_failed = False
        rw = p.render_width_px
        rh = int(round(rw * geom.height_px / geom.width_px))
        k = rw / float(job.meta["png_width_px"])
        content = (k * min(b["left"] for b in bx), k * min(b["top"] for b in bx) - 2 * p.interline_px,
                   k * max(b["right"] for b in bx), k * max(b["bottom"] for b in bx) + 2 * p.interline_px)
        p.fit_attempts += 1
        if fill and not draw_fill_extension(rw, rh, content, p, rng):
            return None
        pl = place(rw, rh, content, p, rng)
        if pl is None:
            content_failed = True
        else:
            p.paper_frame_frac = round(paper_frame_fraction(pl, p), 4)
            if not fill or p.paper_frame_frac >= FILL_MIN_PAPER_FRAC:
                p.canvas_w_px, p.canvas_h_px = pl.canvas_w, pl.canvas_h
                return pl
            p.coverage_rejects += 1
        p.shift = (float(rng.uniform(-SHIFT_FRAC, SHIFT_FRAC)), float(rng.uniform(-SHIFT_FRAC, SHIFT_FRAC)))
        p.persp_jitter = [float(v) for v in rng.uniform(-PERSP_JITTER_FRAC, PERSP_JITTER_FRAC, 8)]
        p.rot_deg = float(rng.uniform(-ROT_DEG_MAX, ROT_DEG_MAX))
        if fill:
            p.paper_ext, p.page_pos = draw_framing(FRAMING_FILL, rng)
    return None


def _smooth_noise(shape: tuple[int, int], sigma_px: float, rng: np.random.Generator) -> np.ndarray:
    n = rng.standard_normal(shape).astype(np.float32)
    if sigma_px > 0:
        n = cv2.GaussianBlur(n, (0, 0), sigma_px)
    sd = float(n.std())
    return n / sd if sd > 0 else n


def illumination(p: AugParams, rng_unused: np.random.Generator | None = None) -> np.ndarray:
    """Smooth irradiance field in [illum_ratio, 1] over the frame (plus an optional soft shadow)."""
    sh, sw = FRAME_H // 16, FRAME_W // 16
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    u, v = xx / sw, yy / sh
    f = p.illum_field["gx"] * u + p.illum_field["gy"] * v
    for bx, by, bs, sgn in p.illum_field["blobs"]:
        f = f + sgn * np.exp(-((u - bx) ** 2 + (v - by) ** 2) / (2 * bs ** 2))
    lo, hi = np.percentile(f, 2), np.percentile(f, 98)
    f = np.clip((f - lo) / max(hi - lo, 1e-6), 0, 1)
    f = p.illum_ratio + (1 - p.illum_ratio) * f
    f = cv2.resize(f, (FRAME_W, FRAME_H), interpolation=cv2.INTER_CUBIC)
    if p.shadow is not None:
        yy, xx = np.mgrid[0:FRAME_H, 0:FRAME_W].astype(np.float32)
        a = p.shadow["angle"]
        d = (xx - FRAME_W / 2) * math.cos(a) + (yy - FRAME_H / 2) * math.sin(a) - p.shadow["offset"] * FRAME_W
        soft = p.shadow["soft_spacings"] * p.interline_px
        s = 1.0 / (1.0 + np.exp(-d / soft))
        f = f * (1 - (1 - p.shadow["depth"]) * s)
    return f.astype(np.float32)


def synthesize(render: np.ndarray, pl: Placement, p: AugParams, rng: np.random.Generator) -> np.ndarray:
    """Vector-page raster -> BGR phone photo (geometry, photometrics, blur, noise, tint). JPEG is applied on save."""
    ink = np.zeros((pl.canvas_h, pl.canvas_w), np.float32)
    rh, rw = render.shape
    ink[pl.page_y:pl.page_y + rh, pl.page_x:pl.page_x + rw] = 1.0 - render.astype(np.float32) / 255.0
    for _ in range(p.specks):
        cx, cy = int(rng.integers(0, pl.canvas_w)), int(rng.integers(0, pl.canvas_h))
        cv2.circle(ink, (cx, cy), max(1, int(round(_u(SPECK_RADIUS_PX, rng)))), _u(SPECK_DEPTH, rng), -1,
                   lineType=cv2.LINE_AA)
    refl = 1.0 - p.ink_depth * np.clip(ink, 0, 1)
    refl += p.texture_sigma * _smooth_noise(refl.shape, p.texture_scale_px, rng)
    del ink
    # Frame -> canvas inverse map (curl is a vertical displacement in the paper).
    yy, xx = np.mgrid[0:FRAME_H, 0:FRAME_W].astype(np.float32)
    pts = np.stack([xx, yy], -1).reshape(-1, 1, 2)
    inv = cv2.perspectiveTransform(pts, np.linalg.inv(pl.H)).reshape(FRAME_H, FRAME_W, 2)
    map_u = inv[..., 0].astype(np.float32)
    map_v = (inv[..., 1] - pl.curl(inv[..., 0], p)).astype(np.float32)
    del pts, inv, yy, xx
    paper = cv2.remap(refl, map_u, map_v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
    alpha = cv2.remap(np.ones_like(refl), map_u, map_v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                      borderValue=0.0)
    del refl, map_u, map_v
    bg = (p.bg_grey / p.paper_grey) * (1.0 + 0.05 * _smooth_noise((FRAME_H, FRAME_W), 8.0, rng))
    img = alpha * paper + (1 - alpha) * bg
    del paper, alpha, bg
    img *= illumination(p) * p.paper_grey
    img = cv2.GaussianBlur(img, (0, 0), max(0.3, p.blur_spacings * p.interline_px))
    out = np.empty((FRAME_H, FRAME_W, 3), np.float32)
    for c in range(3):
        noise = _smooth_noise((FRAME_H, FRAME_W), p.noise_corr_px, rng)
        out[..., c] = img * p.tint_bgr[c] * (1.0 + p.noise_sigma * noise)
    if p.sharpen_amount > 0:
        for c in range(3):
            ch = out[..., c]
            out[..., c] = ch + p.sharpen_amount * (ch - cv2.GaussianBlur(ch, (0, 0), p.sharpen_sigma_px))
    return np.clip(out, 0, 255).astype(np.uint8)


# ── serving (frozen Stage 1 + Stage 2) ───────────────────────────────────────────────────────────────────────────

class _YoloCache:
    """Stage 2 constructs YOLO(weights) on every call; one page per call would reload it 3,000 times. Returning
    the same loaded model is behaviour-identical (inference only), so Stage 2's code path is unchanged."""

    def __init__(self, real: Callable[..., Any]) -> None:
        self.real = real
        self.models: dict[str, Any] = {}

    def __call__(self, weights: str) -> Any:
        if weights not in self.models:
            self.models[weights] = self.real(weights)
        return self.models[weights]


class _ArgSpy:
    """Records `_build_strip_source` arguments (for camera_page_stats) and passes the call through untouched."""

    def __init__(self, real: Callable[..., Any]) -> None:
        self.real = real
        self.args: tuple[Any, ...] | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.args = args
        return self.real(*args, **kwargs)


# ── registration and checks ──────────────────────────────────────────────────────────────────────────────────────

def register(ref: np.ndarray, tgt: np.ndarray) -> tuple[np.ndarray | None, int]:
    """ORB + RANSAC homography ref -> tgt (both grey). Returns (H or None, inliers)."""
    def small(img: np.ndarray) -> tuple[np.ndarray, float]:
        s = ORB_WORK_DIM / max(img.shape)
        return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), s

    a, sa = small(ref)
    b, sb = small(tgt)
    orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 10 or len(kb) < 10:
        return None, 0
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [m for m, n in (pair for pair in matches if len(pair) == 2) if m.distance < ORB_RATIO * n.distance]
    if len(good) < MIN_INLIERS:
        return None, len(good)
    pa = np.float32([ka[m.queryIdx].pt for m in good]) / sa
    pb = np.float32([kb[m.trainIdx].pt for m in good]) / sb
    H, inl = cv2.findHomography(pa, pb, cv2.RANSAC, RANSAC_REPROJ_PX / sb)
    n_in = int(inl.sum()) if inl is not None else 0
    if H is None or n_in < MIN_INLIERS:
        return None, n_in
    return H, n_in


def trackable_system_counts(job: PageJob) -> list[int]:
    """Numbers of leading systems Stage 2 may legitimately return for this page (see SHORT_SPAN_LO/HI).

    Empty when no system is wide enough to be tracked. If a narrow system is not the last one (never seen in the
    renders), only the full count is allowed, which is the strict rule.
    """
    page_sys = job.meta["page_systems"][job.page - 1]
    width = float(job.meta["png_width_px"])
    span: dict[int, float] = {}
    for b in job.meta["staff_boxes_px"]:
        if b["page"] == job.page:
            f = (b["right"] - b["left"]) / width
            span[b["system"]] = min(span.get(b["system"], f), f)
    fr = [span[sy] for sy in page_sys]
    lo, hi = SHORT_SPAN_LO, SHORT_SPAN_HI
    n_sure = sum(f >= hi for f in fr)
    n_maybe = sum(f >= lo for f in fr)
    if any(f < hi for f in fr[:n_sure]) or any(f >= lo for f in fr[n_maybe:]):
        return [len(fr)]
    if not s1.STAFF_MIN_SPAN_FRAC > lo:
        raise RuntimeError("SHORT_SPAN_LO must sit below Stage 1's STAFF_MIN_SPAN_FRAC")
    return [k for k in range(n_sure, n_maybe + 1) if k > 0]


def staff_centres(job: PageJob, render_w: int, pl: Placement) -> dict[tuple[int, str], tuple[float, float, float]]:
    """(system_on_page, staff_n) -> (left, right, centre_y) of the staff in canvas px."""
    k = render_w / float(job.meta["png_width_px"])
    boxes = job.meta["staff_boxes_px"]
    if isinstance(boxes, str):
        raise ValueError("staff_boxes_px stored as a string; re-render meta")
    page_sys = job.meta["page_systems"][job.page - 1]
    out: dict[tuple[int, str], tuple[float, float, float]] = {}
    for b in boxes:
        if b["page"] != job.page:
            continue
        sop = page_sys.index(b["system"])
        out[(sop, str(b["staff_n"]))] = (pl.page_x + k * b["left"], pl.page_x + k * b["right"],
                                         pl.page_y + k * (b["top"] + b["bottom"]) / 2)
    return out


def extract_features(svg: str, render_w: int, pl: Placement, staff_c: dict[tuple[int, str], tuple[float, float,
                     float]]) -> list[Feature]:
    """Dot/flag/tie components in canvas px, each assigned to the nearest staff (by centre y, inside its x span).

    A tie that crosses a system break is drawn as two halves, one per staff, so each half is checked on its own
    staff, which is the strip whose label carries it.
    """
    feats: list[Feature] = []
    kinds = feature_kinds(svg)
    for kind in FEATURE_CSS:
        if kind not in kinds:
            continue
        img = rasterise(svg, render_w, FEATURE_CSS[kind])
        n, lab, st, cen = cv2.connectedComponentsWithStats((img < INK_THRESHOLD).astype(np.uint8))
        for i in range(1, n):
            x, y, w, h, area = st[i]
            if area < FEATURE_MIN_PX:
                continue
            cx, cy = cen[i][0] + pl.page_x, cen[i][1] + pl.page_y
            best = min(((abs(cy - c[2]), key) for key, c in staff_c.items() if c[0] - 5 <= cx <= c[1] + 5),
                       default=None)
            if best is None:
                continue
            feats.append(Feature(kind=kind, system_on_page=best[1][0], staff_n=best[1][1],
                                 mask=lab[y:y + h, x:x + w] == i, x0=x + pl.page_x, y0=y + pl.page_y))
    return feats


def _box(r: int) -> np.ndarray:
    return np.ones((2 * r + 1, 2 * r + 1), np.uint8)


def _contrast_z(src_b: np.ndarray, core: np.ndarray, ring: np.ndarray, sigma_rel: float) -> float | None:
    """(ring paper median - mean of the darkest half of the core) / paper, in units of the paper noise.

    Why not `min` over the footprint against a p90 paper (the first version): both pick noise extremes, so a dot
    that had blurred into the paper still scored ~2.5-2.8 sigma (ml-cv-lead review R1). A median reference and a
    mean over half the core make the statistic centred near zero on blank paper; the pass threshold is then
    calibrated on the null placements below, not assumed.
    """
    cv_ = src_b[core]
    rv = src_b[ring]
    if cv_.size < FEATURE_MIN_PX or rv.size < RING_MIN_PX:
        return None
    paper = float(np.median(rv))
    dark = np.sort(cv_)[: max(1, int(round(CORE_DARK_FRACTION * cv_.size)))]
    return (paper - float(dark.mean())) / max(paper, 1.0) / max(sigma_rel, 1e-6)


def measure_features(feats: list[Feature], H: np.ndarray, ref_w: np.ndarray, ref_ink: np.ndarray,
                     gray: np.ndarray, source: np.ndarray, interline_native: float, k_box: float, sigma_rel: float,
                     staff_dy: dict[tuple[int, str], float], rng: np.random.Generator) -> list[dict[str, Any]]:
    """Contrast z of every dot/flag/tie in the actual strip source at strip scale, plus a null distribution.

    `ref_w` / `ref_ink`: the clean edited render warped into Stage 1's native page, and its ink mask. The strip
    source is box-blurred by k (native px per strip px) so the measurement sees what the 64 px strip keeps. Each
    feature is first moved by its staff's measured offset (Stage 2 box vs mapped render staff; the homography cannot
    model curl or the dewarp), then refined by template matching inside a small window with a uniqueness check
    (staff lines repeat every interline, so a weak second peak one line away must not win).

    The null: the same core/ring footprint placed at NULL_SAMPLES random ink-free spots near the feature. The
    pass threshold on z is chosen on the pooled null (false pass < 1%) in `report`, and applied in `manifest`, so
    the cut itself does not depend on it.
    """
    out: list[dict[str, Any]] = []
    gh, gw = gray.shape
    k = max(1, int(round(k_box)))
    src_b = cv2.blur(source.astype(np.float32), (k, k))
    half = int(round(REFINE_PATCH_SPACINGS * interline_native))
    sx = int(round(REFINE_SEARCH_X_SPACINGS * interline_native))
    sy = int(round(REFINE_SEARCH_Y_SPACINGS * interline_native))
    excl = max(1, int(round(REFINE_PEAK_EXCLUDE_SPACINGS * interline_native)))
    dil = max(1, int(round(OTHER_INK_DILATE_SPACINGS * interline_native)))
    r_in = max(1, int(round(RING_IN_SPACINGS * interline_native)))
    r_out = max(r_in + 1, int(round(RING_OUT_SPACINGS * interline_native)))
    null_reach = int(round(NULL_REACH_SPACINGS * interline_native))
    ink_any = cv2.dilate(ref_ink.astype(np.uint8), _box(dil)) > 0
    for f in feats:
        rec: dict[str, Any] = {"kind": f.kind, "system_on_page": f.system_on_page, "staff_n": f.staff_n}
        voice = VOICES[int(f.staff_n) - 1]
        ys, xs = np.nonzero(f.mask)
        pts = np.stack([xs + f.x0, ys + f.y0], 1).astype(np.float64).reshape(-1, 1, 2)
        q = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
        # q stays in the render (ref) frame: the template and the masks come from there. The staff offset only
        # moves the search window in the photo; the refined offset below is relative to it.
        sdy = int(round(staff_dy.get((f.system_on_page, voice), 0.0)))
        qx, qy = np.round(q[:, 0]).astype(int), np.round(q[:, 1]).astype(int)
        pad = half + max(sx, sy) + abs(sdy) + r_out + null_reach + 2
        bx0, by0 = int(qx.min()) - pad, int(qy.min()) - pad
        bx1, by1 = int(qx.max()) + pad + 1, int(qy.max()) + pad + 1
        if bx0 < 0 or by0 < 0 or bx1 > gw or by1 > gh:
            out.append({**rec, "z": None, "why": "outside_page"})
            continue
        fm = np.zeros((by1 - by0, bx1 - bx0), np.uint8)
        fm[qy - by0, qx - bx0] = 1
        fm = cv2.morphologyEx(fm, cv2.MORPH_CLOSE, _box(1)) > 0   # the warp is ~1:1; close rounding pinholes
        cy, cx = int(round(q[:, 1].mean())) - by0, int(round(q[:, 0].mean())) - bx0
        ref_loc = ref_w[by0:by1, bx0:bx1]
        tmpl = ref_loc[cy - half:cy + half + 1, cx - half:cx + half + 1]
        gy = by0 + cy + sdy
        area = gray[gy - half - sy:gy + half + sy + 1, bx0 + cx - half - sx:bx0 + cx + half + sx + 1]
        if float(tmpl.std()) < 1e-3:
            out.append({**rec, "z": None, "why": "flat_template"})
            continue
        res = cv2.matchTemplate(area, tmpl, cv2.TM_CCOEFF_NORMED)
        x_off = 0
        if f.kind in HORIZONTAL_KINDS:
            # A tie is wider than the patch, so inside it the patch is a horizontal band (tie + staff lines) and
            # the response is a ridge along x: every x scores the same, the square uniqueness margin is ~0 and
            # x carries no information. Only the vertical offset is searched (at dx = 0, the homography's x),
            # and uniqueness is judged against other rows, which is the ambiguity that matters (staff lines).
            res = res[:, sx:sx + 1]
            x_off = sx
        _, corr, _, loc = cv2.minMaxLoc(res)
        res2 = res.copy()
        res2[max(0, loc[1] - excl):loc[1] + excl + 1, max(0, loc[0] - excl):loc[0] + excl + 1] = -1.0
        second = float(res2.max())
        dx, dy = loc[0] + x_off - sx, loc[1] - sy
        rec.update({"corr": round(float(corr), 3), "corr_margin": round(float(corr) - second, 3), "dx": dx,
                    "dy": dy, "staff_dy": sdy})
        if corr < REFINE_MIN_CORR or corr - second < REFINE_MIN_MARGIN:
            out.append({**rec, "z": None, "why": "unregistered"})
            continue
        if abs(dy) >= sy or (f.kind not in HORIZONTAL_KINDS and abs(dx) >= sx):
            # A peak on the search border may be the shoulder of one outside it; the offset is not trusted.
            out.append({**rec, "z": None, "why": "unregistered_edge"})
            continue
        # Other ink = render ink that is not this feature; a flag is not credited with its stem, a tie not with
        # the staff lines it crosses. Everything is shifted by the refined (dx, dy) to where the content is.
        def shift(m: np.ndarray) -> np.ndarray:
            return np.roll(np.roll(m, sdy + dy, 0), dx, 1)

        fm_grown = cv2.dilate(fm.astype(np.uint8), _box(1)) > 0
        other = shift(ref_ink[by0:by1, bx0:bx1] & ~fm_grown)
        fm = shift(fm)
        core = fm & ~(cv2.dilate(other.astype(np.uint8), _box(dil)) > 0)
        occluded = int(core.sum()) < FEATURE_MIN_PX
        if occluded:
            core = fm
        allink = shift(ink_any[by0:by1, bx0:bx1]) | fm
        fm8 = fm.astype(np.uint8)
        ring = (cv2.dilate(fm8, _box(r_out)) > 0) & ~(cv2.dilate(fm8, _box(r_in)) > 0) & ~allink
        sb = src_b[by0:by1, bx0:bx1]
        z = _contrast_z(sb, core, ring, sigma_rel)
        # Null placements: same core/ring shape on blank paper nearby (no render ink under core or ring).
        nulls: list[float] = []
        cy_, cx_ = np.nonzero(core)
        ry_, rx_ = np.nonzero(ring)
        for _ in range(NULL_TRIES):
            if len(nulls) >= NULL_SAMPLES:
                break
            oy, ox = (int(v) for v in rng.integers(-null_reach, null_reach + 1, 2))
            if abs(oy) < r_out and abs(ox) < r_out:
                continue
            ny, nx = cy_ + oy, cx_ + ox
            my, mx = ry_ + oy, rx_ + ox
            if (ny.min() < 0 or nx.min() < 0 or ny.max() >= sb.shape[0] or nx.max() >= sb.shape[1]
                    or my.min() < 0 or mx.min() < 0 or my.max() >= sb.shape[0] or mx.max() >= sb.shape[1]):
                continue
            if allink[ny, nx].any() or allink[my, mx].any():
                continue
            nc = np.zeros_like(core)
            nc[ny, nx] = True
            nr = np.zeros_like(ring)
            nr[my, mx] = True
            zn = _contrast_z(sb, nc, nr, sigma_rel)
            if zn is not None:
                nulls.append(round(zn, 3))
        out.append({**rec, "z": None if z is None else round(z, 3), "why": None if z is not None else "no_ring",
                    "occluded": occluded, "core_px": int(core.sum()), "ring_px": int(ring.sum()),
                    "null_z": nulls})
    return out


def paper_noise(source: np.ndarray, gray: np.ndarray, ref_ink_w: np.ndarray, interline_native: float,
                k_box: float) -> float:
    """Relative paper noise of the strip source at strip scale (blank paper only, filled regions excluded)."""
    k = max(1, int(round(k_box)))
    sb = cv2.blur(source.astype(np.float32), (k, k))
    hp = sb - cv2.GaussianBlur(sb, (0, 0), NOISE_HP_SPACINGS * interline_native)
    d = max(1, int(round(NOISE_INK_EXCLUDE_SPACINGS * interline_native)))
    ink = cv2.dilate(ref_ink_w.astype(np.uint8), np.ones((2 * d + 1, 2 * d + 1), np.uint8)) > 0
    filled = cv2.dilate((source != gray).astype(np.uint8), np.ones((2 * d + 1, 2 * d + 1), np.uint8)) > 0
    sel = ~ink & ~filled & (gray > 0)
    if sel.sum() < 1000:
        raise ValueError("too little clean paper to measure noise")
    v = hp[sel]
    mad = float(np.median(np.abs(v - np.median(v))))
    return 1.4826 * mad / max(float(np.median(sb[sel])), 1.0)


# ── one page ─────────────────────────────────────────────────────────────────────────────────────────────────────

def process_page(job: PageJob, out: Path, yolo: Path, keep_photo: bool, want_stats: bool,
                 spy: _ArgSpy | None, variant: int) -> PageResult:
    t0 = time.perf_counter()
    seed = page_seed(job.font, job.piece, job.page, variant)
    tag = f"p{job.page}_v{variant}"
    rng = np.random.default_rng(seed)
    svg_text = job.svg.read_text(encoding="utf-8")
    geom = page_geometry(ET.fromstring(svg_text))
    interline_frac = SVG_INTERLINE_UNITS * geom.scale / geom.width_px
    p = sample_params(rng, seed, interline_frac)
    p.variant = variant

    labels = {(r["system_on_page"], r["voice"]): r for r in job.labels}
    allowed_systems = trackable_system_counts(job)
    if not allowed_systems:
        # Nothing on the page is wide enough for Stage 1 to track; skipped before the expensive part.
        return PageResult(job.key, "dropped", "short_systems_only", time.perf_counter() - t0,
                          {"seed": seed, "variant": variant})

    # Placement (content = all staves of the page); shrink the interline if the staves cannot fit.
    pl = fit_placement(job, p, geom, interline_frac, rng)
    params = dataclasses.asdict(p)
    if pl is None:
        return PageResult(job.key, "dropped", "no_fit", time.perf_counter() - t0, params)

    edited = edit_svg(svg_text, p)
    render = rasterise(edited, p.render_width_px)
    photo = synthesize(render, pl, p, rng)
    photo_dir = out / "photos" / job.font / job.piece
    photo_dir.mkdir(parents=True, exist_ok=True)
    photo_path = photo_dir / f"{tag}.jpg"
    if not cv2.imwrite(str(photo_path), photo, [cv2.IMWRITE_JPEG_QUALITY, p.jpeg_q]):
        raise OSError(f"could not write {photo_path}")
    del photo

    def done(status: str, reason: str | None, **kw: Any) -> PageResult:
        if not keep_photo:
            photo_path.unlink(missing_ok=True)
        return PageResult(job.key, status, reason, time.perf_counter() - t0, params, **kw)

    # Serving: frozen Stage 1 (keep_unmasked as serving does with ClefKeyNet on; it only adds return fields).
    if spy is not None:
        spy.args = None  # the spy lives per worker; stale args would report the previous page's stats
    try:
        page = s1.preprocess_score_page(str(photo_path), save_debug=False, keep_unmasked=True)
    except (ValueError, cv2.error, IndexError) as e:
        return done("dropped", f"stage1_error:{type(e).__name__}:{e}")
    if page.strip_source is None or page.strip_gray is None:
        return done("dropped", "no_strip_source")
    stats = None
    if want_stats and spy is not None and spy.args is not None:
        from camera_page_stats import page_stats  # noqa: PLC0415  (smoke-only dependency)
        stats = page_stats(spy.args, [b.spacing for b in spy.args[4]])
    tmp = out / "tmp"
    try:
        voices = s2.detect_staff_regions([(page.detect, 1, page.strip_source)], model_weights=str(yolo),
                                         output_dir=str(tmp), save_strips=False,
                                         manifest_path=str(tmp / "manifest.json"))
    except ValueError as e:
        return done("dropped", f"stage2_error:{e}", stats=stats)
    s2_manifest = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
    n_found = len(s2_manifest)
    if n_found not in {k * STAFFS_PER_SYSTEM for k in allowed_systems}:
        want = "|".join(str(k * STAFFS_PER_SYSTEM) for k in allowed_systems)
        return done("dropped", f"staff_count:{n_found}!={want}", stats=stats)
    n_found_sys = n_found // STAFFS_PER_SYSTEM

    # Render -> Stage 1 page registration, to verify every box is the staff the label belongs to.
    ref_canvas = np.full((pl.canvas_h, pl.canvas_w), 255, np.uint8)
    ref_canvas[pl.page_y:pl.page_y + render.shape[0], pl.page_x:pl.page_x + render.shape[1]] = render
    H, n_in = register(ref_canvas, page.strip_gray)
    if H is None:
        return done("dropped", f"registration_failed:{n_in}", stats=stats)
    staff_c = staff_centres(job, p.render_width_px, pl)
    src_h, src_w = page.strip_source.shape[:2]
    det_h = page.detect.shape[0]
    to_det = det_h / src_h
    scale_native = math.sqrt(abs(np.linalg.det(H[:2, :2]))) if H is not None else 1.0
    interline_native = p.interline_px * scale_native
    # Each Stage 2 box must sit nearest to the render staff its (system, voice) names, and close to it. The
    # registration is a homography, so curl and the Stage 1 dewarp leave a residual of up to about one interline;
    # a wrong assignment is off by a whole staff gap (>= ~6 interlines), so the tolerance separates the two.
    mapped: dict[tuple[int, str], float] = {}
    for (sop, staff_n), (left, right, cy) in staff_c.items():
        voice = VOICES[int(staff_n) - 1]
        pts = cv2.perspectiveTransform(np.array([[[left, cy]], [[right, cy]], [[(left + right) / 2, cy]]],
                                                np.float64), H).reshape(-1, 2)
        if pts[:, 0].min() < 0 or pts[:, 0].max() > src_w:
            return done("dropped", f"staff_truncated:{sop}:{voice}", stats=stats)
        mapped[(sop, voice)] = float(pts[2, 1]) * to_det
    tol = STAFF_MATCH_MAX_SPACINGS * interline_native * to_det
    offsets: list[float] = []
    staff_dy: dict[tuple[int, str], float] = {}
    margins: dict[tuple[int, str], float] = {}
    il_det = interline_native * to_det
    for m in s2_manifest:
        key = (m["system"] - 1, m["voice"])
        box_cy = (m["box"]["y1"] + m["box"]["y2"]) / 2
        nearest = min(mapped, key=lambda k: abs(mapped[k] - box_cy))
        d = box_cy - mapped.get(key, math.inf)
        if nearest != key or abs(d) > tol:
            return done("dropped", f"staff_mismatch:{key[0]}:{key[1]}:nearest={nearest}:d={d:.1f}px_det",
                        stats=stats)
        # Identity margin (ruling e): how much closer the box is to its own staff than to any other. A box that
        # is nearest by less than IDENTITY_MARGIN_MIN_SPACINGS could be the neighbour, so its strip is not kept.
        others = [abs(mapped[k] - box_cy) for k in mapped if k != key]
        margins[key] = (min(others) - abs(d)) / il_det if others else math.inf
        offsets.append(d / il_det)
        staff_dy[key] = d / to_det

    strips = {(s_idx - 1, voice): arr for voice, seq in voices.items() for arr, _, s_idx, _, _ in seq}
    k_box = float(np.median([src_w / a.shape[1] for a in strips.values()]))
    ref_w = cv2.warpPerspective(ref_canvas, H, (src_w, src_h), flags=cv2.INTER_LINEAR, borderValue=255)
    ref_ink_w = ref_w < INK_THRESHOLD
    try:
        sigma_rel = paper_noise(page.strip_source, page.strip_gray, ref_ink_w, interline_native, k_box)
    except ValueError as e:
        return done("dropped", f"noise_unmeasurable:{e}", stats=stats)
    feats = extract_features(edited, p.render_width_px, pl, staff_c)
    fres = measure_features(feats, H, ref_w, ref_ink_w, page.strip_gray, page.strip_source, interline_native,
                            k_box, sigma_rel, staff_dy, np.random.default_rng([seed, NULL_RNG_STREAM]))

    sdir = out / "strips" / job.font / job.piece
    sdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for (sop, voice), lab in sorted(labels.items(), key=lambda kv: (kv[0][0], VOICES.index(kv[0][1]))):
        if sop >= n_found_sys and lab["quarantine"] is None:
            rows.append({"page": job.page, "system_on_page": sop, "voice": voice, "system": lab["system"],
                         "status": "dropped", "reason": "short_system_untracked"})
    for (sop, voice), arr in sorted(strips.items(), key=lambda kv: (kv[0][0], VOICES.index(kv[0][1]))):
        lab = labels.get((sop, voice))
        row: dict[str, Any] = {"page": job.page, "system_on_page": sop, "voice": voice,
                               "strip_w": int(arr.shape[1]), "k_box": round(src_w / arr.shape[1], 3)}
        if lab is None:
            rows.append({**row, "status": "dropped", "reason": "no_label"})
            continue
        row["system"] = lab["system"]
        if lab["quarantine"] is not None:
            rows.append({**row, "status": "dropped", "reason": f"quarantine:{lab['quarantine']}"})
            continue
        row["identity_margin_il"] = round(margins[(sop, voice)], 3)
        if margins[(sop, voice)] < IDENTITY_MARGIN_MIN_SPACINGS:
            rows.append({**row, "status": "dropped", "reason": "identity_margin"})
            continue
        staff_n = str(VOICES.index(voice) + 1)
        # Every labelled strip is written; whether its dots/flags/ties survived is decided in `manifest` with
        # the threshold calibrated on the null, so recalibrating never needs a re-cut.
        row["features"] = [f for f in fres if f["system_on_page"] == sop and f["staff_n"] == staff_n]
        name = f"{tag}_s{sop}_{voice}.png"
        # Stage 2 returns the grey strip as 3 equal BGR channels; one channel is lossless.
        if not cv2.imwrite(str(sdir / name), arr[..., 0] if arr.ndim == 3 else arr):
            raise OSError(f"could not write {sdir / name}")
        rows.append({**row, "status": "cut", "reason": None,
                     "path": f"strips/{job.font}/{job.piece}/{name}", "tokens": lab["tokens"]})
    return done("ok", None, strips=rows,
                stats={**(stats or {}), "sigma_rel_strip": round(sigma_rel, 5), "inliers": n_in,
                       "interline_native": round(interline_native, 2), "k_box": round(k_box, 3),
                       "staff_offset_spacings_maxabs": round(max(abs(o) for o in offsets), 3),
                       "identity_margin_min_il": round(min(margins.values()), 3)})


# ── driver ───────────────────────────────────────────────────────────────────────────────────────────────────────

def result_path(out: Path, job: PageJob, variant: int) -> Path:
    return out / "pages" / job.font / job.piece / f"p{job.page}_v{variant}.json"


def select_smoke(jobs: list[PageJob], n: int) -> list[PageJob]:
    """n pages spread over all fonts and scales, deterministic."""
    rng = np.random.default_rng(BASE_SEED)
    by_font: dict[str, list[PageJob]] = {}
    for j in jobs:
        by_font.setdefault(j.font, []).append(j)
    picked: list[PageJob] = []
    per = max(1, n // max(len(by_font), 1))
    for font in sorted(by_font):
        idx = rng.choice(len(by_font[font]), size=min(per, len(by_font[font])), replace=False)
        picked += [by_font[font][i] for i in sorted(idx)]
    return picked


def smoke_plan(jobs: list[PageJob], n: int) -> dict[str, dict[str, int]]:
    """Per font: pages select_smoke aims for (n split evenly) and pages available, so shortfalls are visible."""
    avail = collections.Counter(j.font for j in jobs)
    per = max(1, n // max(len(avail), 1))
    return {font: {"planned": per, "available": avail[font], "picked": min(per, avail[font])}
            for font in sorted(avail)}


def round_robin_by_font(jobs: list[PageJob]) -> list[PageJob]:
    """Interleaves pages font by font (order within a font kept), so a stopped or partial run covers every font.

    Why (recal2, 2026-10-01): select_smoke returns pages grouped by font, and the stopped bach_smoke100c covered
    only 3 of 5 fonts. Only the order changes; the pages and their seeds (page_seed) are the same.
    """
    by_font: dict[str, list[PageJob]] = {}
    for j in jobs:
        by_font.setdefault(j.font, []).append(j)
    queues = [by_font[f] for f in sorted(by_font)]
    out: list[PageJob] = []
    for i in range(max((len(q) for q in queues), default=0)):
        out += [q[i] for q in queues if i < len(q)]
    return out


def require_camera_fwhm_method(camera: Path) -> None:
    """Refuses camera stats measured with a different line-FWHM method than the augmented pages (amendment (a))."""
    from camera_page_stats import FWHM_METHOD  # noqa: PLC0415  (keeps the smoke-only dependency local)
    got = json.loads(camera.read_text(encoding="utf-8")).get("fwhm_method")
    if got != FWHM_METHOD:
        raise SystemExit(f"{camera} has fwhm_method={got!r}, need {FWHM_METHOD!r}: recompute it with "
                         "camera_page_stats.py (see its module docstring) before a smoke run or report.")


# ── page worker (recal2 memory handling) ─────────────────────────────────────────────────────────────────────────
# Pages run in a spawned worker that is replaced after WORKER_MAX_TASKS pages: long single-process runs grew in
# memory (2026-10-01). RSS is logged per page so the worker count is raised only on evidence (ml-cv-lead: 2 workers
# only if peak RSS < 3 GB).
WORKER_MAX_TASKS = 8
DEFAULT_WORKERS = 1
BYTES_PER_MB = 1024 * 1024
_WORKER_SPY: _ArgSpy | None = None


def _worker_init(want_stats: bool) -> None:
    """Per-process setup: one cached YOLO per worker and, for --stats, the strip-source spy."""
    global _WORKER_SPY
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    s2.YOLO = _YoloCache(s2.YOLO)  # type: ignore[attr-defined]
    _WORKER_SPY = _ArgSpy(s1._build_strip_source) if want_stats else None
    if _WORKER_SPY is not None:
        s1._build_strip_source = _WORKER_SPY  # type: ignore[assignment]


def _run_page(job: PageJob, out: Path, yolo: Path, keep_photos: bool, want_stats: bool, variant: int,
              rp: Path) -> tuple[str, str | None, int, float, float | None]:
    """Processes one page in the worker and writes its result JSON atomically (resume never sees a partial file).

    Returns:
        (status, reason, strips kept, seconds, RSS MB) for the parent's progress line.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):   # Stage 1/2 print per-box debug lines
        res = process_page(job, out, yolo, keep_photos, want_stats, _WORKER_SPY, variant)
    gc.collect()
    mem = psutil.Process().memory_info()
    res.rss_mb = round(mem.rss / BYTES_PER_MB, 1)
    peak = getattr(mem, "peak_wset", None)
    res.peak_rss_mb = round(peak / BYTES_PER_MB, 1) if peak is not None else None
    rp.parent.mkdir(parents=True, exist_ok=True)
    tmp = rp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dataclasses.asdict(res), indent=1), encoding="utf-8")
    tmp.replace(rp)
    kept = sum(1 for r in res.strips if r["status"] == "cut")
    return res.status, res.reason, kept, res.seconds, res.rss_mb


def cmd_run(a: argparse.Namespace) -> None:
    head = check_frozen_code()
    if a.workers < 1:
        raise SystemExit("--workers must be >= 1")
    if a.stats:
        require_camera_fwhm_method(a.camera)
    out: Path = a.out
    out.mkdir(parents=True, exist_ok=True)
    jobs = load_jobs(a.renders, a.prefix)
    conv_sha = sha256_file(CONVERTER)
    stale = sorted({j.piece for j in jobs if j.meta["converter_sha256"] != conv_sha})
    if stale:
        log.warning("%d pieces were labelled by a different converter sha than the current file", len(stale))
    plan: dict[str, dict[str, int]] | None = None
    if a.smoke:
        plan = smoke_plan(jobs, a.smoke)
        short = [f for f, v in plan.items() if v["picked"] < v["planned"]]
        if short:
            log.warning("fonts with fewer pages than planned: %s", short)
        jobs = round_robin_by_font(select_smoke(jobs, a.smoke))
    if a.limit:
        jobs = jobs[:a.limit]
    run_info = {"stage12_frozen_commit": FROZEN_COMMIT, "git_head": head, "converter_sha256_now": conv_sha,
                "pieces_with_other_converter_sha": stale, "yolo": str(a.yolo),
                "yolo_sha256": sha256_file(a.yolo), "base_seed": BASE_SEED, "split_seed": SPLIT_SEED,
                "cut_corpus_sha256": sha256_file(Path(__file__)),
                "camera_page_stats_py_sha256": sha256_file(Path(__file__).with_name("camera_page_stats.py")),
                "camera_stats": str(a.camera), "camera_stats_sha256": sha256_file(a.camera),
                "smoke_plan": plan, "job_order": "round_robin_by_font" if a.smoke else "load_order",
                "workers": a.workers, "worker_max_tasks": WORKER_MAX_TASKS}
    (out / "run_info.json").write_text(json.dumps(run_info, indent=1), encoding="utf-8")
    pending: collections.deque[tuple[int, PageJob, Path]] = collections.deque()
    for i, job in enumerate(jobs):
        rp = result_path(out, job, a.variant)
        if rp.exists() and not a.force:
            continue
        pending.append((i, job, rp))
    skipped = len(jobs) - len(pending)
    t_start = time.perf_counter()
    done_n = 0
    budget_hit = False
    # Bounded submission (at most `workers` pages in flight) so the time budget is checked before each page as in
    # the old single-process loop; Pool.imap would queue every page at once.
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(a.workers, initializer=_worker_init, initargs=(a.stats,),
                  maxtasksperchild=WORKER_MAX_TASKS) as pool:
        inflight: collections.deque[tuple[int, PageJob, AsyncResult[Any]]] = collections.deque()
        while pending or inflight:
            while pending and len(inflight) < a.workers and not budget_hit:
                if a.max_minutes and (time.perf_counter() - t_start) / 60 > a.max_minutes:
                    log.info("time budget reached after %d pages", done_n)
                    budget_hit = True
                    break
                i, job, rp = pending.popleft()
                inflight.append((i, job, pool.apply_async(
                    _run_page, (job, out, a.yolo, a.keep_photos, a.stats, a.variant, rp))))
            if not inflight:
                break
            i, job, ar = inflight.popleft()
            status, reason, kept, secs, rss = ar.get()
            done_n += 1
            print(f"[{i + 1}/{len(jobs)}] {job.key} {status} {reason or ''} kept={kept} {secs:.1f}s rss={rss}MB",
                  flush=True)
    print(f"done {done_n}, skipped existing {skipped}, total {len(jobs)}", flush=True)


def group_split(groups_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """piece -> group, piece -> split. Whole groups go to val (seeded order) until VAL_FRACTION of pieces."""
    g = json.loads(groups_path.read_text(encoding="utf-8"))
    piece_group: dict[str, str] = g["piece_group"]
    groups: dict[str, list[str]] = {}
    for piece, grp in piece_group.items():
        groups.setdefault(grp, []).append(piece)
    order = sorted(groups, key=lambda k: hashlib.sha256(f"{SPLIT_SEED}|{k}".encode()).hexdigest())
    target = VAL_FRACTION * len(piece_group)
    val: set[str] = set()
    for grp in order:
        if len(val) >= target:
            break
        val.update(groups[grp])
    return piece_group, {p: ("val" if p in val else "train") for p in piece_group}


def load_results(out: Path) -> list[tuple[str, str, dict[str, Any]]]:
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for rp in sorted((out / "pages").glob("*/*/p*_v*.json")):
        rows.append((rp.parent.parent.name, rp.parent.name, json.loads(rp.read_text(encoding="utf-8"))))
    return rows


def strip_verdict(strip: dict[str, Any], thresholds: dict[str, float]) -> str | None:
    """None when every drawn dot/flag/tie on the strip survived, else the drop reason."""
    for f in strip.get("features", []):
        if f["z"] is None:
            return f"{f['kind']}_{f['why']}"
        if f["z"] <= thresholds[f["kind"]]:
            return f"{f['kind']}_erased"
    return None


def cmd_manifest(a: argparse.Namespace) -> None:
    out: Path = a.out
    piece_group, split = group_split(a.groups)
    thresholds: dict[str, float] = json.loads(a.thresholds.read_text(encoding="utf-8"))["thresholds"]
    run_info = json.loads((out / "run_info.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    drops: dict[str, int] = {}
    page_status: dict[str, int] = {}
    secs: list[float] = []
    for font, piece, res in load_results(out):
        meta = json.loads((a.renders / font / piece / "meta.json").read_text(encoding="utf-8"))
        if piece not in split:
            raise SystemExit(f"{piece} has no split group in {a.groups}")
        secs.append(res["seconds"])
        page_status[res["status"]] = page_status.get(res["status"], 0) + 1
        if res["status"] != "ok":
            reason = res["reason"].split(":")[0]
            drops[f"page:{reason}"] = drops.get(f"page:{reason}", 0) + 1
            continue
        for s in res["strips"]:
            reason = s["reason"].split(":")[0] if s["status"] != "cut" else strip_verdict(s, thresholds)
            if reason is not None:
                drops[f"strip:{reason}"] = drops.get(f"strip:{reason}", 0) + 1
                continue
            rows.append({"path": s["path"], "tokens": s["tokens"], "font": font, "piece": piece,
                         "page": s["page"], "variant": res["params"].get("variant", 0), "system": s["system"],
                         "voice": s["voice"], "melody_group": piece_group[piece], "split": split[piece],
                         "aug": res["params"], "stage12_commit": run_info["stage12_frozen_commit"],
                         "git_head": run_info["git_head"], "converter_sha256": meta["converter_sha256"],
                         "converter_sha256_matches_file": meta["converter_sha256"] == run_info["converter_sha256_now"],
                         "survival_thresholds": thresholds})
    with (out / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    summary = {"strips_kept": len(rows), "pages": page_status, "drops": dict(sorted(drops.items())),
               "split_strips": {s: sum(1 for r in rows if r["split"] == s) for s in ("train", "val")},
               "split_pieces": {s: len({r["piece"] for r in rows if r["split"] == s}) for s in ("train", "val")},
               "split_groups": {s: len({r["melody_group"] for r in rows if r["split"] == s}) for s in ("train", "val")},
               "seconds_per_page_median": float(np.median(secs)) if secs else None,
               "seconds_per_page_mean": float(np.mean(secs)) if secs else None}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


# ── smoke report (ml-cv-lead review R1, R3, R4) ──────────────────────────────────────────────────────────────────
# Pre-registered 2026-10-01, written before the >=50-page smoke was looked at:
# * COVER: for each statistic the augmented p5..p95 must reach the camera p5..p95 (each bound may miss by
#   COVER_TOL relative). The plan wants the camera range spanned, with extra on the low-contrast side.
# * LOW TAIL: the share of augmented staves below the camera p5 of line depth and of head depth must lie in
#   LOW_SHARE_BAND: weighted toward low contrast, but not dominated by a regime under 5% of real pages.
# * DROPS: page drop rate <= PAGE_DROP_MAX; feature-survival strip drops <= FEATURE_DROP_MAX of cut strips.
# * BIAS: kept/all frequency of dotted and tied strips within BIAS_BAND (R4); a larger skew means cut more
#   variants of the low-contrast pages, not loosen the rule.
# * STAFF OFFSET: p99 of the per-page max |box - mapped staff| below STAFF_OFFSET_P99_MAX interline.
#
# Amendment 2026-10-01 (ml-cv-lead review of the recalibration; thresholds above unchanged, never loosened):
# * DROPS denominator (patch 9, GO): the page-drop check counts photographed pages; pages skipped before any photo
#   (every system too short to track) were in the denominator before. Old value (all pages) is reported beside it,
#   and drops are split into structural skips, structural-band failures (no_strip_source on pages whose systems
#   are all in the uncertain SHORT_SPAN band) and augmentation-induced drops.
# * STAFF OFFSET is replaced as the gate by (1) the identity margin: every kept box at least
#   IDENTITY_MARGIN_MIN_SPACINGS closer to its own mapped staff than to any other (checked per box in
#   process_page), and (2) registration failures: the share of drawn features whose template peak hit the search
#   edge or fell below the correlation/uniqueness floor must be <= FEATURE_DROP_MAX. The old offset statistic is
#   still reported (p50, p99 and max) beside the new checks, with its old pass/fail.
# * Added, stricter calibration checks (ruling c-d): shares of staves at/above camera p50 (line depth, line/head
#   ratio >= 0.25; head depth >= 0.30), noise share above camera p95 <= 0.15 and p50 inside camera p25-p75, FWHM
#   share above camera p95 in 0.05-0.20, paper grey / illumination (paper-only mask) p50 inside camera p25-p75,
#   no drop_by_param tertile above 2x the overall rate.
#
# Amendment 2026-10-01, recal2 (ml-cv-lead spec after bach_smoke100c; frozen before bach_smoke100d is run; no
# existing threshold loosened):
# * (a) Line FWHM is sub-pixel (linear interpolation of the half-max crossings, camera_page_stats.FWHM_METHOD) for
#   camera and augmented pages alike; camera_page_stats.json is recomputed with it. FWHM thresholds unchanged.
# * New check, framing: augmented paper_area_frac p50 >= PAPER_AREA_P50_MIN and the share of pages below
#   PAPER_AREA_LOW <= PAPER_AREA_LOW_SHARE_MAX (camera p50 1.00; the 100c partial had aug p50 0.90).
# * Framing ruling, option 2 (ml-cv-lead, 2026-10-01, after the dry check showed fill mode failing every short
#   page): fill mode draws the content's vertical position from the content-fit / coverage interval, and falls back
#   to standard framing after FIT_MAX_ATTEMPTS. New checks: fill->standard fallback <= FILL_FALLBACK_MAX of
#   fill-requested pages, and framing bias: the share of single-system and of final-system pages among
#   standard-framed pages <= FRAMING_BIAS_MAX_RATIO x their share among all photographed pages. Paper-area checks
#   above stand and are measured on the Stage 1 paper mask.
# * (b) drop_by_param: a tertile's ratio to the overall drop rate is evaluated only when the tertile holds
#   >= DROP_RATIO_MIN_EVENTS drop events of that kind (one or two drops in ~40 pages made 2x noise); 2x stands.
#   Every ratio is still reported, with whether it was evaluated.
# * (c) Page-bootstrap 95% CIs (page = unit of independence; within-page correlation ~0.99) are reported next to
#   every stave-level share (and the page-level ones). The decision uses the point estimates.
# * Flags (reported, not checks): fonts with fewer pages than planned (the gate needs all 5 fonts); camera p95 rests
#   on 25 pages. If this smoke fails, stop and escalate (last attempt under this gate).
#
# Amendment 2026-10-02, recal3 (ml-cv-lead verdict on bach_smoke100d, 26/29; user approval 2026-10-02; written and
# frozen before bach_smoke100e is run; no threshold changed):
# * drop_by_param (user-adopted rule): a page-level ratio counts only augmentation-induced page drops, over the
#   photographed pages that are not structural-band failures; structural skips (short_systems_only) and
#   structural-band failures (no_strip_source on band-only pages) are excluded from numerator and denominator.
#   This writes down what the recal2 code already computed (100d's 2.45x was 4 of the 5 augmentation-induced drops
#   in one line_mult tertile), so it does not change the 100d verdict. DROP_RATIO_MIN_EVENTS (3) and the 2x limit
#   stand; strip-level feature-drop ratios are unchanged.
# * Parameters (tuned on seed 20261002's outcome, so this smoke uses BASE_SEED 20261004): ILLUM_LOW_P 0.05,
#   ILLUM_LOW (0.70, 0.75), ILLUM_HIGH (0.75, 0.83), SHADOW_P 0.08, shadow cover share 0.05-0.15 of the frame,
#   NOISE_SIGMA (0.0185, 0.0205). SHARPEN_* untouched. ILLUM and NOISE were moved 0.01 / 0.0005 down from the first
#   recal3 draft on ml-cv-lead's pre-run review (resampled 100d residuals; projections, not measurements).
# * Amendment C (ml-cv-lead pre-run review; PROPOSED, gate status pending the user's ruling, which must be recorded
#   here before the 100e report is read): under random drop placement over ~98 pages, the page-level 2x check
#   fails by chance 58% (3 events), 95% (4), 65% (5), 63% (6), 31% (8) of the time, so as specified it cannot
#   discriminate. Proposed rule: a page-level cell fails only with ratio > 2x, >= DROP_RATIO_MIN_EVENTS events and
#   a max-statistic permutation p < DROP_PERM_ALPHA (DROP_PERM_REPS permutations of the drop labels over the
#   augmentation pool, fixed seed, max over 8 params x 3 tertiles). 2x and 3 are unchanged; strip-level ratios keep
#   the plain 2x rule and remain the real per-parameter sensitivity monitor. With ~5 events the page-level check
#   then guards only against large concentrations. Superseded by C' below before any 100e result was seen;
#   still reported (drop_by_param_reported_only.amendment_C).
# * Amendment C' (ml-cv-lead analysis 2026-10-02, simulated on 100d's real parameter draws; ADOPTED by the user
#   2026-10-02 before `report` was run on bach_smoke100e). Why: the legacy rule false-fails 60/96/68/63/33% of
#   harmless smokes at 3/4/5/6/8 drop events (24 cells, tiny counts), and its strip arm 21.6% (strip outcomes
#   cluster within pages); C fixed the page arm's false alarms but has ~36% power against the harm that matters
#   most (one end of a parameter range wiped out) and left the strip arm noisy. The fix targets a 5% family-wise
#   error, keeps 2x and >= 3 events as the minimum effect size, and was triggered by 100d (100d still fails
#   iqr:noise_rel and paper_area_low_share, so it does not rescue 100d). checks.drop_by_param_cprime replaces
#   checks.drop_by_param_2x as the gate; the legacy check and C stay reported beside it.
#   - R1 page arm: over aug_pool pages carrying every BIAS_PARAMS value, mid-rank each parameter; z_j is the
#     standardised rank sum of the k dropped pages, T = max_j |z_j|; p from DROP_RANK_REPS label permutations
#     (seed DROP_RANK_SEED). Fails iff p < DROP_PERM_ALPHA and j* = argmax |z_j| has an evaluated tertile
#     (>= DROP_RATIO_MIN_EVENTS events) with ratio > TERTILE_DROP_MAX_RATIO. k < 3: passes, flagged unevaluable.
#   - R2 strip arm: fails iff the worst evaluated strip feature-drop ratio > 2x (>= 3 events) and its family-wise
#     p < 0.05, the null shuffling whole pages' (strips_cut, feature_strip_drops) pairs over the ok pages
#     (DROP_STRIP_PERM_REPS, seed DROP_STRIP_PERM_SEED; tertile edges from aug_pool).
#   - R3 confirmatory (one pre-specified cell, no multiplicity correction): the CONFIRM_PARAM lowest-tertile strip
#     feature-drop ratio, one-sided p from the same page shuffle (CONFIRM_REPS, seed CONFIRM_SEED). Confirmed iff
#     p < 0.05 and ratio > 2.0; confirmed fails drop_by_param, and the line_ink lower bound is then reviewed in a
#     new amendment before any full run. 100d's own numbers are not evidence for it (it is where the lead came
#     from); estimated replication power if real <= ~57% (winner's curse).
#   - R4 full-run audit (written now, run after the full Bach run): R1-R3 on the full corpus (~160 drops, power
#     ~1 for a 3x tertile). Remedy fixed now: a failing cell triggers a stratified top-up of new-variant renders
#     drawn inside the depleted parameter range until that cell's retention >= 0.95 of overall; inverse-retention
#     sample weights are the fallback.
#   - Every drop_by_param cell also reports retention = (1 - cell rate) / (1 - overall rate). The report records
#     its own code sha256 (report_code_sha256), since run_info.cut_corpus_sha256 is the run-time code.
#   - Power is simulated on 100d's parameter distribution; recal3 changes illumination/shadow/noise, so 100e's drop
#     count is unknown. R1/R2 are calibrated at any k; the legacy rule is not.
# * Report-only additions: illumination x shadow strata (paper area, noise) and dotted/tied bias per line_ink
#   tertile. The per-page stats spy is reset before each page.
#
# Result 2026-10-02, bach_smoke100e (seed 20261004): FAIL, 24/29. Passed: iqr:noise_rel, paper_area_low_share,
# drop_by_param_cprime (R1 k=3 p 0.456, R2 p 0.672, R3 line_ink not confirmed: ratio 1.27, p 0.242). Failed:
# iqr:paper_grey (p50 227 vs camera IQR), cover:paper_grey (none below camera p5), noise_above_p95 0.164,
# fwhm_above_p95 0.044, line_mult_survival_2x 2.24. ml-cv-lead post-results review: paper grey is a real miss (the
# camera dark tail, 3/25 pages, is global exposure; the generator darkens paper only through the illum field, and
# 100d passed only through the unrealistic deep-illum pages that recal3 removed); noise sits at the limit (bootstrap
# P(>0.15) 0.63) with a real two-sided spread driven by sharpen_amount; fwhm_above_p95 and line_mult_survival_2x are
# chance (false-fail ~0.39 each; the latter has no minimum event count). This was the last attempt under this gate:
# stopped. User decision 2026-10-02: option A, i.e. a gate v2 and recal4 written and frozen together before any
# further run, one attempt on a fresh seed; recal4 adds a global exposure term calibrated on the camera pages only;
# gate v2 gives line_mult_survival the C' treatment and decides noise/fwhm above-p95 on a page-bootstrap CI whose
# settings are fixed by simulation on pooled 100d+100e pages before the run (the user signed off that this CI rule
# loosens the decision rule, not any threshold). v2 is never applied to 100e's verdict (100e still fails paper grey
# under it).
# Leakage flag (ml-cv-lead, 2026-10-02): the 25 camera calibration pages include Non Nobis Domine, Gaano, Handog,
# Honneur and Don't Stop Me Now, i.e. the 2026-09-28 fresh-photo eval pieces. The augmentation is tuned to their
# pixel statistics (not labels), so Phase 2 accuracy on those photos is not held-out evidence.
COVER_TOL = 0.10
COVER_KEYS: tuple[str, ...] = ("interline_px", "line_depth", "head_depth", "line_head_ratio", "line_fwhm_il",
                               "paper_grey", "noise_rel")
LOW_SHARE_BAND = (0.05, 0.35)
PAGE_DROP_MAX = 0.25
FEATURE_DROP_MAX = 0.10
BIAS_BAND = (0.85, 1.15)
STAFF_OFFSET_P99_MAX = 1.0
DEFAULT_CAMERA_STATS = Path("D:/PiyaNota-training/data/phase1_strips/camera_page_stats.json")
BIAS_PARAMS: tuple[str, ...] = ("ink_depth", "line_ink", "blur_spacings", "illum_ratio", "line_mult",
                                 "noise_sigma", "sharpen_amount", "paper_grey")
AT_P50_MIN: dict[str, float] = {"line_depth": 0.25, "line_head_ratio": 0.25, "head_depth": 0.30}
NOISE_ABOVE_P95_MAX = 0.15
FWHM_ABOVE_P95_BAND = (0.05, 0.20)
IQR_KEYS: tuple[str, ...] = ("noise_rel", "paper_grey", "illum_ratio")
TERTILE_DROP_MAX_RATIO = 2.0
REGISTRATION_FAIL_WHY: tuple[str, ...] = ("unregistered", "unregistered_edge")
STRUCTURAL_BAND_REASON = "no_strip_source"
DOT_TOKEN = "dot"
STRUCTURAL_SKIP = "short_systems_only"
TIE_TOKEN = "slur.start"
PAPER_AREA_P50_MIN = 0.97
PAPER_AREA_LOW = 0.80
PAPER_AREA_LOW_SHARE_MAX = 0.15
FILL_FALLBACK_MAX = 0.05
FRAMING_BIAS_MAX_RATIO = 1.5
DROP_RATIO_MIN_EVENTS = 3
DROP_PERM_REPS = 5000
DROP_PERM_SEED = 20261002
DROP_PERM_ALPHA = 0.05
# Amendment C' (user-adopted 2026-10-02, before the bach_smoke100e report was run).
DROP_RANK_REPS = 5000
DROP_RANK_SEED = 20261005
DROP_STRIP_PERM_REPS = 5000
DROP_STRIP_PERM_SEED = 20261006
CONFIRM_REPS = 5000
CONFIRM_SEED = 20261007
CONFIRM_PARAM = "line_ink"              # the 100d lead: faint lines erase dots/ties (single-cell p 0.006, FWER p 0.11)
CONFIRM_TERTILE = 0                     # lowest tertile
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20261001
BOOTSTRAP_CI = (2.5, 97.5)
STAVE_KEYS: tuple[str, ...] = ("interline_px", "line_depth", "head_depth", "line_head_ratio", "line_fwhm_il")
PAGE_KEYS: tuple[str, ...] = ("paper_grey", "illum_ratio", "noise_rel", "paper_area_frac")
CAMERA_PAGES = 25


def page_bootstrap_ci(hits: np.ndarray, n: np.ndarray) -> list[float] | None:
    """95% CI of a pooled share sum(hits) / sum(n), resampling pages (rows) with replacement.

    Why pages: staves on one page share every augmentation draw (within-page correlation ~0.99), so a stave-level
    binomial interval would be far too narrow (recal2 amendment (c)).

    Args:
        hits: per page, the number of units (staves, strips, features) meeting the condition.
        n: per page, the number of units.

    Returns:
        [lo, hi] rounded, or None when there are no units.
    """
    hits, n = np.asarray(hits, dtype=np.float64), np.asarray(n, dtype=np.float64)
    keep = n > 0
    hits, n = hits[keep], n[keep]
    if n.size == 0:
        return None
    idx = np.random.default_rng(BOOTSTRAP_SEED).integers(0, n.size, (BOOTSTRAP_REPS, n.size))
    shares = hits[idx].sum(axis=1) / n[idx].sum(axis=1)
    return [round(float(np.percentile(shares, q)), 4) for q in BOOTSTRAP_CI]


def _tertile_cells(pool_vals: np.ndarray, vals: np.ndarray) -> list[np.ndarray]:
    """Tertile masks over `vals`, with edges from `pool_vals` (the same edges the legacy drop_by_param uses)."""
    edges = np.quantile(pool_vals, [0, 1 / 3, 2 / 3, 1])
    return [((vals > edges[i]) if i else (vals >= edges[i])) & (vals <= edges[i + 1]) for i in range(3)]


def _strip_ratios(cells: np.ndarray, cut: np.ndarray, fd: np.ndarray) -> np.ndarray:
    """Per-cell strip feature-drop ratio to overall for each row of fd (reps x pages); NaN where < 3 events."""
    overall = fd.sum(axis=-1, keepdims=True) / max(float(cut.sum(axis=-1).max()), 1.0)  # shuffles keep the total
    cell_fd = fd @ cells.T
    cell_cut = cut @ cells.T if cut.ndim > 1 else np.broadcast_to(cells @ cut, cell_fd.shape)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = (cell_fd / np.maximum(cell_cut, 1)) / overall
    ratio = np.where(overall > 0, ratio, 0.0)
    return np.where(cell_fd >= DROP_RATIO_MIN_EVENTS, ratio, np.nan)


def drop_param_cprime(aug_pool: list[dict[str, Any]], thresholds: dict[str, float]) -> dict[str, Any]:
    """Amendment C' (see the amendment block): R1 rank-permutation page arm, R2 page-shuffle strip arm, R3 the
    pre-specified line_ink confirmatory cell. Pages, not strips, are the exchangeable unit in every null."""
    pool = [r for r in aug_pool if all(prm in r["params"] for prm in BIAS_PARAMS)]
    out: dict[str, Any] = {"pages": len(pool)}
    if not pool:
        out.update(fail=False, flag="no pages with every parameter")
        return out
    vals = np.array([[float(r["params"][prm]) for r in pool] for prm in BIAS_PARAMS])  # params x pages
    dropped = np.array([r["status"] != "ok" for r in pool], dtype=bool)
    n, k = len(pool), int(dropped.sum())

    # R1: page arm.
    from scipy.stats import rankdata
    ranks = np.vstack([rankdata(v, method="average") for v in vals])
    sd = math.sqrt(k * (n - k) * (n + 1) / 12) if 0 < k < n else 0.0

    def rank_t(lab: np.ndarray) -> tuple[float, int]:
        if sd == 0:
            return 0.0, 0
        z = (ranks @ lab.astype(np.float64) - k * (n + 1) / 2) / sd
        j = int(np.argmax(np.abs(z)))
        return float(abs(z[j])), j

    t_obs, j_obs = rank_t(dropped)
    rng = np.random.default_rng(DROP_RANK_SEED)
    null_t = np.array([rank_t(rng.permutation(dropped))[0] for _ in range(DROP_RANK_REPS)])
    p_r1 = float((1 + np.sum(null_t >= t_obs - 1e-12)) / (1 + DROP_RANK_REPS))
    overall_p = k / n
    floor_cells = []
    for c in _tertile_cells(vals[j_obs], vals[j_obs]):
        ev = int(dropped[c].sum())
        ratio = (float(dropped[c].mean()) / overall_p) if overall_p and c.any() else 0.0
        floor_cells.append({"events": ev, "ratio": round(ratio, 3)})
    floor_hit = any(c["events"] >= DROP_RATIO_MIN_EVENTS and c["ratio"] > TERTILE_DROP_MAX_RATIO for c in floor_cells)
    unevaluable = k < DROP_RATIO_MIN_EVENTS
    r1_fail = (not unevaluable) and p_r1 < DROP_PERM_ALPHA and floor_hit
    out["R1_page_rank"] = {"drop_events": k, "T": round(t_obs, 3), "param": BIAS_PARAMS[j_obs],
                           "p_value": round(p_r1, 4),
                           "mc_se": round(math.sqrt(p_r1 * (1 - p_r1) / DROP_RANK_REPS), 4),
                           "param_tertiles": floor_cells, "two_x_floor_hit": floor_hit,
                           "page_arm_unevaluable_k_lt_3": unevaluable, "fail": r1_fail,
                           "reps": DROP_RANK_REPS, "seed": DROP_RANK_SEED}

    # R2 and R3: strip arm over the ok pages, whole pages shuffled.
    ok = ~dropped
    cut = np.array([sum(1 for st in r["strips"] if st["status"] == "cut") for r, o in zip(pool, ok) if o],
                   dtype=np.float64)
    fd = np.array([sum(1 for st in r["strips"] if st["status"] == "cut" and strip_verdict(st, thresholds) is not None)
                   for r, o in zip(pool, ok) if o], dtype=np.float64)
    cells = np.vstack([c for pi in range(len(BIAS_PARAMS)) for c in _tertile_cells(vals[pi], vals[pi][ok])]
                      ).astype(np.float64)  # (params x 3) x ok pages
    obs = _strip_ratios(cells, cut, fd[None, :])[0]
    worst_obs = float(np.nanmax(obs)) if np.isfinite(obs).any() else 0.0
    rng = np.random.default_rng(DROP_STRIP_PERM_SEED)
    perms = np.array([rng.permutation(len(cut)) for _ in range(DROP_STRIP_PERM_REPS)])
    null = _strip_ratios(cells, cut[perms], fd[perms])
    null_worst = np.where(np.isfinite(null).any(axis=1), np.nanmax(np.nan_to_num(null, nan=-1.0), axis=1), 0.0)
    p_r2 = float((1 + np.sum(null_worst >= worst_obs - 1e-12)) / (1 + DROP_STRIP_PERM_REPS))
    worst_cell = int(np.nanargmax(obs)) if np.isfinite(obs).any() else None
    r2_fail = worst_obs > TERTILE_DROP_MAX_RATIO and p_r2 < DROP_PERM_ALPHA
    out["R2_strip_perm"] = {"strips_cut": int(cut.sum()), "feature_strip_drops": int(fd.sum()),
                            "worst_ratio": round(worst_obs, 3),
                            "worst_cell": (None if worst_cell is None else
                                           f"{BIAS_PARAMS[worst_cell // 3]}/tertile_{worst_cell % 3 + 1}"),
                            "p_value": round(p_r2, 4), "null_p95_worst": round(float(np.percentile(null_worst, 95)), 3),
                            "fail": r2_fail, "reps": DROP_STRIP_PERM_REPS, "seed": DROP_STRIP_PERM_SEED}

    ci = BIAS_PARAMS.index(CONFIRM_PARAM) * 3 + CONFIRM_TERTILE
    cell = cells[ci:ci + 1]
    overall_f = fd.sum() / max(cut.sum(), 1.0)
    cell_cut = float((cell @ cut)[0])
    ratio_obs = float((cell @ fd)[0] / max(cell_cut, 1.0) / overall_f) if overall_f else 0.0
    rng = np.random.default_rng(CONFIRM_SEED)
    perms = np.array([rng.permutation(len(cut)) for _ in range(CONFIRM_REPS)])
    c_fd, c_cut = fd[perms] @ cell[0], cut[perms] @ cell[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        null_c = np.where(overall_f > 0, (c_fd / np.maximum(c_cut, 1)) / overall_f, 0.0)
    p_r3 = float((1 + np.sum(null_c >= ratio_obs - 1e-12)) / (1 + CONFIRM_REPS))
    confirmed = p_r3 < DROP_PERM_ALPHA and ratio_obs > TERTILE_DROP_MAX_RATIO
    out["R3_confirm"] = {"cell": f"{CONFIRM_PARAM}/tertile_{CONFIRM_TERTILE + 1}",
                         "feature_strip_drops": int((cell @ fd)[0]), "strips_cut": int(cell_cut),
                         "ratio": round(ratio_obs, 3), "p_value_one_sided": round(p_r3, 4),
                         "confirmed": confirmed, "reps": CONFIRM_REPS, "seed": CONFIRM_SEED}
    out["fail"] = bool(r1_fail or r2_fail or confirmed)
    return out


def _page_drop_max_ratio(dropped: np.ndarray, bins: list[np.ndarray]) -> float:
    """Largest page-drop ratio-to-overall over the given tertile masks, counting only cells with enough events."""
    overall = float(dropped.mean())
    if overall == 0:
        return 0.0
    best = 0.0
    for m in bins:
        n_ev = int(dropped[m].sum())
        if n_ev >= DROP_RATIO_MIN_EVENTS:
            best = max(best, float(dropped[m].mean()) / overall)
    return best


def drop_param_permutation(aug_pool: list[dict[str, Any]]) -> dict[str, Any]:
    """Max-statistic permutation test for the page-level drop_by_param cells (recal3 amendment C).

    Under the null the augmentation-induced drop labels are exchangeable over the pages; permuting them and taking
    the maximum ratio over every parameter x tertile cell controls the family-wise error of the 24-cell check.
    With ~5 drop events the test has almost no power; it only screens out chance concentrations.
    """
    pool = [r for r in aug_pool if all(prm in r["params"] for prm in BIAS_PARAMS)]
    if not pool:
        return {"p_value": None, "reason": "no pages with every parameter"}
    dropped = np.array([r["status"] != "ok" for r in pool], dtype=bool)
    bins: list[np.ndarray] = []
    for prm in BIAS_PARAMS:
        vals = np.array([float(r["params"][prm]) for r in pool])
        edges = np.quantile(vals, [0, 1 / 3, 2 / 3, 1])
        for i in range(3):
            lo_ok = vals > edges[i] if i else vals >= edges[i]
            bins.append(lo_ok & (vals <= edges[i + 1]))
    observed = _page_drop_max_ratio(dropped, bins)
    rng = np.random.default_rng(DROP_PERM_SEED)
    null = np.array([_page_drop_max_ratio(rng.permutation(dropped), bins) for _ in range(DROP_PERM_REPS)])
    return {"observed_max_ratio": round(observed, 3), "drop_events": int(dropped.sum()), "pages": len(pool),
            "reps": DROP_PERM_REPS, "seed": DROP_PERM_SEED,
            "p_value": round(float((1 + np.sum(null >= observed - 1e-12)) / (1 + DROP_PERM_REPS)), 4),
            "null_share_above_2x": round(float(np.mean(null > TERTILE_DROP_MAX_RATIO)), 4)}


def _share_with_ci(per_page: list[np.ndarray], pred: Callable[[np.ndarray], np.ndarray]) -> dict[str, Any]:
    """Point share over all units plus its page-bootstrap CI; `per_page` holds each page's values."""
    hits = np.array([int(pred(v).sum()) for v in per_page])
    n = np.array([v.size for v in per_page])
    return {"share": round(float(hits.sum() / n.sum()), 4) if n.sum() else None,
            "page_ci95": page_bootstrap_ci(hits, n)}


def band_only_page(renders: Path, font: str, piece: str, res: dict[str, Any]) -> bool:
    """True when no system on the page is surely wide enough for Stage 1 (all below SHORT_SPAN_HI)."""
    meta = json.loads((renders / font / piece / "meta.json").read_text(encoding="utf-8"))
    page = int(res["key"].rsplit("_", 1)[1])
    width = float(meta["png_width_px"])
    span: dict[int, float] = {}
    for b in meta["staff_boxes_px"]:
        if b["page"] == page:
            f = (b["right"] - b["left"]) / width
            span[b["system"]] = min(span.get(b["system"], f), f)
    return bool(span) and all(f < SHORT_SPAN_HI for f in span.values())


def structural_label_loss(renders: Path, results: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    """Labelled systems never cut for structural reasons, and how many of them are a piece's final system.

    Why: short systems are almost always the last system of a piece (a final partial line), so skipping them is a
    known bias against piece endings (final cadences, fermatas, final barlines) in the training set.
    """
    lost: set[tuple[str, str, int, int]] = set()
    labelled: set[tuple[str, str, int, int]] = set()
    final_sys: dict[tuple[str, str], int] = {}
    for font, piece, r in results:
        labs = json.loads((renders / font / piece / "labels.json").read_text(encoding="utf-8"))
        final_sys[(font, piece)] = max(x["system"] for x in labs)
        page = int(r["key"].rsplit("_", 1)[1])
        sys_here = {(font, piece, page, x["system"]) for x in labs if x["page"] == page and x["quarantine"] is None}
        labelled |= sys_here
        if r.get("reason") == STRUCTURAL_SKIP or (r["status"] != "ok" and str(r.get("reason")).split(":")[0]
                                                  == STRUCTURAL_BAND_REASON and band_only_page(renders, font,
                                                                                               piece, r)):
            lost |= sys_here
        for s in r.get("strips", []):
            if s.get("reason") == "short_system_untracked":
                lost.add((font, piece, page, s["system"]))
    n_final = sum(1 for f, pc, _, sy in lost if sy == final_sys[(f, pc)])
    return {"systems_labelled": len(labelled), "systems_lost": len(lost),
            "share_lost": round(len(lost) / max(len(labelled), 1), 4),
            "lost_that_are_final_system": n_final, "final_share_of_lost": round(n_final / max(len(lost), 1), 4)}


def page_kinds(meta: dict[str, Any], page: int) -> dict[str, bool]:
    """Whether a page holds a single system and whether it holds the piece's final system."""
    page_sys = meta["page_systems"][page - 1]
    last = max(s for ps in meta["page_systems"] for s in ps)
    return {"single_system": len(page_sys) == 1, "final_system": last in page_sys}


def framing_bias(renders: Path, framed: list[tuple[str, str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Share of single-system / final-system pages under standard framing vs among all photographed pages.

    Why: a fill placement that cannot fit falls back to standard framing, and the pages that cannot fit are the
    short ones, so standard framing could end up concentrated on piece endings (ruling 2026-10-01). Pass when the
    standard-framing share is at most FRAMING_BIAS_MAX_RATIO x the overall share (trivially when either is empty).
    """
    metas: dict[tuple[str, str], dict[str, Any]] = {}
    rows: list[tuple[dict[str, bool], bool]] = []
    for font, piece, r in framed:
        if (font, piece) not in metas:
            metas[(font, piece)] = json.loads((renders / font / piece / "meta.json").read_text(encoding="utf-8"))
        page = int(r["key"].rsplit("_", 1)[1])
        rows.append((page_kinds(metas[(font, piece)], page), r["params"]["framing_used"] == FRAMING_STANDARD))
    out: dict[str, dict[str, Any]] = {}
    for kind in ("single_system", "final_system"):
        all_share = sum(k[kind] for k, _ in rows) / max(len(rows), 1)
        std = [k for k, s in rows if s]
        std_share = sum(k[kind] for k in std) / max(len(std), 1)
        ratio = std_share / all_share if all_share else (0.0 if std_share == 0 else math.inf)
        out[kind] = {"share_all": round(all_share, 4), "share_standard": round(std_share, 4),
                     "standard_pages": len(std), "ratio": round(ratio, 3), "max_ratio": FRAMING_BIAS_MAX_RATIO,
                     "pass": not std or ratio <= FRAMING_BIAS_MAX_RATIO}
    return out


def _pct(v: list[float]) -> list[float]:
    return [round(float(np.percentile(v, q)), 4) for q in (5, 50, 95)] if v else []


def cmd_report(a: argparse.Namespace) -> None:
    out: Path = a.out
    require_camera_fwhm_method(a.camera)
    results = load_results(out)
    cam = json.loads(a.camera.read_text(encoding="utf-8"))["summary"]["camera"]
    rep: dict[str, Any] = {"pages": len(results)}
    checks: dict[str, bool] = {}

    # R1: null calibration of the survival threshold, per feature kind.
    nulls: dict[str, list[float]] = {}
    zs: dict[str, list[float]] = {}
    for _, _, res in results:
        for s in res.get("strips", []):
            for f in s.get("features", []):
                nulls.setdefault(f["kind"], []).extend(f.get("null_z", []))
                if f["z"] is not None:
                    zs.setdefault(f["kind"], []).append(f["z"])
    thresholds = {k: round(float(np.quantile(v, 1 - NULL_FALSE_PASS_MAX)), 3) for k, v in nulls.items() if v}
    for k in FEATURE_CLASSES:
        thresholds.setdefault(k, max(thresholds.values()) if thresholds else 3.0)
    rep["null"] = {k: {"n": len(v), "pct5_50_95": _pct(v), "threshold": thresholds[k]} for k, v in nulls.items()}
    rep["feature_z"] = {k: {"n": len(v), "pct5_50_95": _pct(v),
                            "fail_share": round(float(np.mean(np.array(v) <= thresholds[k])), 4)}
                        for k, v in zs.items()}
    (out / "thresholds.json").write_text(json.dumps({"thresholds": thresholds, "false_pass_max":
                                                     NULL_FALSE_PASS_MAX, "pages": len(results)}, indent=1),
                                         encoding="utf-8")

    # R3: measured statistics vs camera.
    staves = [st for _, _, r in results if r.get("stats") for st in r["stats"].get("staves", [])]
    pages_st = [r["stats"] for _, _, r in results if r.get("stats") and "paper_grey" in r["stats"]]
    aug: dict[str, list[float]] = {k: [float(st[k]) for st in staves if np.isfinite(st[k])]
                                   for k in ("interline_px", "line_depth", "head_depth", "line_head_ratio",
                                             "line_fwhm_il")}
    for k in ("paper_grey", "illum_ratio", "noise_rel", "paper_area_frac"):
        aug[k] = [float(s[k]) for s in pages_st if s.get(k) is not None]
    # Amendment (c): the same values grouped by page, for the page-bootstrap CIs.
    per_page: dict[str, list[np.ndarray]] = {}
    for k in STAVE_KEYS:
        arrs = [np.array([float(st[k]) for st in r["stats"].get("staves", [])], dtype=np.float64)
                for _, _, r in results if r.get("stats")]
        per_page[k] = [x[np.isfinite(x)] for x in arrs]
    for k in PAGE_KEYS:
        per_page[k] = [np.array([float(s[k])]) for s in pages_st if s.get(k) is not None]
    rep["stats"] = {}
    for k, v in aug.items():
        c5, c95 = cam[k][0], cam[k][4]
        row = {"aug_p5_50_95": _pct(v), "cam_p5_50_95": [c5, cam[k][2], c95], "n": len(v),
               "n_pages": len(per_page[k]),
               "share_below_cam_p5": round(float(np.mean(np.array(v) < c5)), 4) if v else None,
               "share_at_or_above_cam_p50": round(float(np.mean(np.array(v) >= cam[k][2])), 4) if v else None,
               "share_above_cam_p95": round(float(np.mean(np.array(v) > c95)), 4) if v else None,
               "page_ci95": {
                   "share_below_cam_p5": _share_with_ci(per_page[k], lambda x, t=c5: x < t)["page_ci95"],
                   "share_at_or_above_cam_p50": _share_with_ci(per_page[k],
                                                               lambda x, t=cam[k][2]: x >= t)["page_ci95"],
                   "share_above_cam_p95": _share_with_ci(per_page[k], lambda x, t=c95: x > t)["page_ci95"]}}
        if k in AT_P50_MIN and v:
            checks[f"at_p50:{k}"] = row["share_at_or_above_cam_p50"] >= AT_P50_MIN[k]
        if k in IQR_KEYS and v:
            row["aug_p50_in_cam_iqr"] = bool(cam[k][1] <= float(np.median(v)) <= cam[k][3])
            checks[f"iqr:{k}"] = row["aug_p50_in_cam_iqr"]
        if k in COVER_KEYS and v:
            lo, hi = float(np.percentile(v, 5)), float(np.percentile(v, 95))
            row["cover_pass"] = bool(lo <= c5 * (1 + COVER_TOL) and hi >= c95 * (1 - COVER_TOL))
            checks[f"cover:{k}"] = row["cover_pass"]
        rep["stats"][k] = row
    for k in ("line_depth", "head_depth"):
        sh = rep["stats"][k]["share_below_cam_p5"]
        checks[f"low_share:{k}"] = sh is not None and LOW_SHARE_BAND[0] <= sh <= LOW_SHARE_BAND[1]
    sh = rep["stats"]["noise_rel"]["share_above_cam_p95"]
    checks["noise_above_p95"] = sh is not None and sh <= NOISE_ABOVE_P95_MAX
    sh = rep["stats"]["line_fwhm_il"]["share_above_cam_p95"]
    checks["fwhm_above_p95"] = sh is not None and FWHM_ABOVE_P95_BAND[0] <= sh <= FWHM_ABOVE_P95_BAND[1]
    # Recal2 amendment: framing (paper fills the frame as in the camera pages).
    paf = per_page["paper_area_frac"]
    low_area = _share_with_ci(paf, lambda x: x < PAPER_AREA_LOW)
    paf_p50 = float(np.median(np.concatenate(paf))) if paf else None
    rep["paper_area"] = {"aug_p50": None if paf_p50 is None else round(paf_p50, 4), "p50_min": PAPER_AREA_P50_MIN,
                         f"share_below_{PAPER_AREA_LOW}": low_area["share"],
                         f"share_below_{PAPER_AREA_LOW}_page_ci95": low_area["page_ci95"],
                         "share_max": PAPER_AREA_LOW_SHARE_MAX}
    checks["paper_area_p50"] = paf_p50 is not None and paf_p50 >= PAPER_AREA_P50_MIN
    checks["paper_area_low_share"] = low_area["share"] is not None and low_area["share"] <= PAPER_AREA_LOW_SHARE_MAX
    modes: dict[str, list[dict[str, Any]]] = {}
    for _, _, r in results:
        if "paper_frame_frac" in r["params"]:
            modes.setdefault(f"{r['params'].get('framing_requested')}->{r['params'].get('framing_used')}",
                             []).append(r)
    framed = [(f, pc, r) for f, pc, r in results if "framing_requested" in r.get("params", {})]
    fill_req = [r for _, _, r in framed if r["params"]["framing_requested"] == FRAMING_FILL]
    n_fallback = sum(1 for r in fill_req if r["params"]["framing_used"] != FRAMING_FILL)
    rep["fill_fallback"] = {"fill_requested": len(fill_req), "fell_back_to_standard": n_fallback,
                            "rate": round(n_fallback / max(len(fill_req), 1), 4), "max": FILL_FALLBACK_MAX}
    checks["fill_fallback"] = n_fallback / max(len(fill_req), 1) <= FILL_FALLBACK_MAX
    rep["framing_bias"] = framing_bias(a.renders, framed)
    checks["framing_bias"] = all(v["pass"] for v in rep["framing_bias"].values())
    rep["framing"] = {m: {"pages": len(rs), "ok": sum(1 for r in rs if r["status"] == "ok"),
                          "paper_frame_frac_p5_50_95": _pct([r["params"]["paper_frame_frac"] for r in rs]),
                          "measured_paper_area_frac_p5_50_95": _pct([r["stats"]["paper_area_frac"] for r in rs
                                                                     if r.get("stats")
                                                                     and r["stats"].get("paper_area_frac")
                                                                     is not None]),
                          "coverage_rejects_total": sum(int(r["params"].get("coverage_rejects", 0)) for r in rs),
                          "no_fit": sum(1 for r in rs if r.get("reason") == "no_fit")}
                      for m, rs in sorted(modes.items())}
    pairs = [(r["params"]["illum_ratio"], r["stats"]["illum_ratio"]) for _, _, r in results
             if r.get("stats") and "illum_ratio" in r["stats"]]
    rep["illum_sampled_vs_measured"] = [[round(x, 3), round(y, 3)] for x, y in pairs]
    # Recal3 (ml-cv-lead (d)): illumination and shadow changed together, so the paper-area and noise outcomes are
    # reported per stratum. Reported only, not checks.
    strata: dict[str, list[dict[str, Any]]] = {}
    for _, _, r in results:
        prm = r.get("params", {})
        if "illum_ratio" not in prm or r.get("reason") == STRUCTURAL_SKIP:
            continue
        key = (f"illum_{'low' if prm['illum_ratio'] < ILLUM_HIGH[0] else 'high'}"
               f"/shadow_{'yes' if prm.get('shadow') else 'no'}")
        strata.setdefault(key, []).append(r)
    rep["illum_shadow_strata"] = {}
    for key, rs in sorted(strata.items()):
        st = [r["stats"] for r in rs if r.get("stats") and r["stats"].get("paper_area_frac") is not None]
        rep["illum_shadow_strata"][key] = {
            "pages_photographed": len(rs), "ok": sum(1 for r in rs if r["status"] == "ok"),
            f"paper_area_share_below_{PAPER_AREA_LOW}": (round(float(np.mean([x["paper_area_frac"] < PAPER_AREA_LOW
                                                                               for x in st])), 4) if st else None),
            "paper_area_p5_50_95": _pct([x["paper_area_frac"] for x in st]),
            "noise_rel_p5_50_95": _pct([x["noise_rel"] for x in st if x.get("noise_rel") is not None])}

    # R4: drops and selection bias.
    # Pages skipped before any photo exists (every system shorter than the Stage 1 tracker can follow) are a
    # property of the render, not of the augmentation, so the pre-registered page-drop check is applied to the
    # photographed pages; the all-pages rate is reported next to it.
    n_pages = len(results)
    n_ok = sum(1 for _, _, r in results if r["status"] == "ok")
    shot = [r for _, _, r in results if r.get("reason") != STRUCTURAL_SKIP]
    rep["page_drop_rate_all"] = round(1 - n_ok / max(n_pages, 1), 4)
    rep["page_drop_rate"] = round(1 - n_ok / max(len(shot), 1), 4)
    rep["pages_photographed"] = len(shot)
    band = [(f, pc, r) for f, pc, r in results if r["status"] != "ok"
            and str(r.get("reason")).split(":")[0] == STRUCTURAL_BAND_REASON and band_only_page(a.renders, f, pc, r)]
    band_keys = {id(r) for _, _, r in band}
    aug_drop = [r for r in shot if r["status"] != "ok" and id(r) not in band_keys]
    rep["page_drops_split"] = {
        "pages_all": n_pages,
        "structural_skips_never_photographed": n_pages - len(shot),
        "structural_band_failures": len(band),
        "augmentation_induced": len(aug_drop),
        "augmentation_induced_rate_of_photographed": round(len(aug_drop) / max(len(shot), 1), 4),
        "augmentation_induced_rate_excl_band": round(len(aug_drop) / max(len(shot) - len(band), 1), 4),
        "augmentation_induced_reasons": dict(collections.Counter(str(r["reason"]).split(":")[0]
                                                                 for r in aug_drop))}
    rep["page_drop_reasons"] = dict(collections.Counter(r["reason"].split(":")[0] for _, _, r in results
                                                        if r["status"] != "ok"))
    checks["page_drops"] = rep["page_drop_rate"] <= PAGE_DROP_MAX
    rep["uncut_strip_reasons"] = dict(collections.Counter(
        str(s.get("reason")).split(":")[0] for _, _, r in results if r["status"] == "ok"
        for s in r["strips"] if s["status"] != "cut"))
    cut = [(r, s) for _, _, r in results if r["status"] == "ok" for s in r["strips"] if s["status"] == "cut"]
    verdict = [(r, s, strip_verdict(s, thresholds)) for r, s in cut]
    rep["strip_drop_reasons"] = dict(collections.Counter(v for _, _, v in verdict if v is not None))
    feat_drop = sum(1 for _, _, v in verdict if v is not None) / max(len(verdict), 1)
    rep["feature_drop_rate"] = round(feat_drop, 4)
    by_page_verdict: dict[int, list[bool]] = {}
    for r, _, v in verdict:
        by_page_verdict.setdefault(id(r), []).append(v is not None)
    rep["feature_drop_rate_page_ci95"] = _share_with_ci(
        [np.array(x, dtype=bool) for x in by_page_verdict.values()], lambda x: x)["page_ci95"]
    checks["feature_drops"] = feat_drop <= FEATURE_DROP_MAX
    labelled: list[list[str]] = []
    page_labels: list[tuple[dict[str, Any], list[list[str]]]] = []
    for font, piece, r in results:
        labs = json.loads((a.renders / font / piece / "labels.json").read_text(encoding="utf-8"))
        page = int(r["key"].rsplit("_", 1)[1])
        page_toks = [x["tokens"] for x in labs if x["page"] == page and x["quarantine"] is None]
        labelled += page_toks
        page_labels.append((r, page_toks))
    kept_tokens = [s["tokens"] for _, s, v in verdict if v is None]

    def share(rows: list[list[str]], tok: str) -> float:
        return float(np.mean([any(t.split("-")[0] == tok for t in toks) for toks in rows])) if rows else 0.0

    for name, tok in (("dotted", DOT_TOKEN), ("tied", TIE_TOKEN)):
        s_all, s_kept = share(labelled, tok), share(kept_tokens, tok)
        ratio = s_kept / s_all if s_all else float("nan")
        rep[f"bias_{name}"] = {"share_all_labelled": round(s_all, 4), "share_kept": round(s_kept, 4),
                               "ratio": round(ratio, 3),
                               "n_all_labelled": [round(s_all * len(labelled)), len(labelled)],
                               "n_kept": [round(s_kept * len(kept_tokens)), len(kept_tokens)]}
        checks[f"bias:{name}"] = bool(np.isfinite(ratio) and BIAS_BAND[0] <= ratio <= BIAS_BAND[1])
    # Recal3 (ml-cv-lead (c)): 100d dropped 13 low-line_ink strips against ~6 expected (dot/tie registration on faint
    # lines). Logged, not tuned away: dotted/tied share kept vs labelled per line_ink tertile. Reported only.
    li_pages = [(r, labs) for r, labs in page_labels if "line_ink" in r.get("params", {})]
    rep["bias_by_line_ink"] = {}
    if li_pages:
        li_edges = np.quantile([r["params"]["line_ink"] for r, _ in li_pages], [0, 1 / 3, 2 / 3, 1])
        for i in range(3):
            lo, hi = li_edges[i], li_edges[i + 1]
            sel = [(r, labs) for r, labs in li_pages
                   if (lo < r["params"]["line_ink"] if i else lo <= r["params"]["line_ink"])
                   and r["params"]["line_ink"] <= hi]
            ids = {id(r) for r, _ in sel}
            lab_t = [toks for _, labs in sel for toks in labs]
            kept_t = [sv["tokens"] for r, sv, v in verdict if v is None and id(r) in ids]
            row: dict[str, Any] = {"range": [round(float(lo), 3), round(float(hi), 3)], "pages": len(sel),
                                   "labelled_strips": len(lab_t), "kept_strips": len(kept_t)}
            for name, tok in (("dotted", DOT_TOKEN), ("tied", TIE_TOKEN)):
                s_all, s_kept = share(lab_t, tok), share(kept_t, tok)
                row[f"bias_{name}"] = round(s_kept / s_all, 3) if s_all else None
            rep["bias_by_line_ink"][f"tertile_{i + 1}"] = row
    # Tertiles over augmentation-induced page drops (band failures and never-photographed pages are not the
    # augmentation's doing) and feature-survival strip drops.
    rep["drop_by_param"] = {}
    aug_pool = [r for r in shot if id(r) not in band_keys]
    all_ok = [r for r in aug_pool if r["status"] == "ok"]
    all_st = [s for r in all_ok for s in r["strips"] if s["status"] == "cut"]
    overall_page = 1 - len(all_ok) / max(len(aug_pool), 1)
    overall_feat = sum(strip_verdict(s, thresholds) is not None for s in all_st) / max(len(all_st), 1)
    rep["drop_overall"] = {"page_drop": round(overall_page, 4), "feature_strip_drop": round(overall_feat, 4)}
    worst = 0.0
    worst_f = 0.0
    for prm in BIAS_PARAMS:
        if not aug_pool or any(prm not in r["params"] for r in aug_pool):
            rep["drop_by_param"][prm] = "absent from this run's params"
            continue
        vals = np.array([r["params"][prm] for r in aug_pool])
        edges = np.quantile(vals, [0, 1 / 3, 2 / 3, 1])
        bins = []
        for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
            sel = [r for r in aug_pool if (lo < r["params"][prm] if i else lo <= r["params"][prm])
                   and r["params"][prm] <= hi]
            ok = [r for r in sel if r["status"] == "ok"]
            st = [s for r in ok for s in r["strips"] if s["status"] == "cut"]
            fd = [s for s in st if strip_verdict(s, thresholds) is not None]
            pdrop, fdrop = 1 - len(ok) / max(len(sel), 1), len(fd) / max(len(st), 1)
            ratio_p = pdrop / overall_page if overall_page else (0.0 if pdrop == 0 else math.inf)
            ratio_f = fdrop / overall_feat if overall_feat else (0.0 if fdrop == 0 else math.inf)
            # Amendment (b): a ratio counts toward the 2x check only with enough drop events in the bin.
            eval_p = len(sel) - len(ok) >= DROP_RATIO_MIN_EVENTS
            eval_f = len(fd) >= DROP_RATIO_MIN_EVENTS
            worst = max(worst, ratio_p if eval_p else 0.0, ratio_f if eval_f else 0.0)
            worst_f = max(worst_f, ratio_f if eval_f else 0.0)
            bins.append({"range": [round(float(lo), 3), round(float(hi), 3)], "pages": len(sel),
                         "page_drops": len(sel) - len(ok), "page_drop": round(pdrop, 3),
                         "strips_cut": len(st), "feature_strip_drops": len(fd), "feature_strip_drop": round(fdrop, 3),
                         "ratio_to_overall": [round(ratio_p, 2), round(ratio_f, 2)],
                         "retention": [round((1 - pdrop) / (1 - overall_page), 3) if overall_page < 1 else None,
                                       round((1 - fdrop) / (1 - overall_feat), 3) if overall_feat < 1 else None],
                         "ratio_evaluated": [eval_p, eval_f]})
        rep["drop_by_param"][prm] = bins
    rep["drop_by_param_worst_ratio"] = round(worst, 2)
    rep["drop_by_param_worst_feature_ratio"] = round(worst_f, 2)
    rep["drop_by_param_page_permutation"] = drop_param_permutation(aug_pool)
    # Coordinator condition 2 (2026-10-01): thick lines can merge into dots, noteheads and ties, so feature survival
    # is split by line_mult tertile and by thick segment; no bin may exceed 2x the overall failure rate.
    lm_vals = np.array([r["params"]["line_mult"] for r, _ in cut]) if cut else np.array([])
    lm_bins: dict[str, Any] = {}
    worst_lm = 0.0
    if len(lm_vals):
        edges = np.quantile(lm_vals, [0, 1 / 3, 2 / 3, 1])
        groups = {f"tertile_{i + 1}[{edges[i]:.2f},{edges[i + 1]:.2f}]":
                  (lambda v, i=i: (edges[i] < v if i else edges[i] <= v) and v <= edges[i + 1]) for i in range(3)}
        groups["thick_segment(>=2.6)"] = lambda v: v >= LINE_MULT_THICK_RANGE[0]
        groups["not_thick(<2.6)"] = lambda v: v < LINE_MULT_THICK_RANGE[0]

        def rates(sel: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
            st = len(sel)
            fd = sum(strip_verdict(sv, thresholds) is not None for _, sv in sel)
            row: dict[str, Any] = {"strips": st, "feature_strip_drops": fd, "feature_strip_drop": round(fd / max(st, 1), 4)}
            strip_pp: dict[int, list[bool]] = {}
            for rr, sv in sel:
                strip_pp.setdefault(id(rr), []).append(strip_verdict(sv, thresholds) is not None)
            row["feature_strip_drop_page_ci95"] = _share_with_ci([np.array(x, dtype=bool) for x in strip_pp.values()],
                                                                 lambda x: x)["page_ci95"]
            for kind in ("dot", "tie"):
                fs = [f for _, sv in sel for f in sv.get("features", []) if f["kind"] == kind]
                fail = sum(1 for f in fs if f["z"] is None or f["z"] <= thresholds[kind])
                row[f"{kind}_features"] = len(fs)
                row[f"{kind}_fail"] = fail
                row[f"{kind}_survival"] = round(1 - fail / max(len(fs), 1), 4)
                surv_pp: dict[int, list[bool]] = {}
                for rr, sv in sel:
                    surv_pp.setdefault(id(rr), []).extend(not (f["z"] is None or f["z"] <= thresholds[kind])
                                                          for f in sv.get("features", []) if f["kind"] == kind)
                row[f"{kind}_survival_page_ci95"] = _share_with_ci([np.array(x, dtype=bool)
                                                                    for x in surv_pp.values()], lambda x: x)["page_ci95"]
            return row

        overall = rates(cut)
        lm_bins["overall"] = overall
        for name, pred in groups.items():
            row = rates([(r, sv) for r, sv in cut if pred(r["params"]["line_mult"])])
            ratios = []
            for key, n_key, d_key in (("feature_strip_drop", "feature_strip_drops", "strips"),
                                      ("dot", "dot_fail", "dot_features"), ("tie", "tie_fail", "tie_features")):
                o_rate = overall[n_key] / max(overall[d_key], 1)
                b_rate = row[n_key] / max(row[d_key], 1)
                ratios.append(b_rate / o_rate if o_rate else (0.0 if b_rate == 0 else math.inf))
            row["ratio_to_overall_strip_dot_tie"] = [round(x, 2) for x in ratios]
            worst_lm = max(worst_lm, *ratios)
            lm_bins[name] = row
    rep["feature_survival_by_line_mult"] = lm_bins
    rep["feature_survival_by_line_mult_worst_ratio"] = round(worst_lm, 2)
    checks["line_mult_survival_2x"] = bool(lm_bins) and worst_lm <= TERTILE_DROP_MAX_RATIO
    # Amendment C': the gate. The legacy 2x check and amendment C are reported only.
    rep["drop_by_param_cprime"] = drop_param_cprime(aug_pool, thresholds)
    checks["drop_by_param_cprime"] = not rep["drop_by_param_cprime"]["fail"]
    reported_only = {"legacy_2x": worst <= TERTILE_DROP_MAX_RATIO}
    # Recal3 amendment C (proposed; pending user ruling, see the amendment block): the page-level 2x cell fails only
    # with a max-statistic permutation p < DROP_PERM_ALPHA. Reported beside the legacy check, which stays the gate
    # until the ruling.
    perm = rep["drop_by_param_page_permutation"]
    reported_only["amendment_C"] = bool(
        worst <= TERTILE_DROP_MAX_RATIO
        or (perm.get("p_value") is not None and perm["p_value"] >= DROP_PERM_ALPHA
            and rep.get("drop_by_param_worst_feature_ratio", 0.0) <= TERTILE_DROP_MAX_RATIO))
    rep["drop_by_param_reported_only"] = reported_only
    # Amendment 2026-10-01: the old staff-offset gate, reported but no longer the gate.
    offs = [r["stats"]["staff_offset_spacings_maxabs"] for _, _, r in results
            if r["status"] == "ok" and r.get("stats")]
    rep["staff_offset_maxabs_p50_p99_max"] = ([round(float(np.percentile(offs, q)), 3) for q in (50, 99)]
                                              + [round(float(max(offs)), 3)]) if offs else []
    rep["staff_offset_old_gate_p99_lt_1"] = bool(offs) and float(np.percentile(offs, 99)) < STAFF_OFFSET_P99_MAX
    kept_margins = [s["identity_margin_il"] for _, s, v in verdict if v is None and "identity_margin_il" in s]
    rep["identity_margin"] = {
        "kept_boxes": len(kept_margins), "kept_without_margin": sum(1 for _, s, v in verdict
                                                                    if v is None and "identity_margin_il" not in s),
        "min_kept": round(min(kept_margins), 3) if kept_margins else None,
        "p5_kept": round(float(np.percentile(kept_margins, 5)), 3) if kept_margins else None,
        "strips_dropped_for_margin": rep["uncut_strip_reasons"].get("identity_margin", 0),
        "page_min": sorted(round(r["stats"]["identity_margin_min_il"], 3) for _, _, r in results
                           if r["status"] == "ok" and r.get("stats") and "identity_margin_min_il" in r["stats"])}
    checks["identity_margin"] = bool(kept_margins) and rep["identity_margin"]["kept_without_margin"] == 0 \
        and min(kept_margins) >= IDENTITY_MARGIN_MIN_SPACINGS
    feats = [f for r, s in cut for f in s.get("features", [])]
    reg_fail = sum(1 for f in feats if f.get("why") in REGISTRATION_FAIL_WHY)
    feats_by_page: dict[int, list[bool]] = {}
    for r, s in cut:
        feats_by_page.setdefault(id(r), []).extend(f.get("why") in REGISTRATION_FAIL_WHY
                                                   for f in s.get("features", []))
    rep["feature_registration"] = {"features": len(feats), "edge_or_low_corr": reg_fail,
                                   "share": round(reg_fail / max(len(feats), 1), 4),
                                   "share_page_ci95": _share_with_ci([np.array(x, dtype=bool)
                                                                      for x in feats_by_page.values()],
                                                                     lambda x: x)["page_ci95"],
                                   "by_why": dict(collections.Counter(str(f.get("why")) for f in feats))}
    checks["feature_registration"] = reg_fail / max(len(feats), 1) <= FEATURE_DROP_MAX
    rep["structural_label_loss"] = structural_label_loss(a.renders, results)
    secs = [r["seconds"] for _, _, r in results]
    rep["seconds_per_page_p50_mean"] = [round(float(np.median(secs)), 1), round(float(np.mean(secs)), 1)]
    rss = [float(r["rss_mb"]) for _, _, r in results if r.get("rss_mb") is not None]
    peaks = [float(r["peak_rss_mb"]) for _, _, r in results if r.get("peak_rss_mb") is not None]
    rep["memory_mb"] = {"rss_p50_max": [round(float(np.median(rss)), 1), round(max(rss), 1)] if rss else None,
                        "peak_working_set_max": round(max(peaks), 1) if peaks else None}
    # Recal2 flags (reported, not checks).
    run_info_path = out / "run_info.json"
    plan = (json.loads(run_info_path.read_text(encoding="utf-8")).get("smoke_plan")
            if run_info_path.exists() else None)
    per_font = collections.Counter(font for font, _, _ in results)
    flags: dict[str, Any] = {"camera_percentiles_from_pages": CAMERA_PAGES}
    if plan:
        rep["font_coverage"] = {f: {"planned": v["planned"], "available": v["available"], "results": per_font[f]}
                                for f, v in plan.items()}
        flags["under_sampled_fonts"] = sorted(f for f, v in plan.items() if per_font[f] < v["planned"])
    else:
        rep["font_coverage"] = dict(per_font)
        flags["under_sampled_fonts"] = "no smoke_plan in run_info.json (not a --smoke run or pre-recal2 run)"
    rep["flags"] = flags
    rep["decision_basis"] = "point estimates; page_ci95 values are reported only (amendment (c))"
    rep["checks"] = checks
    rep["report_code_sha256"] = sha256_file(Path(__file__))
    (out / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "illum_sampled_vs_measured"}, indent=1))


def cmd_tiles(a: argparse.Namespace) -> None:
    """1:1 eyeball page: each kept strip as cut, the clean render's staff under it, and its label tokens."""
    out: Path = a.out
    rows = [json.loads(line) for line in (out / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    rng = np.random.default_rng(BASE_SEED)
    pick = [rows[i] for i in sorted(rng.choice(len(rows), size=min(a.n, len(rows)), replace=False))]
    tdir = out / "tiles"
    tdir.mkdir(exist_ok=True)
    parts = ["<!doctype html><meta charset=utf-8><title>Phase 1 strips</title><body style='background:#fff;"
             "font:12px monospace'>"]
    for i, r in enumerate(pick):
        meta = json.loads((a.renders / r["font"] / r["piece"] / "meta.json").read_text(encoding="utf-8"))
        png = cv2.imread(str(a.renders / r["font"] / r["piece"] / f"page_{r['page']}.png"), cv2.IMREAD_GRAYSCALE)
        staff_n = str(VOICES.index(r["voice"]) + 1)
        b = next(x for x in meta["staff_boxes_px"] if x["page"] == r["page"] and x["system"] == r["system"]
                 and str(x["staff_n"]) == staff_n)
        h = b["bottom"] - b["top"]
        crop = png[max(0, int(b["top"] - 1.6 * h)):int(b["bottom"] + 1.6 * h), :]
        strip = cv2.imread(str(out / r["path"]), cv2.IMREAD_GRAYSCALE)
        ref = cv2.resize(crop, (strip.shape[1], int(crop.shape[0] * strip.shape[1] / crop.shape[1])),
                         interpolation=cv2.INTER_AREA)
        tile = np.vstack([strip, np.full((4, strip.shape[1]), 0, np.uint8), ref])
        name = f"tile_{i:03d}.png"
        cv2.imwrite(str(tdir / name), tile)
        parts.append(f"<p>{html.escape(r['font'])} {html.escape(r['piece'])} p{r['page']} sys{r['system']} "
                     f"{r['voice']} ({r['split']})<br><img src='tiles/{name}' style='image-rendering:pixelated'>"
                     f"<br>{html.escape(' '.join(r['tokens']))}</p>")
    (out / "tiles.html").write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {len(pick)} tiles to {out / 'tiles.html'}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--renders", type=Path, default=DEFAULT_RENDERS)
    r.add_argument("--prefix", default="bach_")
    r.add_argument("--yolo", type=Path, default=DEFAULT_YOLO)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--smoke", type=int, default=0)
    r.add_argument("--max-minutes", type=float, default=0.0)
    r.add_argument("--keep-photos", action="store_true")
    r.add_argument("--stats", action="store_true")
    r.add_argument("--force", action="store_true", help="redo pages that already have a result")
    r.add_argument("--variant", type=int, default=0, help="augmentation variant index (extra photos of a page)")
    r.add_argument("--camera", type=Path, default=DEFAULT_CAMERA_STATS, help="camera stats the ranges target")
    r.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"page worker processes (spawned, recycled every {WORKER_MAX_TASKS} pages)")
    m = sub.add_parser("manifest")
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--renders", type=Path, default=DEFAULT_RENDERS)
    m.add_argument("--groups", type=Path, required=True)
    m.add_argument("--thresholds", type=Path, required=True, help="thresholds.json written by `report`")
    rp_ = sub.add_parser("report")
    rp_.add_argument("--out", type=Path, required=True)
    rp_.add_argument("--renders", type=Path, default=DEFAULT_RENDERS)
    rp_.add_argument("--camera", type=Path, default=DEFAULT_CAMERA_STATS)
    t = sub.add_parser("tiles")
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--renders", type=Path, default=DEFAULT_RENDERS)
    t.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    {"run": cmd_run, "manifest": cmd_manifest, "tiles": cmd_tiles, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
