"""PiyaNota one-page demo: one score page through Stages 1-5 with the current system.

Current system = Stage 1 (keep_unmasked) -> Stage 2 YOLOv8 -> ClefKeyNet clef/key/octave per strip ->
fine-tuned CRNN (seed1 default) -> Stage 4 reconstruction -> Stage 5 MIDI/MP3. It composes the stage
functions in the same order as ``stage3_transcription.run_stages_1_to_3`` and
``stage5_synthesis.run_full_pipeline_with_report``; it calls them directly only so that it can (a) pass
explicit viz/events folders (those runners fall back to the dead ``D:\\PiyaNota (Code)`` defaults,
BUG-017) and (b) print the per-system ClefKeyNet decisions, which the runners do not return.

Runs on CPU only: the dev GPU has an open nondeterminism/hang bug (BUG-013).

Usage (from the repo root of this worktree):
    python demo_one_page.py --page D:/PiyaNota/data/piyanota_dataset/gaano_ko_ikaw_kamahal_pg02.jpg \
        --out output/demo_gaano_pg02
"""
from __future__ import annotations

import os

# Must precede any torch import (also the ones inside the stage modules).
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import torch  # noqa: E402

torch.cuda.is_available = lambda: False  # stage modules and ultralytics pick their device from this

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import stage3_clefkey  # noqa: E402
from stage1_preprocessing import preprocess_batch  # noqa: E402
from stage2_detection import detect_staff_regions  # noqa: E402
from stage3_transcription import transcribe_voice_sequences  # noqa: E402
from stage4_reconstruction import VOICES, reconstruct_satb_with_report  # noqa: E402
from stage5_synthesis import DEFAULT_BPM, build_review, synthesize_satb  # noqa: E402

CRNN_CHECKPOINTS = {
    "seed1": Path("D:/PiyaNota/music_symbol_detection/finetuned_font_seed1.pt"),
    "seed2": Path("D:/PiyaNota/music_symbol_detection/finetuned_font_seed2.pt"),
}
DEFAULT_SEED = "seed1"
DEFAULT_YOLO = Path("D:/PiyaNota/staff_detector_files/weights/best.pt")
# Gitignored, so a fresh worktree has no copy at stage3_clefkey.DEFAULT_CLEF_KEY_CHECKPOINT.
TRAINING_TREE_CLEF_KEY = (Path("D:/PiyaNota-training") / "training" / "clef_key_artifacts"
                          / "t4_full_seed20260926_runA" / "clef_key_classifier.pt")
DEFAULT_SOUNDFONT = Path("D:/PiyaNota/soundfont/piano.sf2")
DATASET_MANIFEST = Path("D:/PiyaNota/data/piyanota_dataset/dataset_manifest.csv")
DEV_SPLIT = "dev"
IMG_HEIGHT = 64  # CRNN training height
STRIP_MANIFEST = stage3_clefkey.DEFAULT_PIPELINE_MANIFEST


def check_split(page: Path, allow_heldout: bool) -> str:
    """Returns the page's dataset split and refuses held-out pages unless explicitly allowed.

    Looking at output on a test/heldout page spends it: anything noticed can leak into later tuning.

    Raises:
        SystemExit: the page is in a non-dev split and allow_heldout is False.
    """
    if not DATASET_MANIFEST.is_file():
        print(f"[demo] WARNING: {DATASET_MANIFEST} not found; cannot check the page's split.")
        return "unknown"
    with DATASET_MANIFEST.open(encoding="utf-8", newline="") as fh:
        split = next((row["split"] for row in csv.DictReader(fh) if row["filename"] == page.name), None)
    if split is None:
        return "not in dataset manifest"
    if split != DEV_SPLIT and not allow_heldout:
        raise SystemExit(f"[demo] {page.name} is in the '{split}' split. Use a dev page or pass --allow-heldout.")
    return split


def resolve_clef_key(path: Path) -> Path:
    """Checks the ClefKeyNet checkpoint exists and is the pinned T4 seed-20260926 run A file.

    Raises:
        FileNotFoundError: the checkpoint is missing.
        ValueError: its sha256 is not the pinned one.
    """
    if not path.is_file():
        raise FileNotFoundError(f"ClefKeyNet checkpoint not found: {path}")
    digest = stage3_clefkey.file_sha256(path)
    if digest != stage3_clefkey.DEFAULT_CLEF_KEY_SHA256:
        raise ValueError(f"ClefKeyNet checkpoint {path} has sha256 {digest}, expected "
                         f"{stage3_clefkey.DEFAULT_CLEF_KEY_SHA256}")
    return path


