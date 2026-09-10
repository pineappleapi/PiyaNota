"""
PiyaNota — OMR baseline comparison.

Benchmarks this project's own Stage 3 CRNN-CTC transcriber
(`stage3_transcription.load_model` / `transcribe_strip`) against open-source
OMR baselines on Symbol Error Rate (SER), using the Camera-PrIMuS dataset
(`datasets/CameraPriMus/`).

Why two different token vocabularies are used
-----------------------------------------------
Our own system is scored against the dataset's `.agnostic` ground truth using
the exact vocabulary it was trained to emit (Camera-PrIMuS agnostic tokens,
e.g. `note.quarter-L4`) — this is a like-for-like comparison.

oemer (github.com/BreezeWhite/oemer) has no notion of that agnostic
vocabulary — it is a full end-to-end system whose only output is MusicXML.
There is no principled way to convert MusicXML back into staff-position
agnostic tokens (that information — which line/space a symbol sits on — is
simply not preserved once oemer has resolved it into a key/clef-independent
pitch). So oemer is instead scored against the dataset's `.semantic` ground
truth (pitch+duration tokens, e.g. `note-Bb5_eighth`), with its MusicXML
output converted into the same shape via music21. This makes the *absolute*
SER numbers for "ours" and "oemer" not directly comparable to the third
decimal place (different vocabularies, different token granularities) — but
it is the fairest apples-to-oranges comparison achievable without hand
grading, and both numbers still answer the practical question: how close is
each system's raw output to ground truth. This caveat is restated in the
printed summary so it isn't lost.

Usage
-----
    python compare_omr_baselines.py
    python compare_omr_baselines.py --ours-sample-size 300 --oemer-sample-size 15
    python compare_omr_baselines.py --skip-oemer   # ours-only run
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import torch

from stage3_transcription import compute_ser, load_model, transcribe_strip

# -- Constants ----------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DATASET_ROOT = (
    PROJECT_ROOT / "datasets" / "CameraPriMus" / "CameraPrIMuS - Copy" / "Corpus"
)
DEFAULT_WEIGHTS = (
    PROJECT_ROOT / "music_symbol_detection" / "crnn_cameraprimus_transcription.pt"
)

RANDOM_SEED = 42                 # fixed seed -> same sample set on every run
DEFAULT_OURS_SAMPLE_SIZE = 200    # CRNN inference is cheap; a large sample is affordable
# oemer's full U-Net segmentation pipeline (two models, CPU-only on this box --
# see OEMER_TIMEOUT_S) took ~8 minutes wall-clock for a single tiny
# Camera-PrIMuS incipit in a manual pre-check, so both the sample size and
# the variant set below are kept deliberately small to bound total runtime.
DEFAULT_OEMER_SAMPLE_SIZE = 2
DEFAULT_OEMER_VARIANTS = ("clean",)  # see main(): distorted is skipped by default
OEMER_TIMEOUT_S = 600             # >= observed ~8 min single-image runtime, plus margin
IMG_HEIGHT = 64                   # must match Stage 3 training height

# music21 duration-type spellings -> Camera-PrIMuS `.semantic` spellings
DURATION_TYPE_TO_SEMANTIC = {
    "whole": "whole",
    "half": "half",
    "quarter": "quarter",
    "eighth": "eighth",
    "16th": "sixteenth",
    "32nd": "thirty_second",
    "64th": "sixty_fourth",
    "128th": "hundred_twenty_eighth",
    "breve": "double_whole",
}


# -- Sample discovery ---------------------------------------------------------

@dataclass(frozen=True)
class Sample:
    """Paths to one Camera-PrIMuS incipit's ground truth and image variants."""
    stem: str
    agnostic_path: Path
    semantic_path: Path
    clean_png: Path
    distorted_jpg: Path


