"""
PiyaNota - Stage 2: Staff Region Detection (YOLOv8)
Detects and extracts individual staff strips from preprocessed score pages.
"""

import cv2
import numpy as np
from pathlib import Path

# Ultralytics YOLOv8 — install with: pip install ultralytics
from ultralytics import YOLO


# ── Voice assignment by vertical index within a 4-staff SATB system ──────────
VOICE_MAP = {1: "Soprano", 2: "Alto", 3: "Tenor", 4: "Bass"}

# Detection thresholds
CONF_THRESHOLD = 0.4   # minimum confidence to keep a detection
NMS_THRESHOLD  = 0.3   # IoU threshold for Non-Maximum Suppression
STRIP_HEIGHT   = 250    # fixed height for CRNN-CTC input (px)


def detect_staff_regions(
    preprocessed_images: list,
    model_weights: str = "staff_detector_files\\weights\\best.pt",
    output_dir: str = "data/strips",
    save_strips: bool = True,
    save_viz: bool = False,          # ← new flag
    viz_dir: str = "data/detection_viz",
) -> dict:
    output_path = Path(output_dir)
    if save_strips:
        output_path.mkdir(parents=True, exist_ok=True)

    viz_path = Path(viz_dir)
    if save_viz:
        viz_path.mkdir(parents=True, exist_ok=True)

    model = YOLO(model_weights)

    voice_sequences = {"Soprano": [], "Alto": [], "Tenor": [], "Bass": []}

    for image, page_index in preprocessed_images:
        if len(image.shape) == 2:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            image_bgr = image.copy()

        img_h, img_w = image_bgr.shape[:2]

        # ── Single model call per page ────────────────────────────────────
        results = model(image_bgr, conf=CONF_THRESHOLD, iou=NMS_THRESHOLD, verbose=False)


        boxes   = _extract_boxes(results)

        # Rule 1: Filter out low-confidence detections before grouping
        boxes = [b for b in boxes if b["conf"] >= CONF_THRESHOLD]

        # Rule 2: cap at 16 (4 systems × 4 voices max)
        if len(boxes) > 16:
            boxes = sorted(boxes, key=lambda b: b["conf"], reverse=True)[:16]

        # Rule 3: sort top-to-bottom for correct SATB grouping
        boxes = sorted(boxes, key=lambda b: b["cy"])

        # Rule 3.5: remove duplicate detections on the same staff
        boxes = _remove_duplicates(boxes, min_cy_gap=30)

        # Rule 3.6: staff-count validation — open-score enforcement (PIYA-105 #4)
        if len(boxes) != 0 and len(boxes) % 4 != 0:
            raise ValueError(
                f"[Stage 2] page {page_index}: unsupported_staff_layout — "
                f"detected {len(boxes)} staff region(s) after filtering/dedup, "
                f"not divisible by 4. Closed-score (2-staff) SATB is not "
                f"supported (see docs/sow.md Section 3)."
            )

        # ── DEBUG: print raw box heights ──────────────────────────────────────
        for b in boxes:
            print(f"  [Stage 2] y1={b['y1']} y2={b['y2']} height={b['y2']-b['y1']}px conf={b['conf']:.2f}")

        # Rule 4: stretch to full width — stafflines always span full page
        for b in boxes:
            b["x1"] = 0
            b["x2"] = img_w

        if len(boxes) == 0:
            print(f"[Stage 2] WARNING: No staff regions detected on page {page_index}.")
            continue

        print(f"[Stage 2] Page {page_index}: {len(boxes)} staff region(s) detected.")

        # ── Visualization after validation ────────────────────────────────
        if save_viz:
            _draw_and_save_viz(image_bgr, boxes, page_index, viz_path)

        systems = [boxes[i:i+4] for i in range(0, len(boxes), 4)]

        for sys_idx, system in enumerate(systems, start=1):
            for v_idx, box in enumerate(system, start=1):
                voice = VOICE_MAP.get(v_idx, f"Voice_{v_idx}")
                strip = _crop_and_resize(image_bgr, box, STRIP_HEIGHT)
                voice_sequences[voice].append((strip, page_index, sys_idx, voice, v_idx))

                if save_strips:
                    fname = output_path / f"page{page_index:03d}_sys{sys_idx:02d}_{voice}_vidx{v_idx}.png"
                    cv2.imwrite(str(fname), strip)

    _report(voice_sequences)
    return voice_sequences

def _remove_duplicates(boxes: list, min_cy_gap: int = 30) -> list:
    """
    If two boxes have vertical centers within min_cy_gap pixels,
    they're on the same staff — keep only the higher confidence one.
    """
    if not boxes:
        return boxes
    filtered = [boxes[0]]
    for box in boxes[1:]:
        if box["cy"] - filtered[-1]["cy"] > min_cy_gap:
            filtered.append(box)
        else:
            # Same staff — keep higher confidence
            if box["conf"] > filtered[-1]["conf"]:
                filtered[-1] = box
    return filtered



def _draw_and_save_viz(image_bgr, boxes, page_index, output_path,
                        box_color=(0, 0, 255), box_thickness=2, font_scale=0.6):
    """Draws boxes on a copy of the image and saves it. No YOLO call."""
    canvas = image_bgr.copy()
    systems = [boxes[i:i+4] for i in range(0, len(boxes), 4)]

    for sys_idx, system in enumerate(systems, start=1):
        for v_idx, box in enumerate(system, start=1):
            voice = VOICE_MAP.get(v_idx, f"Voice_{v_idx}")
            label = f"S{sys_idx} {voice} ({box['conf']:.2f})"
            cv2.rectangle(canvas, (box["x1"], box["y1"]),
                          (box["x2"], box["y2"]), box_color, box_thickness)
            (tw, th), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
            label_y = max(box["y1"] - 4, th + 4)
            cv2.rectangle(canvas,
                          (box["x1"], label_y - th - baseline - 2),
                          (box["x1"] + tw + 4, label_y + baseline - 2),
                          box_color, cv2.FILLED)
            cv2.putText(canvas, label, (box["x1"] + 2, label_y - baseline),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                        (255, 255, 255), 1, cv2.LINE_AA)

    fname = output_path / f"page{page_index:03d}_detections.png"
    cv2.imwrite(str(fname), canvas)
    print(f"[Viz] Page {page_index}: {len(boxes)} box(es) drawn -> {fname.name}")

