"""
PiyaNota — Staff Detector Training Script
==========================================
Trains YOLOv8n on the converted DeepScoresV2 staff dataset.
Run this AFTER prepare_deepscore.py has finished.

Recommended command for a Monday defense:
    python train_staff_detector.py

This uses 30 epochs and yolov8n (fastest) by default.
Swap to yolov8s.pt for slightly better accuracy if time allows.

After training, best weights will be at:
    runs/train/piyanota_staff_detector/weights/best.pt

Plug those into run_pipeline.py:
    python run_pipeline.py --input data/raw \\
        --weights runs/train/piyanota_staff_detector/weights/best.pt
"""
import torch
torch.backends.cudnn.benchmark = False

from stage2_detection import train_yolov8, evaluate_model
from pathlib import Path
import argparse

DATA_YAML    = "data/staff_dataset/dataset.yaml"
BASE_WEIGHTS = "yolov8n.pt"    # smallest + fastest; use yolov8s.pt for more accuracy
EPOCHS       = 30              # 30 is enough for a proof-of-concept demo
IMG_SIZE     = 416
BATCH_SIZE   = 4
PROJECT      = "runs/train"
NAME         = "piyanota_staff_detector"

# Camera-robustness augmentation overrides — Ultralytics' defaults (degrees=0.0,
# perspective=0.0, shear=0.0, fliplr=0.5) assume a generic detection dataset,
# not phone photos of sheet music. Stage 1 (stage1_preprocessing.py) already
# deskews each page, so these are a residual-error margin, not a substitute for
# that step.
ROTATION_DEGREES     = 5.0     # small rotation tolerance for residual deskew error
PERSPECTIVE_FRACTION = 0.0006  # Ultralytics docs: keep within ~0-0.001, or box regression destabilizes
SHEAR_DEGREES        = 2.0     # small shear tolerance for residual lens/angle distortion
HORIZONTAL_FLIP_PROB = 0.0     # a photographed choral octavo is never mirrored in production


def main(eval_only: bool = False, weights: str = None):
    if eval_only:
        w = weights or f"{PROJECT}/{NAME}/weights/best.pt"
        print(f"[Eval] Evaluating weights: {w}")
        evaluate_model(weights=w, data_yaml=DATA_YAML)
        return

    if not Path(DATA_YAML).exists():
        print(f"ERROR: Dataset YAML not found at: {DATA_YAML}")
        print("Run prepare_deepscore.py first:\n")
        print("  python prepare_deepscore.py --ds2 path/to/ds2_dense --out data/staff_dataset")
        return

    print("=" * 55)
    print("  PiyaNota — Staff Detector Training")
    print("=" * 55)
    print(f"  Base weights : {BASE_WEIGHTS}")
    print(f"  Dataset      : {DATA_YAML}")
    print(f"  Epochs       : {EPOCHS}")
    print(f"  Image size   : {IMG_SIZE}")
    print(f"  Augment      : degrees={ROTATION_DEGREES}, perspective={PERSPECTIVE_FRACTION}, "
          f"shear={SHEAR_DEGREES}, fliplr={HORIZONTAL_FLIP_PROB}")
    print(f"  Output       : {PROJECT}/{NAME}/weights/best.pt")
    print("=" * 55 + "\n")

    train_yolov8(
        data_yaml=DATA_YAML,
        base_weights=BASE_WEIGHTS,
        epochs=EPOCHS,
        img_size=IMG_SIZE,
        batch=BATCH_SIZE,
        project=PROJECT,
        name=NAME,
        degrees=ROTATION_DEGREES,
        perspective=PERSPECTIVE_FRACTION,
        shear=SHEAR_DEGREES,
        fliplr=HORIZONTAL_FLIP_PROB,
    )

    best_weights = f"{PROJECT}/{NAME}/weights/best.pt"
    print("\n" + "=" * 55)
    print("  Training complete. Running evaluation on test set...")
    print("=" * 55)
    evaluate_model(weights=best_weights, data_yaml=DATA_YAML)

    print("\n" + "=" * 55)
    print("  Ready for inference. Run the full pipeline with:")
    print(f"    python run_pipeline.py --input data/raw \\")
    print(f"      --weights {best_weights}")
    print("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PiyaNota Staff Detector Trainer")
    parser.add_argument("--eval",    action="store_true", help="Evaluate only (skip training)")
    parser.add_argument("--weights", default=None,        help="Weights to evaluate (--eval mode)")
    args = parser.parse_args()
    main(eval_only=args.eval, weights=args.weights)
