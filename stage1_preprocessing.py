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
DEWARP_MIN_DRIFT_PX      = 5.0    # skip dewarp unless some staff drifts at least this much (already-straight input stays bit-identical)
STAFF_LINES_PER_STAFF    = 5


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



def preprocess_score_image(image_path: str, save_debug: bool = False) -> tuple:
    img_path = Path(image_path)
    bgr = cv2.imread(str(img_path))
    if bgr is None:
        raise ValueError(f"Could not read image: {image_path}")

    # Step 0: Downscale large phone images
    MAX_DIM = 1600
    ph, pw = bgr.shape[:2]
    if max(ph, pw) > MAX_DIM:
        scale = MAX_DIM / max(ph, pw)
        bgr = cv2.resize(bgr, (int(pw * scale), int(ph * scale)),
                         interpolation=cv2.INTER_AREA)
        print(f"[Stage 1] Downscaled {ph}x{pw} -> {bgr.shape[0]}x{bgr.shape[1]}")

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
    bgr = correct_perspective(bgr)
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
    if dewarped:
        print(f"[Dewarp] {len(curves)} staff curve(s), max drift "
              f"{max(c.drift_px for c in curves):.1f}px -> straightening staves")
        _dbg_save(save_debug, img_path, _draw_staff_curves(binary, curves), "3_staff_tracks")
        denoised = dewarp_to_staff_grid(denoised, curves)
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
    binary = _blank_border_if_no_staff(binary, BORDER_TOP_PX, BORDER_BOTTOM_PX)
    left_px = min(BORDER_LEFT_PX, binary.shape[1])
    binary[:, :left_px] = 255
    right_px = min(BORDER_RIGHT_PX, binary.shape[1])
    if right_px > 0:
        binary[:, -right_px:] = 255

    _dbg_save(save_debug, img_path, binary, "3_binary")

    # Step 3.2: Blank lyrics
    binary = blank_lyrics_regions(binary)

    # Step 3.3: Undo blanking that erased tracked staves (BUG-001). The band
    # heuristics above merge/misjudge bands on camera pages and wipe whole staves
    # (e.g. a tenor staff between two lyric lines). The tracker's staves are
    # independently verified 5-line groups, so their rows are never blank-worthy.
    # Side columns are re-blanked so shadow ink is not resurrected with them.
    if curves:
        # Post-dewarp each staff sits at its curve's mean_center with median spacing
        # (see dewarp_to_staff_grid); undewarped staves drift < DEWARP_MIN_DRIFT_PX.
        centers = [(c.mean_center, float(np.median(c.spacing_at(np.linspace(c.x_min, c.x_max, 32)))))
                   for c in curves]
        binary = _restore_staff_rows(binary, pre_blank, centers)
        binary[:, :left_px] = 255
        if right_px > 0:
            binary[:, -right_px:] = 255
    _dbg_save(save_debug, img_path, binary, "3a_blanked")

    # Step 4: Grid alignment using stafflines + barlines
    # After a dewarp the staves are horizontal by construction; a further global
    # rotation (esp. the barline-angle average, which measures perspective lean,
    # not staff tilt) would only re-tilt them, so angles are measured but not applied.
    corrected, h_angle, v_angle = correct_to_grid(binary, bgr, apply_rotation=not dewarped)
    _dbg_save(save_debug, img_path, corrected, "4_corrected")
    print(f"[Stage 1] '{img_path.name}' -> h={h_angle:.2f} deg v={v_angle:.2f} deg")

    return corrected, h_angle


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
        The perspective-corrected BGR image, or `bgr` unchanged if no
        confident page-boundary quad was found.
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
        return bgr

    largest = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, PERSPECTIVE_APPROX_EPS_FRAC * perimeter, True)

    if len(approx) != 4:
        print(f"[Perspective] largest contour approximates to {len(approx)} points, "
              f"not 4 — leaving image unchanged")
        return bgr

    if not cv2.isContourConvex(approx):
        print("[Perspective] 4-point contour is not convex — leaving image unchanged")
        return bgr

    quad_area = cv2.contourArea(approx)
    area_ratio = quad_area / frame_area
    if area_ratio < PERSPECTIVE_MIN_AREA_RATIO:
        print(f"[Perspective] quad covers only {area_ratio:.2f} of frame "
              f"(need >= {PERSPECTIVE_MIN_AREA_RATIO}) — leaving image unchanged")
        return bgr

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
        return bgr

    tl, tr, br, bl = _order_quad_points(approx.reshape(4, 2).astype(np.float32))

    dst_w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    dst_h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if dst_w <= 0 or dst_h <= 0:
        print("[Perspective] degenerate quad (zero width/height) — leaving image unchanged")
        return bgr

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
    return warped


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
                tol = max(1.8, 0.2 * gap)
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
    pts = track["pts"][-6:]
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
    """(x, y, slope) at one end of a track, slope from the ~8 points nearest that end."""
    pts = track["pts"][-8:] if at_end else track["pts"][:8]
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
    degree = 3 if len(xs) >= 25 else 2 if len(xs) >= 12 else 1
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


