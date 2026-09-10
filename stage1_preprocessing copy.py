"""
PiyaNota - Stage 1: Image Preprocessing Pipeline
Prepares mobile-captured SATB score images for staff detection.

Upgrade: staffline-aware dewarping slotted between binarization and skew correction.
"""

import cv2
from matplotlib.pyplot import gray
import numpy as np
import os
from pathlib import Path


# ── Existing pipeline (with dewarp step inserted) ───────────────────────────

def preprocess_score_image(image_path: str, save_debug: bool = False) -> tuple:
    img_path = Path(image_path)
    bgr = cv2.imread(str(img_path))
    if bgr is None:
        raise ValueError(f"Could not read image: {image_path}")
    
    # ── Step 0: Downscale large phone images to a manageable resolution ──
    # iPhone photos can be 3000-4000px — rescale to max 1600px on longest side
    # so staffline detection kernels and thresholds work correctly.
    MAX_DIM = 2400
    ph, pw = bgr.shape[:2]
    if max(ph, pw) > MAX_DIM:
        scale = MAX_DIM / max(ph, pw)
        bgr = cv2.resize(bgr, (int(pw * scale), int(ph * scale)),
                         interpolation=cv2.INTER_AREA)
        print(f"[Stage 1] Downscaled from {ph}x{pw} → {bgr.shape[0]}x{bgr.shape[1]}")

    # Step 1: Grayscale
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _dbg_save(save_debug, img_path, gray, "1_gray")

    # Step 2: Background normalization
    bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (91, 91)))
    normalized = cv2.divide(gray, bg, scale=255)

    # Mild blur AFTER normalization to kill grain before thresholding
    normalized = cv2.GaussianBlur(normalized, (3, 3), 0)
    _dbg_save(save_debug, img_path, normalized, "2_normalized")

    # Step 3: Adaptive threshold on normalized image
    binary = cv2.adaptiveThreshold(
        normalized, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=10
    )

    # Kill edge shadows
    border_top = 30
    border_sides = 40
    border_bottom = 60
    binary[:30, :] = 255     # top — usually clean, small border
    binary[-100:, :] = 255   # bottom — hand/table shadow, larger
    binary[:, :80] = 255     # left — book spine, larger
    binary[:, -80:] = 255    # right — hand/page edge, larger

    _dbg_save(save_debug, img_path, binary, "3_binary")

    # ── Step 3.2: Blank lyric rows so YOLO never detects them ────────────
    binary = blank_lyrics_regions(binary)
    
    _dbg_save(save_debug, img_path, binary, "3a_blanked")
    # ─────────────────────────────────────────────────────────────────────

   # Step 3.5: Grid alignment FIRST (fix gross rotation before dewarping)
    corrected, h_angle, v_angle = correct_to_grid(binary, bgr)
    
    _dbg_save(save_debug, img_path, corrected, "3b_grid_aligned")
    print(f"[Stage 1] '{img_path.name}' → grid aligned {h_angle:.2f}°")
    return corrected, h_angle
    
def correct_to_grid(binary: np.ndarray, bgr: np.ndarray) -> tuple[np.ndarray, float, float]:
    """
    Corrects document tilt using the Projection Profile Method.
    
    For each candidate angle, rotates the image and computes the horizontal
    projection profile (row-wise ink sum). The angle that produces the most
    peaked/variance-maximum profile is the true horizontal — because perfectly
    horizontal stafflines create sharp spikes in the profile.
    
    Returns: (corrected_binary, h_angle, v_angle)
    """
    h, w = binary.shape
    ink = cv2.bitwise_not(binary)  # ink = 255

    best_angle = 0.0
    best_variance = -1.0

    # Search range: -10° to +10° in 0.1° steps
    search_angles = np.arange(-10.0, 10.1, 0.1)

    for angle in search_angles:
        # Rotate ink image by candidate angle
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        rotated = cv2.warpAffine(ink, M, (w, h),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0)

        # Horizontal projection profile: sum ink per row
        profile = np.sum(rotated, axis=1).astype(np.float64)

        # Variance of profile — peaks when stafflines are horizontal
        variance = np.var(profile)

        if variance > best_variance:
            best_variance = variance
            best_angle = angle

    print(f"[Grid] best_angle={best_angle:.2f}°  variance={best_variance:.0f}")

    # Apply correction
    corrected = binary.copy()
    if abs(best_angle) > 0.1:
        M = cv2.getRotationMatrix2D((w // 2, h // 2), best_angle, 1.0)
        corrected = cv2.warpAffine(corrected, M, (w, h),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_REPLICATE)

    return corrected, best_angle, 0.0

def blank_lyrics_regions(binary: np.ndarray) -> np.ndarray:
    h, w = binary.shape
    ink = cv2.bitwise_not(binary)

    min_len = max(int(w * 0.15), 50)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1))
    staff_mask = cv2.morphologyEx(ink, cv2.MORPH_OPEN, h_kernel)

    row_sum = np.sum(staff_mask, axis=1)
    has_staff = row_sum > (w * 0.10)

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
        return binary

    merged = [list(bands[0])]
    for b in bands[1:]:
        if b[0] - merged[-1][1] < 25:
            merged[-1][1] = b[1]
        else:
            merged.append(list(b))

    staff_h = int(np.mean([e - s for s, e in merged]))
    result = binary.copy()

    for i, (staff_top, staff_bot) in enumerate(merged):
        if i < len(merged) - 1:
            next_top = merged[i + 1][0]
            gap_h = next_top - staff_bot

            blank_top = staff_bot + int(staff_h * 0.6) # distance from the 5th line of the staff
            blank_bot = next_top - int(staff_h * 0.9)  # was 40, now 20 = taller box

            # Inter-system gap: lyrics still appear below Bass,
            # so blank a wider zone but stop before the next system's high notes
            if gap_h > 150:
                blank_bot = next_top - int(staff_h * 1.0) # protect next staff's high notes

        else:
            # Last staff on page — lyrics can appear below it too
            blank_top = blank_top = staff_bot + int(staff_h * 0.6) # distance from the 5th line of the staff
            blank_bot = h

        if blank_bot > blank_top:
            result[blank_top:blank_bot, :] = 255

    print(f"[Blank] {len(merged)} staff group(s), staff_h={staff_h}px, lyric zones blanked.")
    return result


def preprocess_batch(image_dir: str, output_dir: str, save_debug: bool = False) -> list:
    """
    Preprocesses all PNG/JPG images in a directory, saves results,
    and returns an ordered list of (corrected_image, page_index) pairs.
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
        corrected, angle = preprocess_score_image(str(img_file), save_debug=save_debug)
        out_file = output_path / f"page_{i:03d}_preprocessed.png"
        cv2.imwrite(str(out_file), corrected)
        print(f"  Saved → {out_file}")
        results.append((corrected, i))

    print(f"\n[Stage 1] Preprocessed {len(results)} page(s). Output: {output_dir}")
    return results


# ── Internal helper ──────────────────────────────────────────────────────────

def _dbg_save(enabled: bool, base_path: Path, img: np.ndarray, tag: str):
    if not enabled:
        return
    debug_dir = base_path.parent / "debug"
    debug_dir.mkdir(exist_ok=True)
    out = debug_dir / f"{base_path.stem}_{tag}.png"
    cv2.imwrite(str(out), img)


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python stage1_preprocessing.py <input_dir> <output_dir>")
        print("Example: python stage1_preprocessing.py data/raw data/preprocessed")
        sys.exit(1)

    batch = preprocess_batch(sys.argv[1], sys.argv[2], save_debug=True)
    print(f"\nDone. {len(batch)} image(s) ready for Stage 2.")