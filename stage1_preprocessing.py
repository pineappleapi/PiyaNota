"""
PiyaNota - Stage 1: Image Preprocessing Pipeline
"""

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from pathlib import Path

logger = logging.getLogger(__name__)


# ── blank_lyrics_regions() safety guard thresholds ────────────────────────────
# Calibrated against real staffline-mask output: a clean page reliably yields
# ~5 raw line-bands per staff (5 stafflines), e.g. 40 for 8 staves. A page
# where staffline detection has effectively failed (noisy/unnormalized camera
# photos) yields only a handful of scattered noise bands instead — observed as
# low as 7 on a 12-staff camera page. Below MIN_RAW_LINE_BANDS, trust nothing
# from this pass and leave the image unblanked rather than blank based on noise.
MIN_RAW_LINE_BANDS     = 20   # floor: one full system's worth of stafflines (4 staves x 5 lines)
MIN_MERGED_BAND_HEIGHT = 15   # px; merged bands shorter than this are noise, not a real staff
MAX_BLANK_HEIGHT_RATIO = 7.0  # a single blanked zone may never exceed this many multiples of staff_h

# ── Illumination normalization + edge-shadow blanking (camera-photo specific) ─
# Corrects uneven lighting/shadow gradients before thresholding, and blanks the
# outer edge bands where hand/table-shadow/book-spine artifacts typically sit.
# Ported from the abandoned stage1_preprocessing copy.py WIP.
BG_NORM_KERNEL_SIZE = 91   # px; elliptical dilation kernel used to estimate local background
BG_NORM_BLUR_KSIZE  = 3    # px; mild blur after normalization, to kill grain before thresholding
BORDER_TOP_PX    = 30
BORDER_BOTTOM_PX = 100
# Left is deliberately much smaller than right: the clef is almost always the
# first symbol on a staff, sitting close to the left margin — an aggressive
# left blank risks silently clipping it (infer_pitch() would then fall back
# to CLEF_FALLBACK[voice] instead of the real clef, corrupting every pitch on
# that strip without erroring). The right edge is low-consequence by
# comparison (trailing barline/whitespace), so it keeps the larger margin.
BORDER_LEFT_PX   = 20
BORDER_RIGHT_PX  = 80

# ── _blank_border_if_no_staff() content-protection margin ─────────────────────
# Extends protection beyond a detected staff's literal 5-line band so ledger
# lines, accidentals, and clef tails that extend past the staff proper aren't
# clipped when the staff sits near a border. Not calibrated against a measured
# max ledger-line extent -- deliberately generous (BUG-012 was a silent
# content-destruction bug, so this errs toward under-blanking, not over-).
BORDER_PROTECT_MARGIN_RATIO = 0.75

# ── Perspective correction (camera-photo specific) ────────────────────────────
# Corrects keystone/perspective distortion from off-axis phone photography —
# same rationale as oemer's own dewarp step. Deliberately strict: a missed or
# false quad must never warp the image, since a bad warp corrupts staff
# geometry for every downstream stage, whereas skipping just leaves today's
# (already-working) behavior in place.
PERSPECTIVE_CANNY_LOW        = 50
PERSPECTIVE_CANNY_HIGH       = 150
PERSPECTIVE_DILATE_KSIZE     = 5     # px; closes small gaps in the page-boundary edge
PERSPECTIVE_APPROX_EPS_FRAC  = 0.02  # fraction of contour perimeter for approxPolyDP
PERSPECTIVE_MIN_AREA_RATIO   = 0.6   # quad must cover >= this fraction of the frame
# A real camera photo of a page has visible background margin around it, so a
# genuine page-boundary quad sits inset from the frame edges. Tightly-cropped
# digital exports (e.g. Camera-PrIMuS strips) have content running edge-to-edge
# with no margin, so Canny's "large 4-point contour" there is just the image
# border itself — same area_ratio signature as a real page, but spurious.
# Gating on inset distinguishes the two without touching the area/shape checks
# that real page photos rely on.
PERSPECTIVE_MIN_MARGIN_FRAC  = 0.015  # quad's bbox must be inset from every frame edge by this fraction of that edge's length

# ── Staff-line tracking + page dewarp (camera-photo specific, BUG-001) ────────
# Phone photos of a held/curled page are not just rotated: staves drift, curve
# and change scale across the page (measured 3-4 deg tilt, up to ~80 px of
# vertical drift per staff, and a curled corner on some pages). correct_to_grid()
# fits ONE global angle, and blank_lyrics_regions() assumes every staff is a
# horizontal band -- on such pages the blanking erased whole real staves (seen on
# the Step-3 test set) before Stage 2 ever ran. Fix: follow each staff's actual
# 5-line curve, then remap the page so every staff is straight and horizontal.
# Applied only when the measured drift is real, so already-straight inputs
# (digital screenshots) take the exact pre-existing path.
STAFF_BLOCK_WIDTH        = 32     # px; column block over which line rows are projected
STAFF_BLOCK_STEP         = 16     # px; block stride (50% overlap)
STAFF_LINE_OPEN_KSIZE    = 13     # px; short horizontal opening -- short enough to survive ~5 deg slope
STAFF_LINE_MIN_FILL      = 0.45   # fraction of block width a row must be inked to count as a line row
STAFF_LINE_MAX_THICKNESS = 6      # px; taller ink runs are notes/text, not a staffline
STAFF_SPACING_MIN_PX     = 4.0    # plausible staffline spacing range at the <=1600px working scale
STAFF_SPACING_MAX_PX     = 30.0
STAFF_SPACING_TOL        = 0.25   # max relative spread of the 4 gaps inside one 5-line staff
STAFF_SPACING_TOL_ABS_PX = 2.5    # ...or this many px, whichever is larger
STAFF_HINT_SPACING_RANGE = (0.65, 1.35)  # 2nd pass: fitted line pitch must be within this multiple of the page's median spacing
STAFF_GRID_MAX_RESIDUAL_PX = 1.5  # 2nd pass: lines must sit on a uniform grid within this many px...
STAFF_GRID_OUTLIER_PX      = 5.0  # ...except ONE line (fused with a lyric underscore / beam) may be off by up to this
STAFF_DUPLICATE_SPACINGS   = 3.0  # curves closer than this many spacings over their shared x-range are the same staff
STAFF_TRACK_MAX_GAP_BLOCKS = 6    # blocks a track may be missed (notes/lyrics) before it is closed
STAFF_TRACK_LINK_TOL     = 0.6    # link tolerance, in staffline spacings per missed block (capped at 3)
STAFF_TRACK_MERGE_TOL    = 0.6    # broken-track merge: max extrapolation mismatch, in staff heights
STAFF_TRACK_MERGE_MAX_GAP_FRAC = 0.5  # broken pieces further apart than this fraction of page width are not merged
STAFF_TRACK_MIN_POINTS   = 8      # a raw track needs at least this many block detections
STAFF_MIN_SPAN_FRAC      = 0.3    # a real staff spans at least this fraction of the page width
STAFF_FIT_MAX_RESIDUAL_PX = 2.0   # RMS of the polynomial center-line fit; worse = not trusted
STAFF_FIT_OUTLIER_PX     = 2.5    # points further than this from the first fit are dropped and refit
STAFF_EXTRAP_SLOPE_SPAN_PX = 150  # px of track end used to estimate the slope for linear extrapolation
STAFF_EXT_STEP_PX        = 6      # end-extension step; small so a steeply curling staff is followed
STAFF_EXT_HALF_WIDTH_PX  = 4      # columns (each side) sampled, sheared along the predicted slope
STAFF_EXT_SEARCH_SPACINGS = 1.5   # +/- vertical search around the predicted center, in line spacings
STAFF_EXT_MIN_SCORE      = 0.65   # mean ink along the 5 predicted lines needed to accept a step
STAFF_EXT_MIN_CONTRAST   = 0.25   # line-position ink minus between-line ink, rejects solid blobs
STAFF_EXT_MAX_MISSES     = 3      # consecutive failed steps before giving up
STAFF_EXT_SLOPE_POINTS   = 5      # trailing points used to re-estimate the local slope
STAFF_PROTECT_MARGIN_SPACINGS = 1.25  # rows kept around a tracked staff (ledger lines, clef tails) when undoing over-blanking
DEWARP_MIN_DRIFT_PX      = 5.0    # skip dewarp unless some staff drifts at least this much (the dewarp step is a no-op on already-straight input; later masking still edits the page)
STAFF_LINES_PER_STAFF    = 5
STAFF_GROUP_TOL_ABS_PX   = 1.8    # 5-line grouping: absolute floor on the gap-match tolerance (px)...
STAFF_GROUP_TOL_REL      = 0.2    # ...or this fraction of the line gap, whichever is larger
STAFF_FIT_CUBIC_MIN_POINTS = 25   # enough block detections to trust a cubic center-line fit
STAFF_FIT_QUAD_MIN_POINTS  = 12   # enough for a quadratic; fewer falls back to a straight line
STAFF_PREDICT_POINTS     = 6      # trailing points used to predict where a track continues
STAFF_END_STATE_POINTS   = 8      # points nearest a track end used to estimate its end slope
KNOT_EPSILON_PX          = 1e-3   # per-knot nudge that keeps dewarp remap knots strictly increasing

# ── Working resolutions ───────────────────────────────────────────────────────
# Detection/tracking run on the 1600px page (every STAFF_* constant above was tuned there).
# Strips are cut from a SECOND, native-resolution page built through the same perspective and
# dewarp geometry. Measured (PIYA-121, DSMN page 1): downscaling the gray image and denoising
# cost nothing (rest-glyph correlation with the native gray 0.97, NLM identical), but
# binarizing the 1600px gray (rest strokes are ~1.6 px, partial-volume gray) drops thin
# strokes/line segments and re-thresholding after the gray dewarp bloats bands +24% ink mass;
# binarizing at native resolution and only then shrinking to the 64px strip keeps the mass at
# 1.00 (see docs/bug-tracker.md BUG-016).
DETECT_MAX_DIM = 1600            # px; detection / tracking working size
STRIP_SOURCE_MAX_DIM = 4032      # px; native phone resolution is kept up to this size
STRIP_SOURCE_BLUR_SIGMA_PER_SCALE = 0.4  # gaussian sigma per unit of native/detect scale: 1.0 px at the
                                         # 2.52x of a 4032px phone photo (measured), 0.8 (the old 3x3) at 1x
