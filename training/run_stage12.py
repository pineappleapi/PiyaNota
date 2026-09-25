"""Runs Stage 1 + Stage 2 on a folder of photos and writes strips, viz and a manifest.

Why: one reproducible entry point for regenerating the BSN / DSMN strip sets (the ad-hoc scratch
runners it replaces were not committed). It runs NO Stage 3/CRNN.

Usage (from the repo root):
    python training/run_stage12.py --raw D:/PiyaNota/data/raw/Raw --out data/test_bothSidesNow
    python training/run_stage12.py --raw data/step3_testset/raw --out data/step3_testset
Writes <out>/preprocessed (detection pages + native strip sources), <out>/strips (+ manifest.json)
and <out>/review (detection viz). Existing files with those names are overwritten.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage1_preprocessing as s1  # noqa: E402
import stage2_detection as s2  # noqa: E402

DEFAULT_WEIGHTS = "D:/PiyaNota/staff_detector_files/weights/best.pt"


EYEBALL_TILE_W = 1400  # px of native strip per sheet tile; wider tiles get downscaled by viewers
EYEBALL_VOICES = ("Soprano", "Alto", "Tenor", "Bass")
EYEBALL_GAP_PX = 6


def write_eyeball_sheets(strips_dir: Path, eyeball_dir: Path) -> int:
    """Stacks each system's four strips (S/A/T/B order) into 1:1 tiles for viewing.

    Why 1:1 tiles: the final strips are 64 px tall and ~3000 px wide, so any whole-strip
    montage is downscaled and hides the thin glyphs (rests, beams, ties) this review is about.

    Returns:
        Number of tile images written.
    """
    import cv2
    import numpy as np

    eyeball_dir.mkdir(parents=True, exist_ok=True)
    systems: dict[str, dict[str, Path]] = {}
    for path in sorted(strips_dir.glob("page*_sys*_*_vidx*.png")):
        page_sys, voice = path.stem.split("_")[0:2], path.stem.split("_")[2]
        systems.setdefault("_".join(page_sys), {})[voice] = path
    written = 0
    for key, voices in systems.items():
        imgs = [cv2.imread(str(voices[v])) for v in EYEBALL_VOICES if v in voices]
        width = max(i.shape[1] for i in imgs)
        rows = []
        for img in imgs:
            rows += [np.pad(img, ((0, EYEBALL_GAP_PX), (0, width - img.shape[1]), (0, 0)),
                            constant_values=128)]
        sheet = np.vstack(rows)
        for k, x in enumerate(range(0, width, EYEBALL_TILE_W)):
            cv2.imwrite(str(eyeball_dir / f"{key}_strips_tile{k}.png"), sheet[:, x:x + EYEBALL_TILE_W])
            written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, help="Directory of raw photos")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--weights", default=DEFAULT_WEIGHTS, help="YOLOv8 staff-detector weights")
    args = parser.parse_args()

    out = Path(args.out)
    pages = s1.preprocess_batch(args.raw, str(out / "preprocessed"))
    s2.detect_staff_regions(
        pages, model_weights=args.weights, output_dir=str(out / "strips"),
        save_viz=True, viz_dir=str(out / "review"),
        manifest_path=str(out / "strips" / "manifest.json"))
    print(f"[eyeball] {write_eyeball_sheets(out / 'strips', out / 'eyeball')} tile(s) written")


if __name__ == "__main__":
    main()