def discover_samples(dataset_root: Path) -> List[Sample]:
    """Finds every Corpus subfolder with a complete set of required files.

    Args:
        dataset_root: Path to the extracted Camera-PrIMuS `Corpus/` directory.

    Returns:
        Samples sorted by stem name, for a deterministic ordering that
        `random.Random(seed).sample()` can draw from reproducibly.
    """
    samples: List[Sample] = []
    for entry in sorted(dataset_root.iterdir()):
        if not entry.is_dir():
            continue
        stem = entry.name
        agnostic = entry / f"{stem}.agnostic"
        semantic = entry / f"{stem}.semantic"
        clean = entry / f"{stem}.png"
        distorted = entry / f"{stem}_distorted.jpg"
        if agnostic.exists() and semantic.exists() and clean.exists() and distorted.exists():
            samples.append(Sample(stem, agnostic, semantic, clean, distorted))
    return samples


def load_tab_separated(path: Path) -> List[str]:
    """Reads a `.agnostic` or `.semantic` ground-truth file into a token list."""
    text = path.read_text(encoding="utf-8").strip()
    return text.split("\t") if text else []


# -- "Ours" evaluation (Stage 3 CRNN-CTC vs .agnostic ground truth) -----------

@dataclass
class VariantResult:
    """Aggregated + per-sample SER for one system on one image variant."""
    system: str
    variant: str
    n_samples: int
    n_failed: int
    per_sample_ser: List[float] = field(default_factory=list)
    total_edits: int = 0
    total_gt_tokens: int = 0

    @property
    def mean_ser(self) -> float:
        return sum(self.per_sample_ser) / len(self.per_sample_ser) if self.per_sample_ser else float("nan")

    @property
    def aggregate_ser(self) -> float:
        """Corpus-level SER: total edit operations / total ground-truth tokens."""
        return self.total_edits / self.total_gt_tokens if self.total_gt_tokens else float("nan")


def evaluate_ours(
    samples: List[Sample],
    weights_path: Path,
    variant: str,
    device: Optional[torch.device] = None,
) -> VariantResult:
    """Runs Stage 3's CRNN-CTC transcriber on each sample and scores SER.

    Args:
        samples: Samples to evaluate.
        weights_path: CRNN checkpoint (music_symbol_detection/*.pt).
        variant: "clean" (.png) or "distorted" (_distorted.jpg).
        device: Torch device to run on. Defaults to CPU -- this comparison
          runs oemer (a separate process that may also claim the GPU) around
          the same time, and a cuDNN LSTM call was observed to fail with
          CUDNN_STATUS_EXECUTION_FAILED under that contention on this
          4GB-VRAM GTX 1650 dev box; CPU is slower but small and reliable
          for a strip-sized CRNN forward pass.

    Returns:
        Aggregated result for this variant.
    """
    model, device = load_model(str(weights_path), device=device or torch.device("cpu"))
    result = VariantResult(system="PiyaNota Stage 3 (CRNN-CTC)", variant=variant,
                            n_samples=len(samples), n_failed=0)

    for sample in samples:
        image_path = sample.clean_png if variant == "clean" else sample.distorted_jpg
        image = cv2.imread(str(image_path))
        if image is None:
            result.n_failed += 1
            continue
        ground_truth = load_tab_separated(sample.agnostic_path)
        predicted = transcribe_strip(image, model, device, img_height=IMG_HEIGHT)

        ser = compute_ser(predicted, ground_truth)
        result.per_sample_ser.append(ser)
        result.total_edits += round(ser * len(ground_truth))
        result.total_gt_tokens += len(ground_truth)

    return result


# -- oemer baseline (subprocess isolation, MusicXML -> semantic tokens) -------