STRIP_SOURCE_BLUR_MIN_SIGMA_PX = 0.8
STRIP_SOURCE_BLOCK_SIZE_1600 = 31  # adaptive-threshold block at 1600px (see _binarize); scaled with the page
STRIP_SOURCE_THRESHOLD_C = 10     # same offset as _binarize

# ── Non-staff ink (lyric/text) mask, run once on the straightened page ────────
# Everything that is neither a tracked staff nor connected to one is removed. "Connected"
# means: a component of the ink (nothing subtracted, so beams/ties/rests cannot be cut off
# their stems or noteheads by a line-removal step) that has a pixel within MASK_ATTACH_TOL_SPACINGS
# of some tracked staff band. This replaces the old per-strip Stage 2 mask, whose staff-line
# opening treated thin flat beams and long ties as neighbouring staff lines.
MASK_ATTACH_TOL_SPACINGS = 0.75  # x line spacing; ink this close to a band counts as touching the staff
MASK_LINK_RADIUS_SPACINGS = 0.2  # x line spacing; gaps this small between ink pieces (ties/heads) are bridged
# Ledger-line notes: a notehead centred on a short ledger line floats 1+ spacings off the staff
# yet is content. Told apart from text by shape: compact glyph with ink on BOTH sides of one
# short horizontal line (a lyric extender/underscore has ink only above it).
LEDGER_MAX_REACH_SPACINGS = 3.5
LEDGER_RUN_MIN_SPACINGS = 1.2
LEDGER_RUN_MAX_SPACINGS = 3.0
LEDGER_MAX_HEIGHT_SPACINGS = 2.5
LEDGER_MAX_WIDTH_SPACINGS = 3.5
LEDGER_SIDE_MIN_SPACINGS = 0.25
LEDGER_THIN_ROW_FRAC = 0.8
LEDGER_MAX_LINE_SPACINGS = 0.3
# Ledger-line chain: ledger line k sits k line-spacings beyond the staff's outer line. A note on
# the 2nd+ ledger line fuses with its lines into one blob that fails the single-line shape test
# above, and a lone ledger line below such a note fixes its pitch, so a thin ledger-length run in
# ledger row k counts only if row k-1 (or the staff, for k=1) has an overlapping run.
LEDGER_CHAIN_MAX_LINES = 4
LEDGER_CHAIN_ROW_TOL_SPACINGS = 0.25  # x line spacing; tolerance on the k-spacing row position
LEDGER_CHAIN_MIN_OVERLAP_FRAC = 0.5   # fraction of a run that must sit over the previous run
# A staff the tracker missed has no band, so its ink would be deleted as "not attached". Any
# unattached component this wide that contains several long horizontal runs is staff-like and kept.
MASK_STAFFLIKE_MIN_WIDTH_FRAC = 0.15  # x page width
MASK_STAFFLIKE_MIN_RUNS = 3
STAFFLIKE_RUN_SPACINGS = 6.0  # a 'long horizontal run' is at least this many line spacings


@dataclass
class StaffCurve:
    """One tracked 5-line staff: center-line and line-spacing as functions of x.

    The polynomial is only trusted inside [x_min, x_max] (where lines were
    actually observed); outside it is extended linearly from the end slope,
    because a cubic extrapolated over hundreds of pixels diverges.
    """
    center_coeffs: np.ndarray   # np.polyfit coefficients of center-line y(x)
    spacing_coeffs: np.ndarray  # degree-1 coefficients of staffline spacing d(x)
    x_min: float
    x_max: float
    n_points: int
    rms_px: float

    def center_at(self, x: np.ndarray) -> np.ndarray:
        """Center-line y at columns x, linearly extended outside the observed span."""
        x = np.asarray(x, dtype=np.float64)
        y = np.polyval(self.center_coeffs, np.clip(x, self.x_min, self.x_max))
        lo_slope = self._end_slope(self.x_min, +1)
        hi_slope = self._end_slope(self.x_max, -1)
        y = np.where(x < self.x_min, y + lo_slope * (x - self.x_min), y)
        y = np.where(x > self.x_max, y + hi_slope * (x - self.x_max), y)
        return y

    def spacing_at(self, x: np.ndarray) -> np.ndarray:
        """Staffline spacing at columns x (clamped to the observed span)."""
        x = np.clip(np.asarray(x, dtype=np.float64), self.x_min, self.x_max)
        return np.maximum(np.polyval(self.spacing_coeffs, x), 1.0)

    def _end_slope(self, x_end: float, inward: int) -> float:
        span = min(float(STAFF_EXTRAP_SLOPE_SPAN_PX), self.x_max - self.x_min)
        if span <= 0:
            return 0.0
        x_in = x_end + inward * span
        return float((np.polyval(self.center_coeffs, x_in) - np.polyval(self.center_coeffs, x_end)) / (x_in - x_end))

    @property
    def mean_center(self) -> float:
        xs = np.linspace(self.x_min, self.x_max, 32)
        return float(np.mean(self.center_at(xs)))

    @property
    def drift_px(self) -> float:
        """Peak-to-peak vertical travel of the center-line over the observed span."""
        ys = self.center_at(np.linspace(self.x_min, self.x_max, 64))
        return float(ys.max() - ys.min())



@dataclass(frozen=True)
class StaffBand:
    """A tracked staff as the mask sees it, in the page's current (post-dewarp) geometry."""
    center: float
    spacing: float
    slack: float = 0.0  # residual vertical wander (px) of an un-dewarped staff


@dataclass
class PreprocessedPage:
    """Stage 1 result for one page.

    Attributes:
        detect: Binary page at DETECT_MAX_DIM for YOLO and the staff tracker (ink = 0).
        strip_source: Native-resolution binary page in the same (dewarped, masked) geometry, or
            None when the non-staff mask could not be applied (Stage 2 then cuts strips from
            ``detect``). Strips are cut from this page so thin glyphs (rests, flags, ties) are
            not lost to a 1600px binarization.
        angle: Staffline angle measured by correct_to_grid (degrees).
        mask_applied: Whether the non-staff-ink mask ran on this page.
        removed_px: Ink pixels removed by the mask at detection resolution (0 if not applied).
        strip_unmasked: Same page as ``strip_source`` before the mask (audit only; None unless
            keep_unmasked was requested).
        strip_staves: The tracked staves in ``strip_source`` pixels (audit only).
        strip_gray: The native normalized+dewarped gray page the strip source was thresholded
            from (audit only): the analog reference thin-glyph fidelity is measured against.
    """
    detect: np.ndarray
    strip_source: np.ndarray | None
    angle: float
    mask_applied: bool
    removed_px: int
    strip_unmasked: np.ndarray | None = None
    strip_staves: list[StaffBand] | None = None
    strip_gray: np.ndarray | None = None


def _band_row_mask(height: int, staves: list[StaffBand], tol_spacings: float) -> np.ndarray:
    """Bool per-row mask of the rows within `tol_spacings` of any staff's outer lines."""
    rows = np.zeros(height, dtype=bool)
    half = (STAFF_LINES_PER_STAFF - 1) / 2.0
    for s in staves:
        reach = (half + tol_spacings) * s.spacing + s.slack
        lo = max(0, int(np.floor(s.center - reach)))
        hi = min(height, int(np.ceil(s.center + reach)) + 1)
        rows[lo:hi] = True
    return rows


def _is_ledger_note(comp: np.ndarray, top: int, bottom: int, staves: list[StaffBand],
                    spacing: float) -> bool:
    """True if a detached component is a notehead sitting on a short ledger line.

    Args:
        comp: Bool mask of the component's ink inside its bounding box.
        top, bottom: Bounding-box rows on the page.
        staves: Tracked staves.
        spacing: Median line spacing.
    """
    half = (STAFF_LINES_PER_STAFF - 1) / 2.0
    gap = min(max(s.center - half * s.spacing - bottom, top - (s.center + half * s.spacing), 0.0)
              for s in staves)
    if gap > LEDGER_MAX_REACH_SPACINGS * spacing:
        return False
    height, width = comp.shape
    if height > LEDGER_MAX_HEIGHT_SPACINGS * spacing or width > LEDGER_MAX_WIDTH_SPACINGS * spacing:
        return False
    rows = comp.sum(axis=1)
    line_row = int(rows.argmax())
    if not LEDGER_RUN_MIN_SPACINGS * spacing <= rows[line_row] <= LEDGER_RUN_MAX_SPACINGS * spacing:
        return False
    thickness = int((rows >= LEDGER_THIN_ROW_FRAC * rows[line_row]).sum())
    if thickness > max(2, LEDGER_MAX_LINE_SPACINGS * spacing):
        return False
    side = LEDGER_SIDE_MIN_SPACINGS * spacing
    return line_row >= side and (height - line_row) >= side


def _is_staff_like(comp: np.ndarray, page_width: int, spacing: float) -> bool:
    """True if a wide detached component holds several long horizontal runs (an untracked staff)."""
    if comp.shape[1] < MASK_STAFFLIKE_MIN_WIDTH_FRAC * page_width:
        return False
    kernel = np.ones((1, max(int(round(STAFFLIKE_RUN_SPACINGS * spacing)), 3)), np.uint8)
    runs = cv2.morphologyEx(comp.astype(np.uint8), cv2.MORPH_OPEN, kernel).any(axis=1)
    groups = int(np.count_nonzero(runs[1:] & ~runs[:-1])) + int(runs[0])
    return groups >= MASK_STAFFLIKE_MIN_RUNS


