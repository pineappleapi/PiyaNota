"""ml-cv-lead's promoted lead: A-vs-B / C-vs-D on the CPM proxy showed blank
vertical padding alone (independent of resolution) collapses clef accuracy
from 100% to ~20-25%. Stage 2's real `_crop_and_resize()` pads every detected
box by `padding=0.5` (50% of box height, each side) before the 64px resize --
a currently-active production step. This script tests crop-margin size as a
single variable directly against the real 6-screenshot/48-strip set: same
YOLO boxes, same STRIP_HEIGHT=64, same model, only `padding` varies.

NOT a code change to stage2_detection.py -- _crop_and_resize is monkeypatched
for the duration of this test only, to control `padding` without touching the
committed default (still under investigation, not yet a proposed fix).
"""
import sys
sys.path.insert(0, r"D:\PiyaNota (Code)")
import functools
import cv2
import torch
from pathlib import Path

import stage2_detection as s2
from stage3_transcription import load_model, transcribe_strip

WEIGHTS = r"D:\PiyaNota (Code)\music_symbol_detection\crnn_cameraprimus_transcription.pt"
YOLO_WEIGHTS = r"D:\PiyaNota (Code)\staff_detector_files\weights\best.pt"
STRIP_HEIGHT = 64

PAGES = {
    "shot": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_shot\page_001_preprocessed.png",
    "5751": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5751\page_001_preprocessed.png",
    "5752": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5752\page_001_preprocessed.png",
    "5753": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5753\page_001_preprocessed.png",
    "5754": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5754\page_001_preprocessed.png",
    "5755": r"C:\Users\paul_\.claude\jobs\e65e784a\tmp\pilot_prep_5755\page_001_preprocessed.png",
}
GROUND_TRUTH = {"Soprano": "treble", "Alto": "treble", "Tenor": "treble-8vb", "Bass": "bass"}
BUG012_AFFECTED = {("shot", 2, "Bass"), ("5751", 2, "Bass"), ("5752", 2, "Bass"),
                    ("5754", 2, "Bass"), ("5755", 2, "Bass")}

_ORIG_CROP_AND_RESIZE = s2._crop_and_resize


def clef_matches(token, voice):
    if token is None:
        return False
    expected = GROUND_TRUTH[voice]
    if expected in ("treble", "treble-8vb"):
        return token == "clef.G-L2"
    if expected == "bass":
        return token == "clef.F-L4"
    return False


def first_clef_token(tokens):
    for t in tokens:
        if t.startswith("clef."):
            return t
    return None


def run_at_padding(padding_value, model, device):
    def patched(image, box, target_height, padding=padding_value, strip_id=""):
        return _ORIG_CROP_AND_RESIZE(image, box, target_height, padding=padding_value, strip_id=strip_id)
    s2._crop_and_resize = patched
    try:
        rows = []
        for key, path in PAGES.items():
            img = cv2.imread(path)
            voices = s2.detect_staff_regions(
                [(img, 1)], model_weights=YOLO_WEIGHTS,
                output_dir=str(Path(r"D:\PiyaNota (Code)\$CLAUDE_JOB_DIR\tmp\padding_ablation_strips") / f"p{padding_value}" / key),
                save_strips=False,
            )
            for voice, entries in voices.items():
                for strip, page_index, sys_idx, voice_name, v_idx in entries:
                    tokens = transcribe_strip(strip, model, device, img_height=STRIP_HEIGHT)
                    clef_tok = first_clef_token(tokens)
                    match = clef_matches(clef_tok, voice_name)
                    affected = (key, sys_idx, voice_name) in BUG012_AFFECTED
                    rows.append({"screenshot": key, "voice": voice_name, "sys": sys_idx,
                                 "predicted": clef_tok, "match": match, "bug012_affected": affected})
        return rows
    finally:
        s2._crop_and_resize = _ORIG_CROP_AND_RESIZE


def summarize(rows, label):
    total = len(rows)
    matches = sum(1 for r in rows if r["match"])
    clean = [r for r in rows if not r["bug012_affected"]]
    clean_matches = sum(1 for r in clean if r["match"])
    print(f"\n=== {label} ===")
    print(f"All strips:           {matches}/{total} = {100*matches/total:.1f}%")
    if clean:
        print(f"Excl. BUG-012 strips: {clean_matches}/{len(clean)} = {100*clean_matches/len(clean):.1f}%")
    import collections
    wrong = collections.Counter(r["predicted"] for r in clean if not r["match"])
    print(f"  wrong-pred distribution (excl. BUG-012): {wrong.most_common(6)}")


def main():
    device = torch.device("cpu")
    model, device = load_model(WEIGHTS, device=device)

    for padding_value in (0.5, 0.25, 0.1, 0.0):
        rows = run_at_padding(padding_value, model, device)
        summarize(rows, f"padding={padding_value}")


if __name__ == "__main__":
    main()