def summarize_decisions(decisions: dict[str, stage3_clefkey.StripDecision]) -> list[str]:
    """One console line per system (key) and per strip (clef, octave, source, flags)."""
    lines: list[str] = []
    current_system = ""
    for strip_id in sorted(decisions):
        d = decisions[strip_id]
        page_part, system, voice = strip_id.split("_")[:3]   # page001_sys01_Soprano_vidx1
        if system != current_system:
            current_system = system
            kind = "sharps" if d.key > 0 else "flats" if d.key < 0 else "none"
            lines.append(f"  {page_part} {system}: key {d.key:+d} ({kind}), source {d.key_source}")
        flags = sorted(set(d.flags) | set(d.clef.flags))
        lines.append(f"    {voice:<8} clef {d.clef.clef_class:<5} octave_shift {d.clef.octave_shift:+d}  "
                     f"source {d.clef.source:<14} review_needed={d.review_needed}"
                     + (f"  flags: {', '.join(flags)}" if flags else ""))
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="PiyaNota one-page demo (Stages 1-5, CPU)")
    parser.add_argument("--page", type=Path, required=True, help="One score page image (photo or PDF render)")
    parser.add_argument("--out", type=Path, required=True, help="Output folder (new or empty)")
    parser.add_argument("--seed", choices=sorted(CRNN_CHECKPOINTS), default=DEFAULT_SEED)
    parser.add_argument("--yolo", type=Path, default=DEFAULT_YOLO)
    parser.add_argument("--clef-key", type=Path, default=TRAINING_TREE_CLEF_KEY)
    parser.add_argument("--soundfont", type=Path, default=DEFAULT_SOUNDFONT)
    parser.add_argument("--bpm", type=int, default=DEFAULT_BPM)
    parser.add_argument("--allow-heldout", action="store_true", help="Allow a test/heldout page (spends it)")
    args = parser.parse_args()

    t_start = time.time()
    page: Path = args.page.resolve()
    out: Path = args.out.resolve()
    if not page.is_file():
        raise FileNotFoundError(f"page not found: {page}")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"[demo] {out} is not empty; pick a new --out so old outputs can't mix in.")
    crnn = CRNN_CHECKPOINTS[args.seed]
    for label, path in (("CRNN", crnn), ("YOLO", args.yolo)):
        if not path.is_file():
            raise FileNotFoundError(f"{label} weights not found: {path}")
    clef_key = resolve_clef_key(args.clef_key)
    split = check_split(page, args.allow_heldout)

    dirs = {name: out / name for name in ("input", "preprocessed", "strips", "stage3_viz", "events",
                                          "reconstructed", "audio")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(page, dirs["input"] / page.name)
    timings: dict[str, float] = {}

    t = time.time()
    pages = preprocess_batch(str(dirs["input"]), str(dirs["preprocessed"]), save_debug=False, keep_unmasked=True)
    timings["stage1"] = time.time() - t

    t = time.time()
    manifest_path = dirs["strips"] / STRIP_MANIFEST
    voices = detect_staff_regions(pages, model_weights=str(args.yolo), output_dir=str(dirs["strips"]),
                                  save_viz=True, viz_dir=str(out / "detection_viz"),
                                  manifest_path=str(manifest_path))
    timings["stage2"] = time.time() - t

    t = time.time()
    ckm = stage3_clefkey.load_clef_key_model(clef_key)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with torch.no_grad():
        decisions, _ = stage3_clefkey.decisions_for_pages(pages, manifest, ckm)
    timings["clefkeynet"] = time.time() - t

    t = time.time()
    voice_events = transcribe_voice_sequences(voices, model_weights=str(crnn), img_height=IMG_HEIGHT,
                                              viz_dir=str(dirs["stage3_viz"]), events_dir=str(dirs["events"]),
                                              clef_key_decisions=decisions)
    timings["stage3"] = time.time() - t

    # Pitches pass through Stage 4/5 unchanged: Tenor's octave was applied once in Stage 3 by the
    # decision's octave_shift (the voice-based Tenor lowering is off under the header override).
    t = time.time()
    stage4_error = None
    satb: dict[str, list[dict[str, Any]]] = {}
    try:
        satb, recon = reconstruct_satb_with_report(voice_events)
    except ValueError as exc:  # an empty voice: Stage 5 can't build four tracks
        stage4_error = str(exc)
        recon = {"flags": []}
    timings["stage4"] = time.time() - t
    if satb:
        for voice, events in satb.items():
            (dirs["reconstructed"] / f"{voice.lower()}_events.json").write_text(
                json.dumps(events, indent=2), encoding="utf-8")
        (dirs["reconstructed"] / "stage4_report.json").write_text(
            json.dumps(recon, indent=2, default=str), encoding="utf-8")
    review, review_detail = build_review(voice_events, recon["flags"])
    (out / "review.json").write_text(json.dumps({"review": review, "items": review_detail}, indent=2),
                                     encoding="utf-8")

    t = time.time()
    audio: dict[str, str] = {}
    if satb:
        audio = synthesize_satb(satb, output_dir=str(dirs["audio"]), bpm=args.bpm,
                                soundfont_path=str(args.soundfont))
    timings["stage5"] = time.time() - t
    total = time.time() - t_start

    print("\n" + "=" * 72)
    print(f"PiyaNota one-page demo  |  page {page.name} (split: {split})  |  CRNN {args.seed}  |  CPU")
    print("=" * 72)
    print("Strips per voice: " + ", ".join(f"{v} {len(voices.get(v, []))}" for v in VOICES))
    print("ClefKeyNet decisions (clef/key/octave replace the CRNN's own header):")
    print("\n".join(summarize_decisions(decisions)))
    n_review = sum(d.review_needed for d in decisions.values())
    print(f"Strips flagged review_needed by their own decision: {n_review}/{len(decisions)}")
    print(f"Job review: reviewNeeded={review['reviewNeeded']}  reasons={review['reasons']}")
    print("Notes per voice (Stage 3): " + ", ".join(
        f"{v} {sum(e['type'] == 'note' for e in voice_events.get(v, []))}" for v in VOICES))
    if stage4_error:
        print(f"STAGE 4 FAILED: {stage4_error}  (no audio produced)")
    print("Audio:")
    for voice in VOICES:
        print(f"  {voice:<8} {audio.get(voice, 'NOT PRODUCED')}")
    if any(p.endswith(".mid") for p in audio.values()):
        print("  NOTE: .mid fallback -- MP3 needs fluidsynth + ffmpeg on PATH, pydub, and the soundfont.")
    print("Outputs:")
    for name, d in dirs.items():
        print(f"  {name:<14} {d}")
    print(f"  {'review':<14} {out / 'review.json'}")
    print("Timings (s): " + ", ".join(f"{k} {v:.1f}" for k, v in timings.items()) + f", total {total:.1f}")
    print("=" * 72)


if __name__ == "__main__":
    main()
