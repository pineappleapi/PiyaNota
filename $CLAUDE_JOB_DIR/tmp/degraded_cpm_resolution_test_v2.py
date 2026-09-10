"""v2: addresses ml-cv-lead's review of the first pass --
  1. Draw the 150-sample set from a proxy held-out slice (first 10% of a
     deterministic sorted-by-stem glob, same ordering convention already used
     by compare_omr_baselines.py) instead of a full-corpus random shuffle that
     was very likely dominated by training-set samples (90/10 split per the
     Kaggle training notebook). NOTE: this is a best-effort proxy, not a
     verified reproduction of the original Kaggle val split -- the training
     notebook's own split was taken from an *unsorted* glob.glob() order on
     Kaggle's filesystem, which cannot be exactly reproduced locally. Flagged
     as a residual limitation, not silently assumed away.
  2. Persist per-sample raw records so a real paired (McNemar-style) comparison
     and a majority-class check can be computed, not just marginal accuracy.
"""
import sys
sys.path.insert(0, r"D:\PiyaNota (Code)")
import glob
import json
import random
import collections
from pathlib import Path

import cv2
import numpy as np
import torch

from stage3_transcription import load_model, transcribe_strip

random.seed(42)

WEIGHTS = r"D:\PiyaNota (Code)\music_symbol_detection\crnn_cameraprimus_transcription.pt"
STRIP_HEIGHT = 64
NATIVE_TARGET = 40
PADDING = 0.5
N_SAMPLES = 150

cpm_root = Path(r"D:\PiyaNota (Code)\datasets\CameraPriMus\CameraPrIMuS - Copy\Corpus")

# Proxy held-out slice: sorted-by-stem order (matches compare_omr_baselines.py's
# discover_samples() convention), first 10% -- same ratio as the training
# notebook's val_size = int(0.1 * len(indices)).
entries = sorted([d for d in cpm_root.iterdir() if d.is_dir()])
val_size = int(0.1 * len(entries))
proxy_val_entries = entries[:val_size]
print(f"Total corpus dirs: {len(entries)}, proxy-val slice: {len(proxy_val_entries)}")

agnostic_files = []
for d in proxy_val_entries:
    stem = d.name
    ap = d / f"{stem}.agnostic"
    if ap.exists():
        agnostic_files.append(str(ap))
random.shuffle(agnostic_files)
print(f"Usable .agnostic files in proxy-val slice: {len(agnostic_files)}")


def first_clef(tokens):
    for t in tokens:
        if t.startswith("clef."):
            return t
    return None


def ground_truth_clef(agnostic_path):
    with open(agnostic_path, encoding="utf-8", errors="ignore") as f:
        tokens = f.read().split()
    return first_clef(tokens)


def pad_and_resize(gray_img: np.ndarray, target_height: int, padding: float) -> np.ndarray:
    h, w = gray_img.shape[:2]
    pad = int(h * padding)
    padded = cv2.copyMakeBorder(gray_img, pad, pad, 0, 0, cv2.BORDER_CONSTANT, value=255)
    h2, w2 = padded.shape[:2]
    new_w = max(1, int(w2 * target_height / h2))
    return cv2.resize(padded, (new_w, target_height), interpolation=cv2.INTER_AREA)


