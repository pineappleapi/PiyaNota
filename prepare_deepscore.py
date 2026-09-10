"""
PiyaNota — DeepScoresV2 → YOLO Converter (staff class only)
============================================================
Converts ds2_dense annotations to YOLO format for YOLOv8 training.
Keeps only the 'staff' class (category ids 135 and 208).

Verified ds2_dense folder structure:
    ds2_dense/
        images/                  ← score page images (.png)
        instance/                ← ignored
        segmentation/            ← ignored
        deepscores_train.json
        deepscores_test.json

Verified JSON schema:
    categories  : dict  { "135": {"name": "staff", "annotation_set": "deepscores", ...},
                          "208": {"name": "staff", "annotation_set": "muscima++",  ...}, ... }
    images      : list  [ {"id": 2, "filename": "lg-....png", "width": 1960,
                            "height": 2772, "ann_ids": ["1113019", ...]}, ... ]
    annotations : dict  { "1020": {"a_bbox": [116.0, 139.0, 2315.0, 206.0],
                                   "cat_id": ["135", "208"],
                                   "img_id": "679", ...}, ... }

    a_bbox = [x_min, y_min, x_max, y_max]   ← axis-aligned bounding box
    cat_id = list of string ids              ← annotation belongs to BOTH sets

Usage:
    python prepare_deepscore.py --ds2 path/to/ds2_dense --out data/staff_dataset

    ds2_dense should contain images/, deepscores_train.json, deepscores_test.json
Then train:
    python train_staff_detector.py
"""

import json
import shutil
import argparse
import random
from pathlib import Path


# ── Config ─────────────────────────────────────────────────────────────────────
VAL_SPLIT = 0.1   # fraction of train images held out for validation
SEED      = 42


