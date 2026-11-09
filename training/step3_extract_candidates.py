"""PIYA-106 Step 3 helper: dump Stage 2 staff detections for review WITHOUT the
divisible-by-4 hard stop.

Why: on camera photos Stage 2's staff-count validation (PIYA-105 #4) raises on most
pages (BUG-001), so the normal CLI cannot produce strips for a real-world test set.
This reuses Stage 2's own model call, filtering, dedup and crop functions unchanged so
candidate strips are pixel-identical to what the pipeline would produce, but keeps every
detection numbered so a human can confirm/fix voice assignment before labeling.
"""

import argparse
import json
from pathlib import Path
from typing import Any

import cv2

import stage2_detection as s2

MAX_BOXES_PER_PAGE = 16  # same cap as Stage 2 Rule 2


def extract_page_candidates(
    model: Any, image_bgr: Any, conf: float = s2.CONF_THRESHOLD
) -> list[dict[str, Any]]:
    """Runs the Stage 2 detection/filter/dedup sequence and returns numbered boxes."""
    results = model(image_bgr, conf=conf, iou=s2.NMS_THRESHOLD, verbose=False)
    boxes = [b for b in s2._extract_boxes(results) if b["conf"] >= conf]
    if len(boxes) > MAX_BOXES_PER_PAGE:
        boxes = sorted(boxes, key=lambda b: b["conf"], reverse=True)[:MAX_BOXES_PER_PAGE]
    boxes = sorted(boxes, key=lambda b: b["cy"])
    return s2._remove_duplicates(boxes, min_cy_gap=30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prep", required=True, help="Stage 1 preprocessed pages dir")
    parser.add_argument("--out", required=True, help="Output dir for candidates + viz")
    parser.add_argument("--weights", required=True, help="YOLOv8 staff detector weights")
    args = parser.parse_args()

    out = Path(args.out)
    (out / "candidates").mkdir(parents=True, exist_ok=True)
    (out / "viz").mkdir(parents=True, exist_ok=True)
    model = s2.YOLO(args.weights)
    summary: dict[str, Any] = {}

    for page_path in sorted(Path(args.prep).glob("page_*_preprocessed.png")):
        page_no = int(page_path.stem.split("_")[1])
        img = cv2.imread(str(page_path))
        if img is None:
            raise FileNotFoundError(f"could not read {page_path}")
        img_h, img_w = img.shape[:2]
        boxes = extract_page_candidates(model, img)
        canvas = img.copy()
        page_info = []
        for k, b in enumerate(boxes, start=1):
            b["x1"], b["x2"] = 0, img_w
            strip = s2._crop_and_resize(
                img, b, s2.STRIP_HEIGHT, strip_id=f"p{page_no}c{k}",
                limits=s2._neighbor_limits(boxes, k - 1, img_h))
            cv2.imwrite(str(out / "candidates" / f"page{page_no:03d}_cand{k:02d}.png"), strip)
            cv2.rectangle(canvas, (0, b["y1"]), (img_w, b["y2"]), (0, 0, 255), 2)
            cv2.putText(canvas, f"#{k} {b['conf']:.2f}", (8, max(b["y1"] - 4, 16)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
            page_info.append({"cand": k, "y1": int(b["y1"]), "y2": int(b["y2"]),
                              "cy": float(b["cy"]), "conf": round(float(b["conf"]), 3)})
        cv2.imwrite(str(out / "viz" / f"page{page_no:03d}_candidates.png"), canvas)
        summary[f"page{page_no:03d}"] = {"size": [img_w, img_h], "boxes": page_info}
        print(f"page {page_no}: {len(boxes)} candidate staff box(es)")

    (out / "candidates.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