def build_sample(png_path: str, degrade: bool, pad: bool):
    img = cv2.imread(png_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    if degrade:
        h, w = img.shape[:2]
        new_w = max(1, int(w * NATIVE_TARGET / h))
        img = cv2.resize(img, (new_w, NATIVE_TARGET), interpolation=cv2.INTER_AREA)
    if pad:
        return pad_and_resize(img, STRIP_HEIGHT, PADDING)
    h, w = img.shape[:2]
    new_w = max(1, int(w * STRIP_HEIGHT / h))
    return cv2.resize(img, (new_w, STRIP_HEIGHT), interpolation=cv2.INTER_AREA)


def main():
    device = torch.device("cpu")
    model, device = load_model(WEIGHTS, device=device)

    stems_used = []
    records = []
    count = 0
    for agnostic_path in agnostic_files:
        if count >= N_SAMPLES:
            break
        img_path = agnostic_path.replace(".agnostic", ".png")
        gt = ground_truth_clef(agnostic_path)
        if gt is None or not Path(img_path).exists():
            continue

        cell_preds = {}
        for cell, (degrade, pad) in {
            "A": (False, False), "B": (False, True),
            "C": (True, False),  "D": (True, True),
        }.items():
            strip = build_sample(img_path, degrade, pad)
            if strip is None:
                cell_preds[cell] = None
                continue
            strip_bgr = cv2.cvtColor(strip, cv2.COLOR_GRAY2BGR)
            tokens = transcribe_strip(strip_bgr, model, device, img_height=STRIP_HEIGHT)
            cell_preds[cell] = first_clef(tokens)

        records.append({"stem": Path(agnostic_path).parent.name, "gt": gt, **cell_preds})
        count += 1

    out_path = Path(r"D:\PiyaNota (Code)\$CLAUDE_JOB_DIR\tmp\degraded_cpm_v2_records.json")
    out_path.write_text(json.dumps(records, indent=2))
    print(f"n={len(records)} records saved to {out_path}")

    # -- Marginal accuracy per cell --
    for cell in ("A", "B", "C", "D"):
        correct = sum(1 for r in records if r[cell] == r["gt"])
        wrong = len(records) - correct
        print(f"\n{cell}: accuracy={100*correct/len(records):.1f}% ({correct} correct, {wrong} wrong)")
        wrong_preds = collections.Counter(r[cell] for r in records if r[cell] != r["gt"])
        print(f"  wrong-pred distribution: {wrong_preds.most_common(6)}")

    # -- True-label (ground truth) distribution in this sample, for the majority-class check --
    gt_dist = collections.Counter(r["gt"] for r in records)
    print(f"\nTrue-label distribution in this {len(records)}-sample draw:")
    for clef, n in gt_dist.most_common():
        print(f"  {clef:15s} {n:4d} ({100*n/len(records):.1f}%)")

    # -- Paired McNemar-style disagreement: A vs C (resolution effect, no padding) --
    def mcnemar(cell_x, cell_y, label):
        x_right_y_wrong = sum(1 for r in records if r[cell_x] == r["gt"] and r[cell_y] != r["gt"])
        x_wrong_y_right = sum(1 for r in records if r[cell_x] != r["gt"] and r[cell_y] == r["gt"])
        both_right = sum(1 for r in records if r[cell_x] == r["gt"] and r[cell_y] == r["gt"])
        both_wrong = sum(1 for r in records if r[cell_x] != r["gt"] and r[cell_y] != r["gt"])
        print(f"\n{label}: both_right={both_right} both_wrong={both_wrong} "
              f"{cell_x}_only_right={x_right_y_wrong} {cell_y}_only_right={x_wrong_y_right}")
        # Simple McNemar chi-square (no continuity correction) when discordant pairs exist
        b, c = x_right_y_wrong, x_wrong_y_right
        if b + c > 0:
            chi2 = (b - c) ** 2 / (b + c)
            print(f"  McNemar chi2={chi2:.2f} on {b+c} discordant pairs (b={b}, c={c})")
        else:
            print("  No discordant pairs -- cells agree on every sample.")

    mcnemar("A", "C", "A vs C (native vs degraded-res, both unpadded)")
    mcnemar("B", "D", "B vs D (native vs degraded-res, both padded)")

    # -- Majority-class collapse check for B/D wrong predictions --
    modal_true_clef = gt_dist.most_common(1)[0][0]
    for cell in ("B", "D"):
        wrong_records = [r for r in records if r[cell] != r["gt"]]
        matches_modal_true = sum(1 for r in wrong_records if r["gt"] == modal_true_clef)
        print(f"\n{cell} wrong predictions where true label IS the sample's modal true clef "
              f"({modal_true_clef}): {matches_modal_true}/{len(wrong_records)}")


if __name__ == "__main__":
    main()