def _run_oemer(image_path: Path, output_dir: Path, timeout_s: int) -> Tuple[Optional[Path], str]:
    """Runs oemer's `ete.main()` end-to-end pipeline in an isolated subprocess.

    A subprocess (rather than an in-process import) is used so that a crash,
    hang, or native-library fault in oemer/onnxruntime cannot take down this
    comparison script, and so a per-image timeout can be enforced.

    Args:
        image_path: Score image to transcribe.
        output_dir: Directory oemer will write `<stem>.musicxml` into.
        timeout_s: Wall-clock cap; a TimeoutExpired is treated as a failure.

    Returns:
        (path_to_musicxml_or_None, diagnostic_text). diagnostic_text carries
        stderr (or the timeout message) for honest failure reporting.
    """
    script = (
        "import sys; from oemer.ete import main; "
        f"sys.argv = ['oemer', {str(image_path)!r}, '-o', {str(output_dir)!r}]; "
        "main()"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {timeout_s}s"

    musicxml_path = output_dir / f"{image_path.stem}.musicxml"
    if proc.returncode != 0 or not musicxml_path.exists():
        tail = proc.stderr.strip().splitlines()
        diagnostic = "\n".join(tail[-15:]) if tail else f"exit code {proc.returncode}, no stderr"
        return None, diagnostic
    return musicxml_path, ""


def _pitch_to_semantic(pitch) -> str:
    """Converts a music21 Pitch to Camera-PrIMuS semantic spelling: 'B-5' -> 'Bb5'."""
    return f"{pitch.name.replace('-', 'b')}{pitch.octave}"


def musicxml_to_semantic_tokens(musicxml_path: Path) -> List[str]:
    """Flattens a MusicXML file's notes/rests into `.semantic`-shaped tokens.

    Only notes and rests are extracted (clef/key/time-signature/barline are
    dropped) because oemer's MusicXML and the corpus's `.semantic` ground
    truth encode those header elements too differently to align token-for-
    token; notes/rests are where both representations agree in granularity.
    """
    import music21  # deferred: heavy import, only needed for this baseline

    score = music21.converter.parse(str(musicxml_path))
    tokens: List[str] = []
    for element in score.flatten().notesAndRests:
        dur_type = DURATION_TYPE_TO_SEMANTIC.get(element.duration.type, element.duration.type)
        dots = "." * element.duration.dots
        if element.isRest:
            tokens.append(f"rest-{dur_type}{dots}")
        elif element.isChord:
            for p in element.pitches:
                tokens.append(f"note-{_pitch_to_semantic(p)}_{dur_type}{dots}")
        else:
            tokens.append(f"note-{_pitch_to_semantic(element.pitch)}_{dur_type}{dots}")
    return tokens


def semantic_notes_and_rests(path: Path) -> List[str]:
    """Reference tokens for the oemer comparison: `.semantic` file, notes/rests only."""
    tokens = load_tab_separated(path)
    return [t for t in tokens if t.startswith("note-") or t.startswith("rest-")]


def evaluate_oemer(
    samples: List[Sample],
    variant: str,
    scratch_dir: Path,
) -> Tuple[Optional[VariantResult], List[str]]:
    """Runs the oemer baseline on each sample and scores SER against `.semantic`.

    Returns:
        (result_or_None, failure_diagnostics). result is None if every
        sample failed (nothing to aggregate); failure_diagnostics always
        lists what went wrong, for honest reporting even on partial success.
    """
    scratch_dir.mkdir(parents=True, exist_ok=True)
    result = VariantResult(system="oemer", variant=variant, n_samples=len(samples), n_failed=0)
    diagnostics: List[str] = []

    for sample in samples:
        image_path = sample.clean_png if variant == "clean" else sample.distorted_jpg
        musicxml_path, diag = _run_oemer(image_path, scratch_dir, OEMER_TIMEOUT_S)
        if musicxml_path is None:
            result.n_failed += 1
            diagnostics.append(f"{sample.stem} ({variant}): {diag}")
            continue
        try:
            predicted = musicxml_to_semantic_tokens(musicxml_path)
        except Exception as exc:  # music21 parse failures vary widely; report, don't crash the run
            result.n_failed += 1
            diagnostics.append(f"{sample.stem} ({variant}): MusicXML parse failed: {exc}")
            continue

        ground_truth = semantic_notes_and_rests(sample.semantic_path)
        ser = compute_ser(predicted, ground_truth)
        result.per_sample_ser.append(ser)
        result.total_edits += round(ser * len(ground_truth))
        result.total_gt_tokens += len(ground_truth)

    if not result.per_sample_ser:
        return None, diagnostics
    return result, diagnostics


# -- Reporting -----------------------------------------------------------------

def print_summary_table(results: List[VariantResult]) -> None:
    header = f"{'System':<28} {'Variant':<12} {'N':>5} {'Failed':>7} {'Mean SER':>10} {'Aggregate SER':>14}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r.system:<28} {r.variant:<12} {r.n_samples:>5} {r.n_failed:>7} "
              f"{r.mean_ser*100:>9.2f}% {r.aggregate_ser*100:>13.2f}%")


