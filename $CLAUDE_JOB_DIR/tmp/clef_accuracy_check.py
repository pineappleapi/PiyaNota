import sys
sys.path.insert(0, r"D:\PiyaNota (Code)")
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

# Ground truth per BUG-011's consistency-check table (same S/A/T/B pattern,
# 2 systems, on every one of the 6 screenshots -- all same piece/layout).
GROUND_TRUTH = {
    "Soprano": "treble",
    "Alto": "treble",
    "Tenor": "treble-8vb",
    "Bass": "bass",
}

# BUG-012: Bass/system-2 strip has no clef at all in the ORIGINAL baseline on
# these 5 screenshots -- not a fair test of the clef-misread fix, contaminates
# the comparison. 5753 sys2 Bass is the one exception with real content.
BUG012_AFFECTED = {("shot", 2, "Bass"), ("5751", 2, "Bass"), ("5752", 2, "Bass"),
                    ("5754", 2, "Bass"), ("5755", 2, "Bass")}


def clef_matches(token: str, voice: str) -> bool:
    if token is None:
        return False
    expected = GROUND_TRUTH[voice]
    if expected == "treble":
        return token == "clef.G-L2"
    if expected == "treble-8vb":
        # Tenor: plain treble clef token, octave handled downstream by voice-aware lookup
        return token == "clef.G-L2"
    if expected == "bass":
        return token == "clef.F-L4"
    return False


def first_clef_token(tokens):
    for t in tokens:
        if t.startswith("clef."):
            return t
    return None


def run_variant(model, device, blank_left_margin: bool, label: str):
    rows = []
    for key, path in PAGES.items():
        img = cv2.imread(path)
        if img is None:
            print(f"MISSING page image: {path}")
            continue
        voices = s2.detect_staff_regions(
            [(img, 1)],
            model_weights=YOLO_WEIGHTS,
            output_dir=str(Path(r"D:\PiyaNota (Code)\$CLAUDE_JOB_DIR\tmp\clef_check_strips") / label / key),
            save_strips=False,
            blank_left_margin=blank_left_margin,
        )
        # voices: {"Soprano": [(strip, page_index, sys_idx, voice, v_idx), ...], ...}
        for voice, entries in voices.items():
            for strip, page_index, sys_idx, voice_name, v_idx in entries:
                tokens = transcribe_strip(strip, model, device, img_height=STRIP_HEIGHT)
                clef_tok = first_clef_token(tokens)
                match = clef_matches(clef_tok, voice_name)
                affected = (key, sys_idx, voice_name) in BUG012_AFFECTED
                rows.append({
                    "screenshot": key, "voice": voice_name, "sys": sys_idx,
                    "predicted": clef_tok, "match": match, "bug012_affected": affected,
                })
    return rows


def summarize(rows, label):
    total = len(rows)
    matches = sum(1 for r in rows if r["match"])
    clean_rows = [r for r in rows if not r["bug012_affected"]]
    clean_matches = sum(1 for r in clean_rows if r["match"])
    print(f"\n=== {label} ===")
    print(f"All strips:            {matches}/{total} = {100*matches/total:.1f}%")
    if clean_rows:
        print(f"Excl. BUG-012 strips:  {clean_matches}/{len(clean_rows)} = {100*clean_matches/len(clean_rows):.1f}%")
    for r in rows:
        flag = " [BUG-012]" if r["bug012_affected"] else ""
        status = "OK" if r["match"] else "WRONG"
        print(f"  {r['screenshot']:5s} sys{r['sys']} {r['voice']:8s} -> {r['predicted']!s:14s} {status}{flag}")
    return matches, total, clean_matches, len(clean_rows)


def main():
    device = torch.device("cpu")
    model, device = load_model(WEIGHTS, device=device)

    before_rows = run_variant(model, device, blank_left_margin=False, label="before")
    after_rows = run_variant(model, device, blank_left_margin=True, label="after")

    b_m, b_t, b_cm, b_ct = summarize(before_rows, "BEFORE (no blanking, v1/original baseline)")
    a_m, a_t, a_cm, a_ct = summarize(after_rows, "AFTER (v2 vertical-extent blanking)")

    print("\n=== Summary ===")
    print(f"Before: {b_m}/{b_t} ({100*b_m/b_t:.1f}%) all | {b_cm}/{b_ct} ({100*b_cm/b_ct:.1f}%) excl. BUG-012")
    print(f"After:  {a_m}/{a_t} ({100*a_m/a_t:.1f}%) all | {a_cm}/{a_ct} ({100*a_cm/a_ct:.1f}%) excl. BUG-012")


if __name__ == "__main__":
    main()