def _ledger_chain_labels(ink: np.ndarray, labels: np.ndarray, heights: np.ndarray,
                         staves: list[StaffBand], spacing: float) -> np.ndarray:
    """Labels of components that hold a valid chain of ledger-line runs above or below a staff.

    A component qualifies as a lone thin line (a ledger line with no note on it) or when its
    runs cover two or more ledger rows (a note fused with its lines). A lyric word whose
    baseline happens to sit in one ledger row does neither, so it stays erasable.

    Args:
        ink: Bool ink mask of the page.
        labels: Component labels of the gap-bridged ink.
        heights: Ink-only bounding-box height per label.
        staves: Tracked staves.
        spacing: Median line spacing.

    Returns:
        Sorted unique component labels (0 never included).
    """
    height, width = ink.shape
    half = (STAFF_LINES_PER_STAFF - 1) / 2.0
    min_len = max(int(round(LEDGER_RUN_MIN_SPACINGS * spacing)), 3)
    max_len = int(round(LEDGER_RUN_MAX_SPACINGS * spacing))
    kernel = np.ones((1, min_len), np.uint8)
    rows_hit: dict[int, set[tuple[int, int, int]]] = {}
    thin_max = max(2, int(np.ceil(LEDGER_MAX_LINE_SPACINGS * spacing)))
    for si, s in enumerate(staves):
        tol = LEDGER_CHAIN_ROW_TOL_SPACINGS * s.spacing + s.slack
        for sign in (-1, 1):
            previous = [(0, width)]  # the staff itself spans the page
            for k in range(1, LEDGER_CHAIN_MAX_LINES + 1):
                centre = s.center + sign * (half + k) * s.spacing
                lo, hi = max(0, int(np.floor(centre - tol))), min(height, int(np.ceil(centre + tol)) + 1)
                if hi <= lo:
                    break
                runs = cv2.morphologyEx(ink[lo:hi].astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)
                cols = runs.any(axis=0)
                edges = np.flatnonzero(np.diff(np.concatenate(([0], cols.view(np.int8), [0]))))
                valid: list[tuple[int, int]] = []
                for x0, x1 in zip(edges[::2], edges[1::2]):
                    overlap = max((min(x1, b) - max(x0, a) for a, b in previous), default=0)
                    if x1 - x0 <= max_len and overlap >= LEDGER_CHAIN_MIN_OVERLAP_FRAC * (x1 - x0):
                        valid.append((int(x0), int(x1)))
                        for lab in np.unique(labels[lo:hi, x0:x1][runs[:, x0:x1]]):
                            rows_hit.setdefault(int(lab), set()).add((si, sign, k))
                if not valid:
                    break
                previous = valid
    return np.array(sorted(lab for lab, hit in rows_hit.items()
                           if lab > 0 and (len(hit) >= 2 or heights[lab] <= thin_max)), dtype=labels.dtype)


def non_staff_ink_mask(binary: np.ndarray, staves: list[StaffBand]) -> np.ndarray:
    """Finds ink that is neither a tracked staff nor connected to one (lyrics, titles, dust).

    Runs on the straightened page. Connectivity is decided on the ink itself, gap-bridged by
    MASK_LINK_RADIUS_SPACINGS, with nothing subtracted first: beams, ties, flags and rests stay
    joined to the stems/noteheads that are on the staff, so they cannot be mistaken for
    neighbouring lines or text. A component is kept if it has a pixel within
    MASK_ATTACH_TOL_SPACINGS of any tracked staff's outer lines, holds a chain of ledger lines
    leading away from a staff, or looks like a ledger-line note or an untracked staff.

    Args:
        binary: Page, ink = 0.
        staves: Tracked staves (at least one).

    Returns:
        Bool mask of the ink pixels to erase.
    """
    ink = binary < 128
    if not staves or not ink.any():
        return np.zeros(ink.shape, dtype=bool)
    height, width = ink.shape
    spacing = float(np.median([s.spacing for s in staves]))
    band_rows = _band_row_mask(height, staves, MASK_ATTACH_TOL_SPACINGS)

    link = max(1, int(round(MASK_LINK_RADIUS_SPACINGS * spacing)))
    linked = cv2.dilate(ink.astype(np.uint8),
                        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * link + 1, 2 * link + 1)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(linked, connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[np.unique(labels[band_rows])] = True
    ink_heights = np.zeros(count, dtype=np.int64)
    for i in range(1, count):
        rows = np.flatnonzero(ink[stats[i, cv2.CC_STAT_TOP]:stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT]]
                              [:, stats[i, cv2.CC_STAT_LEFT]:stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH]].any(axis=1))
        ink_heights[i] = (rows[-1] - rows[0] + 1) if rows.size else 0
    keep[_ledger_chain_labels(ink, labels, ink_heights, staves, spacing)] = True
    for i in range(1, count):
        if keep[i]:
            continue
        left, top = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
        w_i, h_i = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        if w_i < LEDGER_RUN_MIN_SPACINGS * spacing and w_i < MASK_STAFFLIKE_MIN_WIDTH_FRAC * width:
            continue  # narrower than any ledger line and than an untracked staff: text speck
        comp = (labels[top:top + h_i, left:left + w_i] == i) & ink[top:top + h_i, left:left + w_i]
        keep[i] = (_is_ledger_note(comp, top, top + h_i, staves, spacing)
                   or _is_staff_like(comp, width, spacing))
    keep[0] = False
    return ink & ~keep[labels]


def _border_region(shape: tuple[int, int], border_rows: np.ndarray, left_px: int, right_px: int) -> np.ndarray:
    """Bool region blanked by the border step on the detection page (transferred to native)."""
    region = np.zeros(shape, dtype=bool)
    region[border_rows, :] = True
    region[:, :left_px] = True
    if right_px > 0:
        region[:, -right_px:] = True
    return region


def preprocess_score_image(image_path: str, save_debug: bool = False) -> tuple:
    """Backward-compatible wrapper: returns (detection-resolution binary page, angle)."""
    page = preprocess_score_page(image_path, save_debug=save_debug, build_strip_source=False)
    return page.detect, page.angle


def _odd(value: float) -> int:
    """Nearest odd integer >= 3 (adaptive-threshold block sizes must be odd)."""
    return max(3, int(round(value)) | 1)