# -- CLI -----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--ours-sample-size", type=int, default=DEFAULT_OURS_SAMPLE_SIZE)
    parser.add_argument("--oemer-sample-size", type=int, default=DEFAULT_OEMER_SAMPLE_SIZE)
    parser.add_argument("--oemer-variants", nargs="+", default=list(DEFAULT_OEMER_VARIANTS),
                         choices=["clean", "distorted"],
                         help="oemer's pipeline is very slow (see module constants); "
                              "defaults to clean-only to bound total runtime.")
    parser.add_argument("--skip-oemer", action="store_true")
    parser.add_argument("--scratch-dir", type=Path,
                         default=Path(r"C:\Users\paul_\AppData\Local\Temp\claude_omr_compare"))
    args = parser.parse_args()

    if not args.dataset_root.exists():
        raise FileNotFoundError(
            f"Dataset not found at {args.dataset_root} -- extract "
            "datasets/CameraPrIMuS.zip into datasets/CameraPriMus first."
        )

    all_samples = discover_samples(args.dataset_root)
    print(f"[compare] Found {len(all_samples)} complete Camera-PrIMuS samples "
          f"under {args.dataset_root}")

    rng = random.Random(RANDOM_SEED)
    ours_samples = rng.sample(all_samples, min(args.ours_sample_size, len(all_samples)))
    print(f"[compare] Evaluating our system on {len(ours_samples)} samples "
          f"(seed={RANDOM_SEED})")

    results: List[VariantResult] = []
    t0 = time.time()
    for variant in ("clean", "distorted"):
        r = evaluate_ours(ours_samples, args.weights, variant)
        results.append(r)
        print(f"[compare] ours/{variant}: mean SER {r.mean_ser*100:.2f}%  "
              f"aggregate SER {r.aggregate_ser*100:.2f}%  "
              f"({r.n_samples - r.n_failed}/{r.n_samples} scored, "
              f"{time.time()-t0:.1f}s elapsed)")

    if args.skip_oemer:
        print("\n[compare] --skip-oemer set; not attempting the oemer baseline.")
    else:
        # oemer is a full segmentation pipeline; a much smaller, deterministic
        # subset of the *same* sample pool keeps total runtime bounded.
        oemer_rng = random.Random(RANDOM_SEED)
        oemer_samples = oemer_rng.sample(ours_samples, min(args.oemer_sample_size, len(ours_samples)))
        print(f"\n[compare] Attempting oemer baseline on {len(oemer_samples)} samples "
              f"(subset of the ours-sample pool, same seed)")

        all_diagnostics: List[str] = []
        for variant in args.oemer_variants:
            t1 = time.time()
            r, diagnostics = evaluate_oemer(oemer_samples, variant,
                                             args.scratch_dir / variant)
            all_diagnostics.extend(diagnostics)
            elapsed = time.time() - t1
            if r is None:
                print(f"[compare] oemer/{variant}: ALL {len(oemer_samples)} samples failed "
                      f"({elapsed:.1f}s elapsed)")
            else:
                results.append(r)
                print(f"[compare] oemer/{variant}: mean SER {r.mean_ser*100:.2f}%  "
                      f"aggregate SER {r.aggregate_ser*100:.2f}%  "
                      f"({r.n_samples - r.n_failed}/{r.n_samples} scored, "
                      f"{elapsed:.1f}s elapsed)")

        if all_diagnostics:
            print("\n[compare] oemer failure diagnostics (first 10):")
            for line in all_diagnostics[:10]:
                print(f"  - {line}")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print_summary_table(results)
    print(
        "\nNote: 'ours' is scored against Camera-PrIMuS .agnostic ground truth "
        "(the exact vocabulary Stage 3 was trained on). oemer has no notion of "
        "that vocabulary -- it only emits MusicXML -- so it is scored against "
        "the .semantic ground truth (pitch+duration tokens) with its MusicXML "
        "output converted to the same shape via music21. The two SER columns "
        "are therefore each internally consistent but not decimal-for-decimal "
        "comparable across systems -- see the module docstring for why."
    )


if __name__ == "__main__":
    main()
