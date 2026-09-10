import sys
sys.path.insert(0, r"D:\PiyaNota (Code)")
import cv2
from pathlib import Path
import stage2_detection as s2

img = cv2.imread(r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5754\page_001_preprocessed.png")
out_dir = Path(r"D:\PiyaNota (Code)\$CLAUDE_JOB_DIR\tmp\5754_before_after")
out_dir.mkdir(parents=True, exist_ok=True)

for label, blank in (("before", False), ("after", True)):
    voices = s2.detect_staff_regions(
        [(img, 1)],
        model_weights=r"D:\PiyaNota (Code)\staff_detector_files\weights\best.pt",
        output_dir=str(out_dir / label),
        save_strips=True,
        blank_left_margin=blank,
    )
    strip = voices["Soprano"][0][0]  # sys1 Soprano
    cv2.imwrite(str(out_dir / f"soprano_sys1_{label}.png"), strip)
    print(label, "Soprano sys1 shape", strip.shape)