def preprocess_score_page(
    image_path: str,
    save_debug: bool = False,
    mask_non_staff_ink: bool = True,
    build_strip_source: bool = True,
    keep_unmasked: bool = False,
) -> PreprocessedPage:
    """Runs Stage 1 on one photo.

    Args:
        image_path: Input photo.
        save_debug: Write intermediate images next to the input.
        mask_non_staff_ink: Remove lyrics/text/dust not connected to a tracked staff (runs on
            the straightened page). Needs at least one tracked staff.
        build_strip_source: Also build the native-resolution page used for strips (requires the
            mask to have been applied).
        keep_unmasked: Also return the native page before the mask and its staves, for auditing
            what the mask removed.

    Returns:
        A PreprocessedPage.
    """
    img_path = Path(image_path)
    full = cv2.imread(str(img_path))
    if full is None:
        raise ValueError(f"Could not read image: {image_path}")

    # Step 0: Downscale large phone images to the detection size; keep a native-resolution copy
    # (capped at STRIP_SOURCE_MAX_DIM) for the strip source.
    bgr = full
    ph, pw = bgr.shape[:2]
    if max(ph, pw) > DETECT_MAX_DIM:
        scale = DETECT_MAX_DIM / max(ph, pw)
        bgr = cv2.resize(bgr, (int(pw * scale), int(ph * scale)),
                         interpolation=cv2.INTER_AREA)
        print(f"[Stage 1] Downscaled {ph}x{pw} -> {bgr.shape[0]}x{bgr.shape[1]}")
    hi = full
    if max(ph, pw) > STRIP_SOURCE_MAX_DIM:
        scale = STRIP_SOURCE_MAX_DIM / max(ph, pw)
        hi = cv2.resize(full, (int(pw * scale), int(ph * scale)), interpolation=cv2.INTER_AREA)
    pre_k = (hi.shape[1] / bgr.shape[1], hi.shape[0] / bgr.shape[0])

    # Step 0.5: Perspective correction — must run here, on the raw color image,
    # for two reasons: (1) it needs intact page-boundary edges to find the quad
    # via Canny, and Step 1-3 (grayscale/normalize/threshold) exist to isolate
    # *staffline ink*, not the page silhouette, so running this after them would
    # mean warping a binary ink mask instead of correcting the source geometry;
    # (2) it must precede Step 4's correct_to_grid(), which only fits a single
    # in-plane rotation angle from Hough line angles and can't correct true
    # perspective skew — worse, uncorrected perspective can bias that angle
    # estimate, since stafflines converging toward a vanishing point don't all
    # measure the same angle.
    bgr, persp = _correct_perspective(bgr)
    if persp is not None:
        # Conjugate the matrix by the detect->native scale so the native page gets the same warp.
        s_m = np.diag([pre_k[0], pre_k[1], 1.0])
        hi = cv2.warpPerspective(
            hi, s_m @ persp @ np.linalg.inv(s_m),
            (int(round(bgr.shape[1] * pre_k[0])), int(round(bgr.shape[0] * pre_k[1]))),
            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    _dbg_save(save_debug, img_path, bgr, "0a_perspective")

    # Step 1: Grayscale
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _dbg_save(save_debug, img_path, gray, "1_gray")

    # Step 1.5: Illumination normalization — corrects uneven lighting/shadow
    # gradients common in phone photos, before thresholding ever sees them.
    bg = cv2.morphologyEx(
        gray, cv2.MORPH_DILATE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (BG_NORM_KERNEL_SIZE, BG_NORM_KERNEL_SIZE))
    )
    normalized = cv2.divide(gray, bg, scale=255)
    normalized = cv2.GaussianBlur(normalized, (BG_NORM_BLUR_KSIZE, BG_NORM_BLUR_KSIZE), 0)
    _dbg_save(save_debug, img_path, normalized, "1a_normalized")

    # Step 2: Denoise
    denoised = cv2.fastNlMeansDenoising(normalized, h=7)
    _dbg_save(save_debug, img_path, denoised, "2_denoised")

    # Step 3: Binarize
    binary = _binarize(denoised)

    # Step 3.05: Staff-line tracking + dewarp (BUG-001). Must precede border/lyric
    # blanking and Step 4: those assume straight horizontal staves and, on a
    # tilted/curled camera page, erase real staves (blank_lyrics_regions) or
    # apply one wrong global angle (correct_to_grid). The remap is applied to the
    # denoised grayscale and re-binarized, not to the binary image, so thin
    # stafflines are interpolated rather than aliased. Skipped (bit-identical
    # to the old path) when no staff drifts >= DEWARP_MIN_DRIFT_PX.
    curves = track_staff_curves(binary)
    dewarped = needs_dewarp(curves)
    map_y: np.ndarray | None = None
    if dewarped:
        print(f"[Dewarp] {len(curves)} staff curve(s), max drift "
              f"{max(c.drift_px for c in curves):.1f}px -> straightening staves")
        _dbg_save(save_debug, img_path, _draw_staff_curves(binary, curves), "3_staff_tracks")
        map_y = staff_grid_map(denoised.shape, curves)
        denoised = _remap_rows(denoised, map_y)
        binary = _binarize(denoised)
    else:
        print(f"[Dewarp] {len(curves)} staff curve(s), no significant drift -> unchanged")

    # Step 3.1: Blank edge bands — kills hand/table-shadow/book-spine artifacts
    # near page borders.
    # Top/bottom are content-aware: a fixed-pixel blank is only safe on camera
    # photos, which have real background margin around the page — tightly-cropped
    # digital exports can have real staff content right up to the edge, so only
    # blank border rows that don't already look like a real staffline (same
    # detection signal used elsewhere in this file).
    # Left/right are NOT content-aware the same way — there is no equivalent
    # of "already looks like a staffline" for a narrow vertical band that
    # reliably tells a real clef/barline stroke apart from thresholded shadow
    # ink, and Stage 1 doesn't yet know where staves/clefs are (that's Stage
    # 2's job) to gate on real symbol locations instead. Risk is mitigated,
    # not eliminated, by keeping BORDER_LEFT_PX deliberately small (see
    # comment above) rather than by content detection. Bounds-guarded so a
    # page narrower than the border constants can't blank its entire width.
    pre_blank = binary.copy()
    border_rows = _border_rows_to_blank(binary, BORDER_TOP_PX, BORDER_BOTTOM_PX)
    binary[border_rows, :] = 255
    left_px = min(BORDER_LEFT_PX, binary.shape[1])
    binary[:, :left_px] = 255
    right_px = min(BORDER_RIGHT_PX, binary.shape[1])
    if right_px > 0:
        binary[:, -right_px:] = 255

    _dbg_save(save_debug, img_path, binary, "3_binary")

    # Step 3.15: Non-staff ink (lyric/text) mask, on the straightened page. Post-dewarp each
    # staff sits at its curve's mean_center with median spacing (see staff_grid_map); an
    # un-dewarped staff drifts < DEWARP_MIN_DRIFT_PX, half of which is carried as band slack.
    staves = [StaffBand(
        center=c.mean_center,
        spacing=float(np.median(c.spacing_at(np.linspace(c.x_min, c.x_max, 32)))),
        slack=0.0 if dewarped else c.drift_px / 2.0) for c in curves]
    remove: np.ndarray | None = None
    removed_px = 0
    if mask_non_staff_ink and staves:
        candidate_remove = non_staff_ink_mask(binary, staves)
        candidate = binary.copy()
        candidate[candidate_remove] = 255
        # A staff the tracker missed has no band; the staff-like rule protects most of those and
        # this recount catches any that would still be damaged.
        if len(track_staff_curves(candidate)) >= len(curves):
            remove, removed_px = candidate_remove, int(candidate_remove.sum())
            print(f"[Mask] {len(staves)} tracked staff(s): removed {removed_px} px of non-staff ink.")
            binary = candidate
            pre_blank[candidate_remove] = 255  # keep the row-restore below from resurrecting it
        else:
            logger.warning("non-staff mask changed the tracked staff count on %s; mask discarded",
                           img_path.name)
    elif mask_non_staff_ink:
        logger.warning("no tracked staves on %s; non-staff mask skipped", img_path.name)

    # Step 3.2: Blank lyrics (kept for the detection page; YOLO/tracker now see the masked page, staff counts on the 6 screenshots were unchanged;
    # strips do not use this page's ink, they come from the strip source).
    binary = blank_lyrics_regions(binary)

    # Step 3.3: Undo blanking that erased tracked staves (BUG-001). The band
    # heuristics above merge/misjudge bands on camera pages and wipe whole staves
    # (e.g. a tenor staff between two lyric lines). The tracker's staves are
    # independently verified 5-line groups, so their rows are never blank-worthy.
    # Side columns are re-blanked so shadow ink is not resurrected with them.
    if curves:
        binary = _restore_staff_rows(binary, pre_blank, [(b.center, b.spacing) for b in staves])
        binary[:, :left_px] = 255
        if right_px > 0:
            binary[:, -right_px:] = 255
    _dbg_save(save_debug, img_path, binary, "3a_blanked")

    strip_source: np.ndarray | None = None
    unmasked: np.ndarray | None = None
    hi_staves: list[StaffBand] | None = None
    strip_gray: np.ndarray | None = None
    if build_strip_source and remove is not None:
        strip_source, unmasked, hi_staves, strip_gray = _build_strip_source(
            hi, bg, map_y, _border_region(binary.shape, border_rows, left_px, right_px), staves)

    # Step 4: Grid alignment using stafflines + barlines
    # After a dewarp the staves are horizontal by construction; a further global
    # rotation (esp. the barline-angle average, which measures perspective lean,
    # not staff tilt) would only re-tilt them, so angles are measured but not applied.
    corrected, h_angle, v_angle = correct_to_grid(binary, bgr, apply_rotation=not dewarped)
    _dbg_save(save_debug, img_path, corrected, "4_corrected")
    print(f"[Stage 1] '{img_path.name}' -> h={h_angle:.2f} deg v={v_angle:.2f} deg")
    if strip_source is not None and not dewarped:
        rot = grid_correction_deg(h_angle, v_angle)
        if abs(rot) > GRID_ROTATION_MIN_DEG:
            sh, sw = strip_source.shape
            rot_m = cv2.getRotationMatrix2D((sw // 2, sh // 2), -rot, 1.0)
            strip_source = cv2.warpAffine(strip_source, rot_m, (sw, sh), flags=cv2.INTER_NEAREST,
                                          borderMode=cv2.BORDER_REPLICATE)
            if unmasked is not None:
                unmasked = cv2.warpAffine(unmasked, rot_m, (sw, sh), flags=cv2.INTER_NEAREST,
                                          borderMode=cv2.BORDER_REPLICATE)
            if strip_gray is not None:
                strip_gray = cv2.warpAffine(strip_gray, rot_m, (sw, sh), flags=cv2.INTER_LINEAR,
                                            borderMode=cv2.BORDER_REPLICATE)

    return PreprocessedPage(corrected, strip_source, h_angle, remove is not None, removed_px,
                            unmasked if keep_unmasked else None, hi_staves if keep_unmasked else None,
                            strip_gray if keep_unmasked else None)


def _build_strip_source(hi: np.ndarray, bg: np.ndarray, map_y: np.ndarray | None,
                        border_lo: np.ndarray, staves: list[StaffBand]
                        ) -> tuple[np.ndarray, np.ndarray, list[StaffBand], np.ndarray]:
    """Builds the native-resolution, lyric-masked binary page in the detection page's geometry.

    Same steps as the detection path (normalize, dewarp with the same tracked curves,
    adaptive threshold, border blank) but at native resolution, then the same non-staff mask
    decided again on the native ink. It is decided again, not transferred from the 1600px page:
    native-only specks (dust) and thin strokes the 1600px binarization dropped need a verdict
    too, and components are whole here so no erase halo is needed.

    Args:
        hi: Perspective-corrected native BGR page.
        bg: Local-background estimate from the detection page (a smooth field, so upsampling it
            is accurate enough and avoids a 12 MP morphological dilation).
        map_y: Detection-resolution dewarp row map, or None if the page was not dewarped.
        border_lo: Detection-resolution region blanked by the border step.
        staves: Tracked staves in detection pixels.

    Returns:
        (masked page, page before the mask, staves in native pixels, normalized dewarped gray).
    """
    gray = cv2.cvtColor(hi, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = h / bg.shape[0]
    norm = cv2.divide(gray, cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR), scale=255)
    sigma = max(STRIP_SOURCE_BLUR_MIN_SIGMA_PX, STRIP_SOURCE_BLUR_SIGMA_PER_SCALE * scale)
    norm = cv2.GaussianBlur(norm, (0, 0), sigma)
    if map_y is not None:
        norm = _remap_rows(norm, map_y)
    binary = cv2.adaptiveThreshold(
        norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        _odd(STRIP_SOURCE_BLOCK_SIZE_1600 * scale), STRIP_SOURCE_THRESHOLD_C)
    binary[cv2.resize(border_lo.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0] = 255
    # Pixel-centre mapping between the two grids (same convention as _remap_rows).
    hi_staves = [StaffBand(scale * (s.center + 0.5) - 0.5, s.spacing * scale, s.slack * scale)
                 for s in staves]
    unmasked = binary.copy()
    binary[non_staff_ink_mask(binary, hi_staves)] = 255
    return binary, unmasked, hi_staves, norm


def _restore_staff_rows(
    blanked: np.ndarray, original: np.ndarray, staves: list[tuple[float, float]]
) -> np.ndarray:
    """Copies each tracked staff's row band (plus margin) from `original` into `blanked`.

    Args:
        blanked: Binary page after border/lyric blanking.
        original: Same page before any blanking.
        staves: (center_y, line_spacing) per tracked staff, in the page's current geometry.

    Returns:
        A copy of `blanked` with the staff bands restored.
    """
    h = blanked.shape[0]
    out = blanked.copy()
    half = (STAFF_LINES_PER_STAFF - 1) / 2.0 + STAFF_PROTECT_MARGIN_SPACINGS
    for center, spacing in staves:
        lo = max(0, int(round(center - half * spacing)))
        hi = min(h, int(round(center + half * spacing)) + 1)
        out[lo:hi, :] = original[lo:hi, :]
    return out


def correct_perspective(bgr: np.ndarray) -> np.ndarray:
    """Image-only wrapper around _correct_perspective (kept for existing callers)."""
    return _correct_perspective(bgr)[0]


def _correct_perspective(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    """Warps a photographed page to a fronto-parallel rectangle, if confident.

    Looks for a single large convex quadrilateral (the page boundary) via
    Canny edges + contour approximation. Camera photos of sheet music vary
    wildly in framing — the page often fills the whole frame with no visible
    boundary, or background clutter/lighting produces spurious contours — so
    this only acts when the evidence is strong (large, convex, exactly 4
    corners). Anything weaker is left untouched: a false positive here would
    warp a page that didn't need it and corrupt staff geometry for every
    downstream stage, which is worse than doing nothing.

    Args:
        bgr: Post-downscale BGR image, prior to any grayscale/threshold step.

    Returns:
        (image, matrix): the perspective-corrected BGR image and the 3x3 warp matrix that
        produced it, or (`bgr`, None) if no confident page-boundary quad was found. The matrix
        lets the native-resolution strip source be warped identically.
    """
    h, w = bgr.shape[:2]
    frame_area = float(h * w)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, PERSPECTIVE_CANNY_LOW, PERSPECTIVE_CANNY_HIGH)
    edges = cv2.dilate(
        edges,
        cv2.getStructuringElement(cv2.MORPH_RECT, (PERSPECTIVE_DILATE_KSIZE, PERSPECTIVE_DILATE_KSIZE))
    )

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        print("[Perspective] no contours found — leaving image unchanged")
        return bgr, None

    largest = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, PERSPECTIVE_APPROX_EPS_FRAC * perimeter, True)

    if len(approx) != 4:
        print(f"[Perspective] largest contour approximates to {len(approx)} points, "
              f"not 4 — leaving image unchanged")
        return bgr, None

    if not cv2.isContourConvex(approx):
        print("[Perspective] 4-point contour is not convex — leaving image unchanged")
        return bgr, None

    quad_area = cv2.contourArea(approx)
    area_ratio = quad_area / frame_area
    if area_ratio < PERSPECTIVE_MIN_AREA_RATIO:
        print(f"[Perspective] quad covers only {area_ratio:.2f} of frame "
              f"(need >= {PERSPECTIVE_MIN_AREA_RATIO}) — leaving image unchanged")
        return bgr, None

    # Margin-inset gate: reject quads flush (or nearly flush) against the
    # frame border. A tightly-cropped strip with no real background margin
    # produces exactly this shape — high area_ratio, convex, 4 points — from
    # Canny picking up the image's own edge rather than a photographed page
    # boundary, so area/shape alone can't tell the two apart.
    margin_x = PERSPECTIVE_MIN_MARGIN_FRAC * w
    margin_y = PERSPECTIVE_MIN_MARGIN_FRAC * h
    qx, qy = approx.reshape(4, 2)[:, 0], approx.reshape(4, 2)[:, 1]
    min_x, max_x = float(qx.min()), float(qx.max())
    min_y, max_y = float(qy.min()), float(qy.max())
    if min_x < margin_x or min_y < margin_y or max_x > (w - margin_x) or max_y > (h - margin_y):
        print(f"[Perspective] quad touches frame border (bbox x=[{min_x:.0f},{max_x:.0f}] "
              f"y=[{min_y:.0f},{max_y:.0f}] of {w}x{h}, need >= {margin_x:.0f}px/{margin_y:.0f}px "
              f"margin) — leaving image unchanged")
        return bgr, None

    tl, tr, br, bl = _order_quad_points(approx.reshape(4, 2).astype(np.float32))

    dst_w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    dst_h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if dst_w <= 0 or dst_h <= 0:
        print("[Perspective] degenerate quad (zero width/height) — leaving image unchanged")
        return bgr, None

    src_pts = np.array([tl, tr, br, bl], dtype=np.float32)
    dst_pts = np.array([
        [0, 0],
        [dst_w - 1, 0],
        [dst_w - 1, dst_h - 1],
        [0, dst_h - 1],
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(
        bgr, M, (dst_w, dst_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE
    )
    print(f"[Perspective] quad detected (area_ratio={area_ratio:.2f}) -> warped to {dst_w}x{dst_h}")
    return warped, M


def _order_quad_points(pts: np.ndarray) -> np.ndarray:
    """Orders 4 arbitrary quad corner points into (top-left, top-right, bottom-right, bottom-left).

    Standard sum/diff trick: top-left has the smallest x+y and bottom-right
    the largest; top-right has the smallest y-x and bottom-left the largest.
    """
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _staff_line_open_mask(binary: np.ndarray) -> np.ndarray:
    """Ink pixels that survive a short horizontal opening (candidate staffline pixels).

    Deliberately much shorter than `_staff_line_mask()`'s 15%-of-width kernel:
    a long kernel only keeps lines that are straight across a sixth of the
    page, which is exactly what a tilted/curled staff is not.
    """
    ink = cv2.bitwise_not(binary)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (STAFF_LINE_OPEN_KSIZE, 1))
    return cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)


def _find_line_rows(profile: np.ndarray) -> list[float]:
    """Centroid rows of thin, strongly-inked runs in a per-block row profile."""
    on = profile >= STAFF_LINE_MIN_FILL * STAFF_BLOCK_WIDTH
    peaks: list[float] = []
    y, n = 0, len(on)
    while y < n:
        if not on[y]:
            y += 1
            continue
        y_end = y
        while y_end < n and on[y_end]:
            y_end += 1
        if y_end - y <= STAFF_LINE_MAX_THICKNESS:
            weights = profile[y:y_end]
            peaks.append(float(y + (np.arange(y_end - y) * weights).sum() / weights.sum()))
        y = y_end
    return peaks


def _group_five_lines(peaks: list[float]) -> list[tuple[float, float]]:
    """Finds runs of 5 equally spaced line rows; returns (center_y, spacing) each.

    Requiring five *equally spaced* lines is what separates a staff from
    lyric underscores, hairpins, beams and text baselines, none of which
    come in evenly spaced fives.
    """
    found: list[tuple[float, float]] = []
    n, i = len(peaks), 0
    while i < n - (STAFF_LINES_PER_STAFF - 1):
        matched = False
        for j in range(i + 1, n):
            gap = peaks[j] - peaks[i]
            if gap < STAFF_SPACING_MIN_PX:
                continue
            if gap > STAFF_SPACING_MAX_PX:
                break
            chain, last = [i, j], j
            for _ in range(STAFF_LINES_PER_STAFF - 2):
                target = peaks[last] + gap
                tol = max(STAFF_GROUP_TOL_ABS_PX, STAFF_GROUP_TOL_REL * gap)
                cands = [m for m in range(last + 1, n) if abs(peaks[m] - target) <= tol]
                if not cands:
                    break
                last = min(cands, key=lambda m: abs(peaks[m] - target))
                chain.append(last)
            if len(chain) != STAFF_LINES_PER_STAFF:
                continue
            ys = np.array([peaks[m] for m in chain])
            gaps = np.diff(ys)
            if gaps.max() - gaps.min() <= max(STAFF_SPACING_TOL_ABS_PX, STAFF_SPACING_TOL * gaps.mean()):
                found.append((float(ys.mean()), float(gaps.mean())))
                i = chain[-1] + 1
                matched = True
                break
        if not matched:
            i += 1
    return found


def _fit_uniform_grid(group: np.ndarray, pitch_lo: float, pitch_hi: float) -> tuple[float, float, float] | None:
    """Fits 5 line rows to a uniform grid, tolerating one displaced line.

    Returns (center, pitch, score) or None. The center comes from the grid fit,
    not the mean of the rows, so one displaced line cannot bias it.
    """
    k = np.arange(STAFF_LINES_PER_STAFF, dtype=np.float64)
    best: tuple[float, float, float] | None = None
    for drop in (None, *range(STAFF_LINES_PER_STAFF)):
        idx = np.array([m for m in range(STAFF_LINES_PER_STAFF) if m != drop])
        pitch, offset = np.polyfit(k[idx], group[idx], 1)
        if not pitch_lo <= pitch <= pitch_hi:
            continue
        residual = float(np.abs(group[idx] - (offset + pitch * k[idx])).max())
        if residual > STAFF_GRID_MAX_RESIDUAL_PX:
            continue
        penalty = 0.0
        if drop is not None:
            if abs(group[drop] - (offset + pitch * drop)) > STAFF_GRID_OUTLIER_PX:
                continue
            penalty = 0.5
        score = residual + penalty
        if best is None or score < best[2]:
            best = (float(offset + pitch * (STAFF_LINES_PER_STAFF - 1) / 2.0), float(pitch), score)
    return best


def _group_five_lines_with_hint(peaks: list[float], spacing: float) -> list[tuple[float, float]]:
    """Second-pass staff grouping once the page's typical spacing is known.

    The strict first pass rejects a staff whose lines are uneven by even a few
    px, which real perspective/curl and a fused lyric underscore produce
    (measured 12/9/9/8 px on one staff, and a 5th line displaced 3 px on
    others) -- that dropped whole staves. With the page spacing as a prior,
    five consecutive line rows that fit a uniform grid (one outlier allowed)
    are enough. Overlapping candidates are resolved by best grid fit so a stray
    line just above/below a staff cannot displace the real five.
    """
    lo, hi = STAFF_HINT_SPACING_RANGE[0] * spacing, STAFF_HINT_SPACING_RANGE[1] * spacing
    cands: list[tuple[float, int, float, float]] = []
    for i in range(len(peaks) - (STAFF_LINES_PER_STAFF - 1)):
        fit = _fit_uniform_grid(np.array(peaks[i:i + STAFF_LINES_PER_STAFF]), lo, hi)
        if fit is not None:
            cands.append((fit[2], i, fit[0], fit[1]))
    cands.sort()
    taken: set[int] = set()
    found: list[tuple[float, float]] = []
    for _, i, center, pitch in cands:
        idx = set(range(i, i + STAFF_LINES_PER_STAFF))
        if idx & taken:
            continue
        taken |= idx
        found.append((center, pitch))
    return sorted(found)


def _predict_track_y(track: dict, x: float) -> float:
    """Predicts a track's center y at column x from a line through its last points."""
    pts = track["pts"][-STAFF_PREDICT_POINTS:]
    if len(pts) >= 3:
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        slope, intercept = np.polyfit(xs, ys, 1)
        return float(slope * x + intercept)
    return float(pts[-1][1])


def _link_block_detections(per_block: list[list[tuple[float, float, float]]], spacing: float) -> list[dict]:
    """Greedily links per-block staff detections (x, center, spacing) left-to-right into tracks."""
    tracks: list[dict] = []
    for block_idx, dets in enumerate(per_block):
        active = [t for t in tracks if block_idx - t["last"] <= STAFF_TRACK_MAX_GAP_BLOCKS]
        pairs = []
        for di, (x, c, _) in enumerate(dets):
            for ti, t in enumerate(active):
                err = abs(c - _predict_track_y(t, x))
                gap = block_idx - t["last"]
                if err <= STAFF_TRACK_LINK_TOL * spacing * min(gap, 3) + 1.5:
                    pairs.append((err, di, ti))
        pairs.sort()
        used_d: set[int] = set()
        used_t: set[int] = set()
        for _, di, ti in pairs:
            if di in used_d or ti in used_t:
                continue
            used_d.add(di)
            used_t.add(ti)
            active[ti]["pts"].append(dets[di])
            active[ti]["last"] = block_idx
        for di, det in enumerate(dets):
            if di not in used_d:
                tracks.append({"pts": [det], "last": block_idx})
    return tracks


def _end_state(track: dict, at_end: bool) -> tuple[float, float, float]:
    """(x, y, slope) at one end of a track, slope from the STAFF_END_STATE_POINTS points nearest that end."""
    pts = track["pts"][-STAFF_END_STATE_POINTS:] if at_end else track["pts"][:STAFF_END_STATE_POINTS]
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    slope = float(np.polyfit(xs, ys, 1)[0]) if len(pts) >= 3 and np.ptp(xs) > 0 else 0.0
    idx = -1 if at_end else 0
    return float(pts[idx][0]), float(pts[idx][1]), slope


def _merge_broken_tracks(tracks: list[dict], spacing: float, width: int) -> list[dict]:
    """Rejoins pieces of one staff that tracking lost across a notes/lyrics/curl gap.

    Two pieces merge only when each one's end-slope extrapolation lands near
    the other -- staves are >= ~6 spacings apart, so a mismatch tolerance of a
    staff height cannot bridge two different staves.
    """
    tracks = sorted(tracks, key=lambda t: t["pts"][0][0])
    tol = STAFF_TRACK_MERGE_TOL * STAFF_LINES_PER_STAFF * spacing
    merged_any = True
    while merged_any:
        merged_any = False
        best = None
        for a in range(len(tracks)):
            for b in range(len(tracks)):
                if a == b:
                    continue
                xa, ya, sa = _end_state(tracks[a], True)
                xb, yb, sb = _end_state(tracks[b], False)
                gap = xb - xa
                if gap < -STAFF_BLOCK_WIDTH or gap > STAFF_TRACK_MERGE_MAX_GAP_FRAC * width:
                    continue
                err = max(abs(ya + sa * gap - yb), abs(yb - sb * gap - ya))
                if err <= tol and (best is None or err < best[0]):
                    best = (err, a, b)
        if best is not None:
            _, a, b = best
            joined = {"pts": sorted(tracks[a]["pts"] + tracks[b]["pts"], key=lambda p: p[0]), "last": 0}
            tracks = [t for k, t in enumerate(tracks) if k not in (a, b)] + [joined]
            merged_any = True
    return tracks


def _staff_ink_score(ink: np.ndarray, x: int, y_c: float, d: float, slope: float) -> float:
    """Line-vs-gap ink contrast of a 5-line staff of center y_c, spacing d, tilted by `slope` at column x.

    Samples a narrow column window sheared along `slope` on the *unopened* ink
    mask: the 13px horizontal opening used elsewhere erases lines steeper than
    ~0.4, which is precisely the curled staff end this is meant to follow.
    """
    h, w = ink.shape
    xs = np.arange(max(0, x - STAFF_EXT_HALF_WIDTH_PX), min(w, x + STAFF_EXT_HALF_WIDTH_PX + 1))
    if len(xs) == 0:
        return 0.0
    line_hits, gap_hits = [], []
    for k in range(-2, 3):
        y = np.rint(y_c + k * d + slope * (xs - x)).astype(int)
        line_hits.append(ink[np.clip(y, 0, h - 1), xs].mean() / 255.0)
    for k in (-1.5, -0.5, 0.5, 1.5):
        y = np.rint(y_c + k * d + slope * (xs - x)).astype(int)
        gap_hits.append(ink[np.clip(y, 0, h - 1), xs].mean() / 255.0)
    line_score = float(np.mean(line_hits))
    if line_score < STAFF_EXT_MIN_SCORE or min(line_hits) < 0.3:
        return 0.0
    return line_score - float(np.mean(gap_hits))


def _extend_track_ends(
    ink: np.ndarray, pts: list[tuple[float, float, float]], width: int
) -> list[tuple[float, float, float]]:
    """Follows a staff past both ends of its tracked span, including steep page curl.

    Block tracking loses a staff where it curls faster than the block width
    tolerates; the clef and key signature live exactly there. From each end,
    step outward re-estimating the local slope from the last few accepted
    points, and accept a step only when the 5 predicted lines carry ink and the
    gaps between them do not (so a solid blob or a neighboring staff is not adopted).

    Args:
        ink: Unopened ink mask (ink = 255).
        pts: Track points (x, y, spacing), any order.
        width: Page width.

    Returns:
        The extra points found (may be empty), excluding the originals.
    """
    pts = sorted(pts, key=lambda p: p[0])
    extra: list[tuple[float, float, float]] = []
    for direction in (-1, +1):
        chain = list(pts) if direction > 0 else list(reversed(pts))
        misses = 0
        x = chain[-1][0]
        while misses < STAFF_EXT_MAX_MISSES:
            x_next = x + direction * STAFF_EXT_STEP_PX
            if x_next < 0 or x_next >= width:
                break
            tail = chain[-STAFF_EXT_SLOPE_POINTS:]
            tx = np.array([p[0] for p in tail]); ty = np.array([p[1] for p in tail])
            slope = float(np.polyfit(tx, ty, 1)[0]) if len(tail) >= 2 and np.ptp(tx) > 0 else 0.0
            d = chain[-1][2]
            y_pred = chain[-1][1] + slope * (x_next - chain[-1][0])
            best_score, best_y = 0.0, None
            reach = int(round(STAFF_EXT_SEARCH_SPACINGS * d))
            for dy in range(-reach, reach + 1):
                sc = _staff_ink_score(ink, int(round(x_next)), y_pred + dy, d, slope)
                if sc > best_score:
                    best_score, best_y = sc, y_pred + dy
            x = x_next
            if best_y is None or best_score < STAFF_EXT_MIN_CONTRAST:
                misses += 1
                continue
            misses = 0
            new_pt = (float(x_next), float(best_y), float(d))
            chain.append(new_pt)
            extra.append(new_pt)
    return extra


def _fit_staff_curve(pts: list[tuple[float, float, float]]) -> StaffCurve | None:
    """Robust polynomial fit of one track; None if the fit is not trustworthy."""
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)
    ds = np.array([p[2] for p in pts], dtype=np.float64)
    order = np.argsort(xs)
    xs, ys, ds = xs[order], ys[order], ds[order]
    if len(xs) >= STAFF_FIT_CUBIC_MIN_POINTS:
        degree = 3
    elif len(xs) >= STAFF_FIT_QUAD_MIN_POINTS:
        degree = 2
    else:
        degree = 1
    coeffs = np.polyfit(xs, ys, degree)
    keep = np.abs(np.polyval(coeffs, xs) - ys) <= STAFF_FIT_OUTLIER_PX
    if keep.sum() >= max(degree + 2, STAFF_TRACK_MIN_POINTS):
        xs, ys, ds = xs[keep], ys[keep], ds[keep]
        coeffs = np.polyfit(xs, ys, degree)
    rms = float(np.sqrt(np.mean((np.polyval(coeffs, xs) - ys) ** 2)))
    if rms > STAFF_FIT_MAX_RESIDUAL_PX:
        return None
    return StaffCurve(
        center_coeffs=coeffs,
        spacing_coeffs=np.polyfit(xs, ds, 1),
        x_min=float(xs[0]), x_max=float(xs[-1]),
        n_points=len(xs), rms_px=rms,
    )


def track_staff_curves(binary: np.ndarray) -> list[StaffCurve]:
    """Finds every 5-line staff on the page as a curve, tolerant of tilt/curl/scale.

    Method: project a short-opened line mask per overlapping column block, pick
    evenly spaced 5-line groups in each block, link the groups across blocks into
    tracks (slope-predicted, gap-tolerant), rejoin pieces broken by notes or a
    page curl, then fit a polynomial center-line to each track. This is
    deliberately classical: it needs no training data, so it cannot share the
    detector's font/domain gap, and it gives Stage 2 an independent staff count.

    Args:
        binary: Binarized page (ink = 0), any tilt.

    Returns:
        Curves sorted top-to-bottom by mean center-line y. Empty if nothing
        staff-like was found.
    """
    h, w = binary.shape
    opened = _staff_line_open_mask(binary)
    ink = cv2.bitwise_not(binary)
    block_rows: list[tuple[float, list[float]]] = []
    for x0 in range(0, w - STAFF_BLOCK_WIDTH + 1, STAFF_BLOCK_STEP):
        profile = opened[:, x0:x0 + STAFF_BLOCK_WIDTH].sum(axis=1) / 255.0
        block_rows.append((x0 + STAFF_BLOCK_WIDTH / 2.0, _find_line_rows(profile)))

    # Pass 1 (strict) only estimates the page's typical spacing; pass 2 finds the staves.
    strict = [d for _, rows in block_rows for _, d in _group_five_lines(rows)]
    if not strict:
        return []
    spacing = float(np.median(strict))
    per_block = [[(xc, c, d) for c, d in _group_five_lines_with_hint(rows, spacing)]
                 for xc, rows in block_rows]
    # Page-median spacing gate: drops chains whose spacing disagrees with the
    # page (perspective changes spacing by ~10%, not 2x).
    per_block = [[det for det in dets if 0.6 * spacing <= det[2] <= 1.6 * spacing] for dets in per_block]

    tracks = _link_block_detections(per_block, spacing)
    tracks = [t for t in tracks if len(t["pts"]) >= 2]
    tracks = _merge_broken_tracks(tracks, spacing, w)

    curves: list[StaffCurve] = []
    for t in tracks:
        if len(t["pts"]) < STAFF_TRACK_MIN_POINTS:
            continue
        span = t["pts"][-1][0] - t["pts"][0][0]
        if span < STAFF_MIN_SPAN_FRAC * w:
            continue
        # Try the curl-following extension first; if the longer track no longer
        # fits a smooth curve, fall back to the block-tracked span alone.
        extra = _extend_track_ends(ink, t["pts"], w)
        curve = _fit_staff_curve(t["pts"] + extra) if extra else None
        if curve is None:
            curve = _fit_staff_curve(t["pts"])
        if curve is not None:
            curves.append(curve)
    curves = _drop_duplicate_curves(curves, spacing)
    curves.sort(key=lambda c: c.mean_center)
    return curves


def _drop_duplicate_curves(curves: list[StaffCurve], spacing: float) -> list[StaffCurve]:
    """Removes a curve that shadows a better-supported curve of the same staff.

    Fragment merging can stitch stray detections into a phantom track running
    alongside a real staff; two genuine staves are always >> a few spacings apart.
    """
    kept: list[StaffCurve] = []
    for c in sorted(curves, key=lambda c: -c.n_points):
        duplicate = False
        for k in kept:
            lo, hi = max(c.x_min, k.x_min), min(c.x_max, k.x_max)
            if hi <= lo:
                continue
            xs = np.linspace(lo, hi, 16)
            if float(np.mean(np.abs(c.center_at(xs) - k.center_at(xs)))) < STAFF_DUPLICATE_SPACINGS * spacing:
                duplicate = True
                break
        if not duplicate:
            kept.append(c)
    return kept


def staff_grid_map(shape: tuple[int, int], curves: list[StaffCurve]) -> np.ndarray:
    """Builds the per-column vertical remap that straightens every tracked staff.

    For each output column, a piecewise-linear map is built through knots at
    every staff's top and bottom line: output (straight staff at its mean
    height, at its median spacing) -> source (that staff's actual curve at this
    column). Rows between staves interpolate linearly; rows above/below the
    outermost staves shift with the nearest staff. Vertical-only on purpose:
    staffline curvature is the failure, and a horizontal remap would need
    barline tracking we do not have.

    Args:
        shape: (height, width) of the page the curves were tracked on.
        curves: Output of track_staff_curves(), top-to-bottom, non-empty.

    Returns:
        float32 (h, w) array: source row for every output pixel.
    """
    h, w = shape[:2]
    half = (STAFF_LINES_PER_STAFF - 1) / 2.0  # staff spans center +/- 2 spacings
    xs = np.arange(w, dtype=np.float64)

    dst_knots = np.empty(2 * len(curves))
    for k, c in enumerate(curves):
        span_x = np.linspace(c.x_min, c.x_max, 32)
        d_ref = float(np.median(c.spacing_at(span_x)))
        dst_knots[2 * k] = c.mean_center - half * d_ref
        dst_knots[2 * k + 1] = c.mean_center + half * d_ref
    # Destination knots must stay strictly increasing even if two staves'
    # mean centers are unusually close.
    order = np.arange(len(dst_knots))
    dst_knots = np.maximum.accumulate(dst_knots + order * KNOT_EPSILON_PX)

    src_knots = np.empty((len(dst_knots), w))
    for k, c in enumerate(curves):
        center = c.center_at(xs)
        d = c.spacing_at(xs)
        src_knots[2 * k] = center - half * d
        src_knots[2 * k + 1] = center + half * d
    src_knots = np.maximum.accumulate(src_knots + order[:, None] * KNOT_EPSILON_PX, axis=0)

    rows = np.arange(h, dtype=np.float64)
    map_y = np.empty((h, w), dtype=np.float32)
    for x in range(w):
        # Outer knots (slope 1) so rows beyond the first/last staff translate
        # with it instead of clamping to a constant.
        k_dst = np.concatenate([[dst_knots[0] - h], dst_knots, [dst_knots[-1] + h]])
        k_src = np.concatenate([[src_knots[0, x] - h], src_knots[:, x], [src_knots[-1, x] + h]])
        map_y[:, x] = np.interp(rows, k_dst, k_src)
    return map_y


def _remap_rows(image: np.ndarray, map_y: np.ndarray, out_shape: tuple[int, int] | None = None) -> np.ndarray:
    """Applies a row map from staff_grid_map(), optionally to a higher-resolution image.

    For a higher-resolution `image`, the detection-resolution map is upsampled bilinearly (it is
    a smooth field) and its row values rescaled through pixel centres, so the native page is
    warped by the same geometry the staves were tracked in. Bilinear gray interpolation only:
    the caller binarizes AFTER this, so no glyph is thickened or eroded by the warp itself.
    """
    h, w = image.shape[:2]
    mh, mw = map_y.shape
    if (h, w) != (mh, mw):
        ky = h / mh
        map_y = cv2.resize(map_y, (w, h), interpolation=cv2.INTER_LINEAR)
        map_y = (ky * (map_y + 0.5) - 0.5).astype(np.float32)
    map_x = np.tile(np.arange(w, dtype=np.float32), (h, 1))
    return cv2.remap(image, map_x, map_y, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def dewarp_to_staff_grid(image: np.ndarray, curves: list[StaffCurve]) -> np.ndarray:
    """Remaps `image` vertically so every tracked staff becomes a straight horizontal band.

    Args:
        image: Grayscale or binary page.
        curves: Output of track_staff_curves(), top-to-bottom, non-empty.

    Returns:
        Image of the same shape with staves straightened (see staff_grid_map).
    """
    return _remap_rows(image, staff_grid_map(image.shape, curves))


def needs_dewarp(curves: list[StaffCurve]) -> bool:
    """True when at least one staff drifts enough for axis-aligned boxes to cut across it.

    Deliberately ``any`` rather than a majority: a single badly bent staff already makes
    axis-aligned boxes cut through it. The trade-off is that one phantom curve (a false
    tracker hit) can trigger a whole-page warp; the tracker's span/residual filters are
    the guard against that.
    """
    return any(c.drift_px >= DEWARP_MIN_DRIFT_PX for c in curves)


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Adaptive-threshold binarization shared by the initial and post-dewarp passes."""
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=10
    )


def _draw_staff_curves(binary: np.ndarray, curves: list[StaffCurve]) -> np.ndarray:
    """Debug overlay: each tracked staff's center-line and its 5-line extent."""
    canvas = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    xs = np.arange(0, binary.shape[1], 8, dtype=np.float64)
    for k, c in enumerate(curves):
        color = (0, 0, 255) if k % 2 == 0 else (255, 0, 0)
        pts = np.stack([xs, c.center_at(xs)], axis=1).astype(np.int32)
        cv2.polylines(canvas, [pts], False, color, 2)
        cv2.putText(canvas, str(k + 1), (int(pts[0, 0]) + 4, int(pts[0, 1]) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    return canvas


GRID_ROTATION_MIN_DEG = 0.3  # smaller global rotations are measurement noise and are not applied


def grid_correction_deg(h_angle: float, v_angle: float) -> float:
    """Global rotation (degrees) correct_to_grid applies; shared so the strip source matches."""
    return h_angle if abs(v_angle) < GRID_ROTATION_MIN_DEG else (h_angle + v_angle) / 2.0


def correct_to_grid(binary: np.ndarray, bgr: np.ndarray, apply_rotation: bool = True) -> tuple:
    """
    Aligns the score to a true orthogonal grid using stafflines (horizontal)
    and barlines (vertical) as references. Replaces has_page_boundary logic.

    Args:
        apply_rotation: When False, only measures and returns the angles (used
            after dewarp_to_staff_grid(), which already made staves horizontal).
    """
    h, w = binary.shape
    ink = cv2.bitwise_not(binary)

    # ── Horizontal angle from stafflines ─────────────────────────────────
    min_len = max(int(w * 0.15), 50)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1))
    staff_mask = cv2.morphologyEx(ink, cv2.MORPH_OPEN, h_kernel)

    h_lines = cv2.HoughLinesP(staff_mask, rho=1, theta=np.pi/180,
        threshold=50, minLineLength=w//8, maxLineGap=50)

    h_angle = 0.0
    if h_lines is not None:
        angles = []
        for line in h_lines:
            # HoughLinesP's documented return shape is (N, 1, 4), but this
            # OpenCV build hands back (N, 4) — reshape(-1) copes with either.
            x1, y1, x2, y2 = line.reshape(-1)
            if x2 != x1:
                a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                if abs(a) < 20:
                    angles.append(a)
        if angles:
            h_angle = float(np.median(angles))

    # ── Vertical angle from barlines ──────────────────────────────────────
    min_height = max(int(h * 0.03), 30)
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_height))
    barline_mask = cv2.morphologyEx(ink, cv2.MORPH_OPEN, v_kernel)

    v_lines = cv2.HoughLinesP(barline_mask, rho=1, theta=np.pi/180,
        threshold=30, minLineLength=h//20, maxLineGap=10)

    v_angle = 0.0
    if v_lines is not None:
        angles = []
        for line in v_lines:
            # Same shape-mismatch fix as the horizontal-angle block above.
            x1, y1, x2, y2 = line.reshape(-1)
            if y2 != y1:
                a = np.degrees(np.arctan2(x2 - x1, y2 - y1))
                if a > 90:  a -= 180
                if a < -90: a += 180
                if abs(a) < 10:
                    angles.append(a)
        if angles:
            v_angle = float(np.median(angles))

    print(f"[Grid] h_angle={h_angle:.2f}°  v_angle={v_angle:.2f}°")

    # ── Apply correction ──────────────────────────────────────────────────
    correction = grid_correction_deg(h_angle, v_angle)

    corrected = binary.copy()
    if apply_rotation and abs(correction) > GRID_ROTATION_MIN_DEG:
        M = cv2.getRotationMatrix2D((w // 2, h // 2), -correction, 1.0)
        corrected = cv2.warpAffine(corrected, M, (w, h),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_REPLICATE)

    return corrected, h_angle, v_angle


def _staff_line_mask(binary: np.ndarray) -> np.ndarray:
    """
    Per-row boolean mask: True where a row contains a long horizontal run of
    ink (i.e. looks like a literal staffline). Single source of truth for
    this detection signal -- `_detect_staff_bands()` and
    `_blank_border_if_no_staff()`'s literal-mask baseline both consume this
    exact mask, so the two can never silently diverge if the threshold/kernel
    is tuned later.
    """
    h, w = binary.shape
    ink = cv2.bitwise_not(binary)
    min_len = max(int(w * 0.15), 50)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1))
    staff_mask = cv2.morphologyEx(ink, cv2.MORPH_OPEN, h_kernel)
    return np.sum(staff_mask, axis=1) > (w * 0.10)


def _detect_staff_bands(
    binary: np.ndarray,
    has_staff: np.ndarray | None = None,
    context: str = "",
) -> list[list[int]] | None:
    """
    Merges per-line staffline rows (from `_staff_line_mask()`) into per-staff
    bands (top/bottom row of each 5-line staff), applying the same
    reliability guards this detection has always used. Returns None if
    detection looks unreliable on this image.

    Args:
        has_staff: Precomputed `_staff_line_mask()` output, if the caller
          already has one (avoids recomputing the same morphology pass
          twice per page). Computed fresh if omitted.
        context: Short label included in the SKIPPED log line so it's clear
          which caller's guard tripped -- `_blank_border_if_no_staff()`
          falling back to literal-staffline-only protection is a materially
          different (BUG-012-shaped) consequence than
          `blank_lyrics_regions()` leaving lyric zones unblanked.

    Shared by `_blank_border_if_no_staff()` and `blank_lyrics_regions()` so
    both agree on where the real staves are. BUG-012: before this was
    shared, `_blank_border_if_no_staff()` only protected literal
    staffline-mask rows (the long horizontal lines themselves) — not the
    notes/clef/accidentals sitting between and around them, none of which
    are long horizontal lines. A staff whose band overlapped the border zone
    (e.g. the last staff on a tightly-cropped digital page, sitting within
    `bottom_px` of the page bottom) had its actual musical content erased
    while the bare lines survived, producing a near-blank strip downstream.
    """
    h, _ = binary.shape
    if has_staff is None:
        has_staff = _staff_line_mask(binary)

    bands = []
    in_band = False
    for y in range(h):
        if has_staff[y] and not in_band:
            in_band = True; start = y
        elif not has_staff[y] and in_band:
            in_band = False; bands.append((start, y))
    if in_band:
        bands.append((start, h))

    if not bands:
        return None

    # ── Safety guard: don't trust a staffline mask that barely detected any
    # lines at all — that means detection failed on this image (common on
    # unnormalized camera photos), not that there's genuinely little content.
    if len(bands) < MIN_RAW_LINE_BANDS:
        print(f"[Staff detect{f' ({context})' if context else ''}] SKIPPED — only "
              f"{len(bands)} raw line-band(s) detected (need >= {MIN_RAW_LINE_BANDS}); "
              f"staffline detection looks unreliable on this image.")
        return None

    merged = [list(bands[0])]
    for b in bands[1:]:
        if b[0] - merged[-1][1] < 25:
            merged[-1][1] = b[1]
        else:
            merged.append(list(b))

    # Drop merged bands too short to plausibly be a real staff (noise).
    merged = [b for b in merged if (b[1] - b[0]) >= MIN_MERGED_BAND_HEIGHT]
    if len(merged) < 2:
        print(f"[Staff detect{f' ({context})' if context else ''}] SKIPPED — only "
              f"{len(merged)} plausible staff band(s) after filtering; not enough to "
              f"safely locate staff regions.")
        return None

    return merged


def _border_rows_to_blank(binary: np.ndarray, top_px: int, bottom_px: int) -> np.ndarray:
    """
    Returns the bool row mask of top/bottom border rows to blank, never touches a row inside a
    detected staff's content zone — protects tightly-cropped pages (digital
    exports) where a real staff sits right at the edge, while still killing
    camera photos' hand/table-shadow rows near the border. See BUG-012 note
    on `_detect_staff_bands()` for why "content zone" (a margin around each
    merged staff band), not just literal staffline rows, is what must be
    protected here.
    """
    h, w = binary.shape
    protected = _staff_line_mask(binary)

    bands = _detect_staff_bands(binary, has_staff=protected, context="border-blank")
    if bands is None:
        # Staff-band detection was unreliable on this image (see the SKIPPED
        # log line above) -- falls back to the literal-staffline-only mask,
        # which is exactly the BUG-012 mechanism this function exists to fix.
        # Kept as the fallback rather than skipping border-blanking entirely
        # (camera photos with genuinely unreliable staffline detection still
        # need hand/table-shadow rows removed), but surfaced loudly since a
        # real staff caught by this path would silently lose content again.
        logger.warning(
            "_blank_border_if_no_staff: staff-band detection unreliable, "
            "falling back to literal-staffline-only border protection "
            "(re-introduces the BUG-012 failure mode if a real staff sits "
            "in the border zone on this image)."
        )
    else:
        for start, end in bands:
            # Generous margin (not blank_lyrics_regions()'s tighter 0.6x —
            # this is a hard "never erase" guard, not a soft lyric-zone
            # cutoff) so ledger-line notes, accidentals, and clefs that
            # extend past the 5-line staff itself stay protected too.
            margin = int((end - start) * BORDER_PROTECT_MARGIN_RATIO)
            lo, hi = max(0, start - margin), min(h, end + margin)
            protected[lo:hi] = True

    blanked = np.zeros(h, dtype=bool)
    blanked[:min(top_px, h)] = True
    blanked[max(0, h - bottom_px):] = True
    return blanked & ~protected


def _blank_border_if_no_staff(binary: np.ndarray, top_px: int, bottom_px: int) -> np.ndarray:
    """Blanks the border rows chosen by _border_rows_to_blank (see there for the rationale)."""
    result = binary.copy()
    result[_border_rows_to_blank(binary, top_px, bottom_px), :] = 255
    return result


def blank_lyrics_regions(binary: np.ndarray) -> np.ndarray:
    h, w = binary.shape

    merged = _detect_staff_bands(binary, context="lyric-blank")
    if not merged:
        return binary

    staff_h = int(np.mean([e - s for s, e in merged]))
    result = binary.copy()

    for i, (staff_top, staff_bot) in enumerate(merged):
        if i < len(merged) - 1:
            next_top = merged[i + 1][0]
            gap_h = next_top - staff_bot

            blank_top = staff_bot + int(staff_h * 0.6)
            blank_bot = next_top - int(staff_h * 0.9)

            if gap_h > 150:
                blank_bot = next_top - int(staff_h * 1.0)

        else:
            blank_top = staff_bot + int(staff_h * 0.6)
            blank_bot = h

        # Belt-and-suspenders: never blank more than a bounded multiple of
        # staff_h in one zone, even if the band estimate above was still off.
        max_blank_bot = blank_top + int(staff_h * MAX_BLANK_HEIGHT_RATIO)
        blank_bot = min(blank_bot, max_blank_bot)

        if blank_bot > blank_top:
            result[blank_top:blank_bot, :] = 255

    print(f"[Blank] {len(merged)} staff group(s), staff_h={staff_h}px, lyric zones blanked.")
    return result


def preprocess_batch(image_dir: str, output_dir: str, save_debug: bool = False,
                     keep_unmasked: bool = False) -> list:
    """Runs Stage 1 on every image in ``image_dir``.

    Args:
        keep_unmasked: Also keep each page's unmasked native image and tracked staves and append the
            PreprocessedPage as a 4th tuple element; ClefKeyNet crops from it (stage3_clefkey).

    Returns:
        (detection page, page index, native strip source or None[, PreprocessedPage]) per image.
    """
    input_path = Path(image_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
    image_files = sorted(
        [f for f in input_path.iterdir() if f.suffix.lower() in extensions]
    )

    if not image_files:
        raise FileNotFoundError(f"No images found in: {image_dir}")

    results = []
    for i, img_file in enumerate(image_files, start=1):
        page = preprocess_score_page(str(img_file), save_debug=save_debug, keep_unmasked=keep_unmasked)
        out_file = output_path / f"page_{i:03d}_preprocessed.png"
        cv2.imwrite(str(out_file), page.detect)
        print(f"  Saved -> {out_file}")
        if page.strip_source is not None:
            src_file = output_path / f"page_{i:03d}_strip_source.png"
            cv2.imwrite(str(src_file), page.strip_source)
            print(f"  Saved -> {src_file}")
        # (detection page, page index, native strip source or None); Stage 2 accepts 2-tuples too and
        # ignores the 4th element.
        results.append((page.detect, i, page.strip_source, page) if keep_unmasked
                       else (page.detect, i, page.strip_source))

    print(f"\n[Stage 1] Preprocessed {len(results)} page(s). Output: {output_dir}")
    return results


def _dbg_save(enabled: bool, base_path: Path, img: np.ndarray, tag: str):
    if not enabled:
        return
    debug_dir = base_path.parent / "debug"
    debug_dir.mkdir(exist_ok=True)
    out = debug_dir / f"{base_path.stem}_{tag}.png"
    cv2.imwrite(str(out), img)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python stage1_preprocessing.py <input_dir> <output_dir>")
        print("Example: python stage1_preprocessing.py data/raw data/preprocessed")
        sys.exit(1)

    batch = preprocess_batch(sys.argv[1], sys.argv[2], save_debug=True)
    print(f"\nDone. {len(batch)} image(s) ready for Stage 2.")