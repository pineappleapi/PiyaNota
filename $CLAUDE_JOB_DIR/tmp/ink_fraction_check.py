"""Quantify vertical effective-resolution dilution: what fraction of strip
height is actually inked content, real Stage-2 strips (padding=0.5, STRIP_HEIGHT=64)
vs. Camera-PrIMuS clean training renders (no padding step, straight resize).
Isotropic resize (both axes scaled by target_height/h) preserves ink-height
fraction, so measuring on native (pre-resize) images is equivalent to measuring
post-resize -- native is used here to avoid re-running YOLO for the CPM side.
"""
import sys
sys.path.insert(0, r"D:\PiyaNota (Code)")
import glob
import random
import cv2
import numpy as np

import stage2_detection as s2

random.seed(42)

def ink_row_fraction(gray: np.ndarray) -> float:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = cv2.bitwise_not(binary)
    row_has_ink = np.any(ink > 0, axis=1)
    rows = np.where(row_has_ink)[0]
    if len(rows) == 0:
        return 0.0
    ink_extent = rows[-1] - rows[0] + 1
    return ink_extent / gray.shape[0]

# ---- (a) Real Stage-2 strips, current pipeline (padding=0.5, STRIP_HEIGHT=64) ----
PAGES = {
    "shot": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_shot\page_001_preprocessed.png",
    "5751": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5751\page_001_preprocessed.png",
    "5752": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5752\page_001_preprocessed.png",
    "5753": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5753\page_001_preprocessed.png",
    "5754": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5754\page_001_preprocessed.png",
    "5755": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5755\page_001_preprocessed.png",
}
BUG012_AFFECTED = {("shot", 2, "Bass"), ("5751", 2, "Bass"), ("5752", 2, "Bass"),
                    ("5754", 2, "Bass"), ("5755", 2, "Bass")}
YOLO_WEIGHTS = r"D:\PiyaNota (Code)\staff_detector_files\weights\best.pt"

real_fracs = []
for key, path in PAGES.items():
    img = cv2.imread(path)
    voices = s2.detect_staff_regions(
        [(img, 1)], model_weights=YOLO_WEIGHTS,
        output_dir=r"D:\PiyaNota (Code)\$CLAUDE_JOB_DIR\tmp\inkfrac_scratch",
        save_strips=False,
    )
    for voice, entries in voices.items():
        for strip, page_index, sys_idx, voice_name, v_idx in entries:
            if (key, sys_idx, voice_name) in BUG012_AFFECTED:
                continue
            gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
            frac = ink_row_fraction(gray)
            real_fracs.append(frac)

real_fracs = np.array(real_fracs)
print(f"Real Stage-2 strips (padding=0.5, STRIP_HEIGHT=64): n={len(real_fracs)}")
print(f"  mean ink-height fraction = {real_fracs.mean():.3f}, median = {np.median(real_fracs):.3f}, "
      f"min={real_fracs.min():.3f}, max={real_fracs.max():.3f}")

# ---- (b) Camera-PrIMuS clean training renders (no padding step) ----
cpm_root = r"D:\PiyaNota (Code)\datasets\CameraPriMus\CameraPrIMuS - Copy\Corpus"
all_pngs = glob.glob(f"{cpm_root}/**/*.png", recursive=True)
all_pngs = [p for p in all_pngs if "distorted" not in p.lower()]
sample = random.sample(all_pngs, min(200, len(all_pngs)))

cpm_fracs = []
for p in sample:
    gray = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        continue
    frac = ink_row_fraction(gray)
    cpm_fracs.append(frac)

cpm_fracs = np.array(cpm_fracs)
print(f"\nCamera-PrIMuS clean renders (no padding step): n={len(cpm_fracs)}")
print(f"  mean ink-height fraction = {cpm_fracs.mean():.3f}, median = {np.median(cpm_fracs):.3f}, "
      f"min={cpm_fracs.min():.3f}, max={cpm_fracs.max():.3f}")

print(f"\nRatio (real/CPM mean fraction) = {real_fracs.mean()/cpm_fracs.mean():.3f}")
print(f"Implied effective glyph resolution at STRIP_HEIGHT=64: "
      f"real ~{real_fracs.mean()*64:.1f}px vs CPM ~{cpm_fracs.mean()*64:.1f}px")
