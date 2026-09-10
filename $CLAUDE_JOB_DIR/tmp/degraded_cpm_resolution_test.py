"""ml-cv-lead-approved test for fix/bug002-strip-height: does degrading Camera-PrIMuS
source images to real screenshots' native capture resolution (~37-44px tall, pre-padding)
reproduce the clef.C-L3 collapse -- with font/layout/monophony/no-label-text/target-height
all held fixed at the training distribution? Single variable = native source resolution.

Pipeline per sample:
  CPM clean render (native ~144px tall)
    -> downsample to ~40px tall (INTER_AREA)         <- the ONE manipulated variable
    -> pad 50% each side (matches stage2._crop_and_resize's padding=0.5, pad with white
       since there's no real page content to bleed in -- isolates resolution, not label text)
    -> resize to STRIP_HEIGHT=64 (INTER_AREA)          <- identical to production/training resize
    -> transcribe_strip()
Control: same images at native CPM resolution (skip the downsample step) through the same
pad+resize+transcribe path, to sanity-check the harness reproduces the known-good CPM baseline.
"""
import sys
sys.path.insert(0, r"D:\PiyaNota (Code)")
import glob
import random
import cv2
import numpy as np
import torch

from stage3_transcription import load_model, transcribe_strip

random.seed(42)

WEIGHTS = r"D:\PiyaNota (Code)\music_symbol_detection\crnn_cameraprimus_transcription.pt"
STRIP_HEIGHT = 64
NATIVE_TARGET = 40   # matches the ~37-44px real YOLO box height range measured this session
PADDING = 0.5        # matches stage2_detection._crop_and_resize's padding param exactly

cpm_root = r"D:\PiyaNota (Code)\datasets\CameraPriMus\CameraPrIMuS - Copy\Corpus"
agnostic_files = glob.glob(f"{cpm_root}/**/*.agnostic", recursive=True)
random.shuffle(agnostic_files)


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


def run(n_samples: int, degrade: bool, pad: bool, model, device):
    results = []
    count = 0
    for agnostic_path in agnostic_files:
        if count >= n_samples:
            break
        img_path = agnostic_path.replace(".agnostic", ".png")
        gt = ground_truth_clef(agnostic_path)
        if gt is None:
            continue
        strip = build_sample(img_path, degrade, pad)
        if strip is None:
            continue
        strip_bgr = cv2.cvtColor(strip, cv2.COLOR_GRAY2BGR)
        tokens = transcribe_strip(strip_bgr, model, device, img_height=STRIP_HEIGHT)
        pred = first_clef(tokens)
        results.append((gt, pred, pred == gt))
        count += 1
    return results


def summarize(results, label):
    total = len(results)
    correct = sum(1 for _, _, m in results if m)
    print(f"\n=== {label} ===  n={total}  accuracy={100*correct/total:.1f}%")
    import collections
    wrong_preds = collections.Counter(p for gt, p, m in results if not m)
    print("  most common wrong predictions:", wrong_preds.most_common(5))
    clef_c_l3_count = sum(1 for _, p, _ in results if p == "clef.C-L3")
    print(f"  predicted clef.C-L3: {clef_c_l3_count}/{total} ({100*clef_c_l3_count/total:.1f}%)")


def main():
    device = torch.device("cpu")
    model, device = load_model(WEIGHTS, device=device)

    N = 150
    r1 = run(N, degrade=False, pad=False, model=model, device=device)
    summarize(r1, "A: native res, NO padding (true baseline sanity check -- should match known 98%+ CPM SER)")

    r2 = run(N, degrade=False, pad=True, model=model, device=device)
    summarize(r2, "B: native res, WITH 50% blank padding (isolates padding-alone effect)")

    r3 = run(N, degrade=True, pad=False, model=model, device=device)
    summarize(r3, f"C: downsampled to {NATIVE_TARGET}px, NO padding (isolates resolution-alone effect)")

    r4 = run(N, degrade=True, pad=True, model=model, device=device)
    summarize(r4, f"D: downsampled to {NATIVE_TARGET}px, WITH padding (both combined, matches real pipeline shape)")


if __name__ == "__main__":
    main()