def dewarp_to_staff_grid(image: np.ndarray, curves: list[StaffCurve]) -> np.ndarray:
    """Remaps `image` vertically so every tracked staff becomes a straight horizontal band.

    For each output column, a piecewise-linear map is built through knots at
    every staff's top and bottom line: output (straight staff at its mean
    height, at its median spacing) -> source (that staff's actual curve at this
    column). Rows between staves interpolate linearly; rows above/below the
    outermost staves shift with the nearest staff. Vertical-only on purpose:
    staffline curvature is the failure, and a horizontal remap would need
    barline tracking we do not have.

    Args:
        image: Grayscale or binary page.
        curves: Output of track_staff_curves(), top-to-bottom, non-empty.

    Returns:
        Image of the same shape with staves straightened.
    """
    h, w = image.shape[:2]
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
    dst_knots = np.maximum.accumulate(dst_knots + order * 1e-3)

    src_knots = np.empty((len(dst_knots), w))
    for k, c in enumerate(curves):
        center = c.center_at(xs)
        d = c.spacing_at(xs)
        src_knots[2 * k] = center - half * d
        src_knots[2 * k + 1] = center + half * d
    src_knots = np.maximum.accumulate(src_knots + order[:, None] * 1e-3, axis=0)

    rows = np.arange(h, dtype=np.float64)
    map_y = np.empty((h, w), dtype=np.float32)
    for x in range(w):
        # Outer knots (slope 1) so rows beyond the first/last staff translate
        # with it instead of clamping to a constant.
        k_dst = np.concatenate([[dst_knots[0] - h], dst_knots, [dst_knots[-1] + h]])
        k_src = np.concatenate([[src_knots[0, x] - h], src_knots[:, x], [src_knots[-1, x] + h]])
        map_y[:, x] = np.interp(rows, k_dst, k_src)
    map_x = np.tile(np.arange(w, dtype=np.float32), (h, 1))
    return cv2.remap(image, map_x, map_y, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def needs_dewarp(curves: list[StaffCurve]) -> bool:
    """True when at least one staff drifts enough for axis-aligned boxes to cut across it."""
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


def _draw_staff_curves(binary: np.ndarray, curves: list["StaffCurve"]) -> np.ndarray:
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
    correction = h_angle if abs(v_angle) < 0.3 else (h_angle + v_angle) / 2.0

    corrected = binary.copy()
    if apply_rotation and abs(correction) > 0.3:
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


def _blank_border_if_no_staff(binary: np.ndarray, top_px: int, bottom_px: int) -> np.ndarray:
    """
    Blanks the top/bottom border bands, but never touches a row inside a
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

    result = binary.copy()
    for y in range(min(top_px, h)):
        if not protected[y]:
            result[y, :] = 255
    for y in range(max(0, h - bottom_px), h):
        if not protected[y]:
            result[y, :] = 255
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


def preprocess_batch(image_dir: str, output_dir: str, save_debug: bool = False) -> list:
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
        corrected, angle = preprocess_score_image(str(img_file), save_debug=save_debug)
        out_file = output_path / f"page_{i:03d}_preprocessed.png"
        cv2.imwrite(str(out_file), corrected)
        print(f"  Saved -> {out_file}")
        results.append((corrected, i))

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