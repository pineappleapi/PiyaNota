"""
PiyaNota - Stage 1: Image Preprocessing Pipeline
"""

import logging

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
    binary = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=10
    )

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
    binary = _blank_border_if_no_staff(binary, BORDER_TOP_PX, BORDER_BOTTOM_PX)
    left_px = min(BORDER_LEFT_PX, binary.shape[1])
    binary[:, :left_px] = 255
    right_px = min(BORDER_RIGHT_PX, binary.shape[1])
    if right_px > 0:
        binary[:, -right_px:] = 255

    _dbg_save(save_debug, img_path, binary, "3_binary")

    # Step 3.2: Blank lyrics
    binary = blank_lyrics_regions(binary)
    _dbg_save(save_debug, img_path, binary, "3a_blanked")

    # Step 4: Grid alignment using stafflines + barlines
    corrected, h_angle, v_angle = correct_to_grid(binary, bgr)
    _dbg_save(save_debug, img_path, corrected, "4_corrected")
    print(f"[Stage 1] '{img_path.name}' -> h={h_angle:.2f} deg v={v_angle:.2f} deg")

    return corrected, h_angle


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


def correct_to_grid(binary: np.ndarray, bgr: np.ndarray) -> tuple:
    """
    Aligns the score to a true orthogonal grid using stafflines (horizontal)
    and barlines (vertical) as references. Replaces has_page_boundary logic.
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
    if abs(correction) > 0.3:
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