def convert(ds2_root: Path, out_root: Path):
    random.seed(SEED)

    # ds2_root points directly to the folder containing images/ and the JSON files
    root = ds2_root

    img_dir    = root / "images"
    train_json = root / "deepscores_train.json"
    test_json  = root / "deepscores_test.json"

    # ── Validate ───────────────────────────────────────────────────────────────
    for p in (img_dir, train_json, test_json):
        if not p.exists():
            raise FileNotFoundError(
                f"Expected path not found: {p}\n"
                f"Contents of {root}: {[f.name for f in root.iterdir()]}"
            )

    # ── Output dirs ────────────────────────────────────────────────────────────
    for split in ("train", "val", "test"):
        (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    total_images = 0
    total_boxes  = 0

    for json_path, is_train in [(train_json, True), (test_json, False)]:
        split_label = "train" if is_train else "test"
        print(f"\n[Convert] Loading {json_path.name} ...")

        with open(json_path, encoding="utf-8") as f:
            ds2 = json.load(f)

        # ── Staff category ids ─────────────────────────────────────────────────
        # categories is a dict: {"135": {"name": "staff", ...}, ...}
        # Both id "135" (deepscores) and "208" (muscima++) map to "staff"
        staff_cat_ids = {
            k for k, v in ds2["categories"].items()
            if v.get("name", "").lower() == "staff"
        }
        print(f"  Staff category ids: {staff_cat_ids}")

        # ── Image id → metadata ────────────────────────────────────────────────
        # images is a list: [{"id": 2, "filename": "...", "width": W, "height": H, "ann_ids": [...]}, ...]
        # img_id in annotations is a STRING matching str(image["id"])
        id_to_img = {str(img["id"]): img for img in ds2["images"]}

        # ── Group staff annotations by image id ────────────────────────────────
        # annotations is a dict: {"1020": {"cat_id": ["135","208"], "img_id": "679", ...}}
        # cat_id is a list of strings — annotation belongs to both annotation sets
        img_to_anns: dict[str, list] = {}
        for ann in ds2["annotations"].values():
            cat_ids = ann.get("cat_id", [])
            # Keep if ANY of its cat_ids is a staff id
            if not any(c in staff_cat_ids for c in cat_ids):
                continue
            img_id = str(ann["img_id"])
            img_to_anns.setdefault(img_id, []).append(ann)

        img_ids = list(img_to_anns.keys())
        print(f"  Images with staff annotations: {len(img_ids)}")

        # ── Validation split (train only) ──────────────────────────────────────
        if is_train:
            random.shuffle(img_ids)
            n_val     = max(1, int(len(img_ids) * VAL_SPLIT))
            val_ids   = set(img_ids[:n_val])
            train_ids = set(img_ids[n_val:])
            split_map = {**{i: "val"   for i in val_ids},
                         **{i: "train" for i in train_ids}}
        else:
            split_map = {i: "test" for i in img_ids}

        # ── Convert each image ─────────────────────────────────────────────────
        for img_id, anns in img_to_anns.items():
            meta = id_to_img.get(img_id)
            if meta is None:
                print(f"  WARNING: img_id {img_id} not found in images list, skipping.")
                continue

            filename = meta["filename"]   # e.g. "lg-94161796-aug-gonville--page-3.png"
            img_w    = int(meta["width"])
            img_h    = int(meta["height"])
            dest     = split_map[img_id]

            # Locate source image
            src = img_dir / filename
            if not src.exists():
                hits = list(img_dir.rglob(filename))
                if not hits:
                    print(f"  WARNING: image file not found: {filename}, skipping.")
                    continue
                src = hits[0]

            # Copy image to output split folder
            dst_img = out_root / "images" / dest / src.name
            shutil.copy2(src, dst_img)

            # Build YOLO label lines
            label_lines = []
            for ann in anns:
                # a_bbox = [x_min, y_min, x_max, y_max]
                x_min, y_min, x_max, y_max = ann["a_bbox"]
                bw = x_max - x_min
                bh = y_max - y_min

                if bw <= 0 or bh <= 0:
                    continue

                # Convert to YOLO normalized center format
                cx = (x_min + bw / 2) / img_w
                cy = (y_min + bh / 2) / img_h
                nw = bw / img_w
                nh = bh / img_h

                # Clamp to [0.0, 1.0]
                cx = max(0.0, min(1.0, cx))
                cy = max(0.0, min(1.0, cy))
                nw = max(0.0, min(1.0, nw))
                nh = max(0.0, min(1.0, nh))

                label_lines.append(f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
                total_boxes += 1

            if not label_lines:
                continue

            dst_lbl = out_root / "labels" / dest / (src.stem + ".txt")
            dst_lbl.write_text("\n".join(label_lines))
            total_images += 1

        print(f"  Done with {split_label}.")

    # ── Write dataset.yaml ─────────────────────────────────────────────────────
    yaml_path = out_root / "dataset.yaml"
    yaml_path.write_text(
        f"# PiyaNota — Staff detection dataset\n"
        f"# Source: DeepScoresV2 dense, staff class only (cat_ids 135 + 208)\n"
        f"path: {out_root.resolve()}\n"
        f"train: images/train\n"
        f"val:   images/val\n"
        f"test:  images/test\n\n"
        f"nc: 1\n"
        f"names: ['staff']\n"
    )

    print(f"\n{'='*55}")
    print(f"  Conversion complete")
    print(f"{'='*55}")
    print(f"  Images copied     : {total_images}")
    print(f"  Staff boxes total : {total_boxes}")
    print(f"  Output folder     : {out_root.resolve()}")
    print(f"  Dataset YAML      : {yaml_path}")
    print(f"\n  Next step — train:")
    print(f"    python train_staff_detector.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert DeepScoresV2 dense -> YOLO format (staff class only)"
    )
    parser.add_argument(
        "--ds2", required=True,
        help="Path to the ds2_dense folder (the one containing images/ and deepscores_train.json)"
    )
    parser.add_argument(
        "--out", default="data/staff_dataset",
        help="Output directory for the YOLO-format dataset"
    )
    args = parser.parse_args()
    convert(Path(args.ds2), Path(args.out))