# ── Training helpers ──────────────────────────────────────────────────────────

def train_yolov8(
    data_yaml: str,
    base_weights: str = "yolov8n.pt",
    epochs: int = 50,
    img_size: int = 640,
    batch: int = 8,
    project: str = "runs/train",
    name: str = "piyanota_staff_detector",
    degrees: float = 0.0,
    perspective: float = 0.0,
    shear: float = 0.0,
    fliplr: float = 0.5,
):
    """
    Fine-tunes YOLOv8 on annotated staff region data.

    Args:
        data_yaml:    Path to dataset YAML (see data/dataset.yaml template).
        base_weights: Starting weights — 'yolov8n.pt' for pretrained backbone.
        epochs:       Training epochs (50 is good for a first run).
        img_size:     Input resolution (640 recommended).
        project:      Output directory for training runs.
        name:         Run name (subfolder under project/).
        degrees:      Rotation augmentation range in degrees (+/-). Defaults to
            Ultralytics' library default (0.0 — no rotation augmentation).
        perspective:  Perspective-warp augmentation fraction. Defaults to
            Ultralytics' library default (0.0 — no perspective augmentation).
            Ultralytics' own docs describe ~0-0.001 as the sane range; values
            above that destabilize box regression.
        shear:        Shear augmentation range in degrees (+/-). Defaults to
            Ultralytics' library default (0.0 — no shear augmentation).
        fliplr:       Horizontal-flip augmentation probability. Defaults to
            Ultralytics' library default (0.5).

    Usage:
        python stage2_detection.py --train
    """
    model = YOLO(base_weights)
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=img_size,
        batch=batch,
        project=project,
        name=name,
        exist_ok=True,
        resume=False,
        amp=False,       # ← force disable AMP explicitly
        lr0=0.001,       # ← lower from default 0.01
        lrf=0.001,
        degrees=degrees,
        perspective=perspective,
        shear=shear,
        fliplr=fliplr,
        )
    print(f"\n[Training] Complete. Best weights saved to: "
          f"{project}/{name}/weights/best.pt")
    return results


def evaluate_model(weights: str, data_yaml: str):
    """Runs mAP evaluation on the test split."""
    model = YOLO(weights)
    metrics = model.val(data=data_yaml)
    print(f"\n[Eval] mAP50:    {metrics.box.map50:.4f}")
    print(f"[Eval] mAP50-95: {metrics.box.map:.4f}")
    return metrics


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_boxes(results) -> list:
    """Parses Ultralytics Results into a list of box dicts."""
    boxes = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            boxes.append({
                "x1": int(x1), "y1": int(y1),
                "x2": int(x2), "y2": int(y2),
                "cy": (y1 + y2) / 2,
                "conf": conf,
            })
    return boxes


STRIP_HEIGHT = 64   # ← match Stage 3 img_height directly

def _crop_and_resize(image: np.ndarray, box: dict, target_height: int,
                     padding: float = 0.5) -> np.ndarray:  # ← 30% not 150%
    img_h, img_w = image.shape[:2]
    x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]

    pad = int((y2 - y1) * padding)
    y1 = max(0, y1 - pad)
    y2 = min(img_h, y2 + pad)

    crop = image[y1:y2, max(0, x1):x2]

    if crop.size == 0:
        return np.zeros((target_height, target_height, 3), dtype=np.uint8)
    h, w = crop.shape[:2]
    new_w = int(w * (target_height / h))
    resized = cv2.resize(crop, (new_w, target_height), interpolation=cv2.INTER_AREA)
    return resized


def _report(voice_sequences: dict):
    print("\n[Stage 2] Voice strip counts:")
    for voice, strips in voice_sequences.items():
        print(f"  {voice}: {len(strips)} strip(s)")
    empty = [v for v, s in voice_sequences.items() if len(s) == 0]
    if empty:
        print(f"\n  WARNING: Missing voice(s): {empty}. "
              f"Check detection results or recapture.")
        

# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from stage1_preprocessing import preprocess_batch

    parser = argparse.ArgumentParser(description="PiyaNota Stage 2 — Staff Detection")
    parser.add_argument("--input",   default="data/raw",           help="Raw images dir")
    parser.add_argument("--prep",    default="data/preprocessed",  help="Preprocessed dir")
    parser.add_argument("--strips",  default="data/strips",        help="Output strips dir")
    parser.add_argument("--weights", default="staff_detector_files\\weights\\best.pt", help="YOLOv8 weights")
    parser.add_argument("--train",   action="store_true",          help="Run training instead")
    parser.add_argument("--data",    default="data/dataset.yaml",  help="Dataset YAML (for training)")
    parser.add_argument("--viz",     action="store_true",          help="Visualize detections with red boxes")
    args = parser.parse_args()

    if args.train:
        train_yolov8(data_yaml=args.data, base_weights=args.weights)
    else:
        pages = preprocess_batch(args.input, args.prep, save_debug=True)
        voices = detect_staff_regions(
            pages,
            model_weights=args.weights,
            output_dir=args.strips,
            save_viz=args.viz,        # ← one call does both
        )
        print("\nStage 2 complete. Strips ready for Stage 3 (CRNN-CTC).")
