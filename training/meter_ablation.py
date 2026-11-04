"""DEV-DATA DIAGNOSTIC ONLY, NOT AN ACCURACY RESULT: APPLY_MID_METER_CHANGE off versus on (Task 3, 2026-11-04 plan).

Data: dev pieces only. Gaano, Handog, Don't Stop Me Now (eval_prelim / eval_fresh camera pages), the Both Sides
Now photos (data/raw/Raw) and Moonriver p01-p04 (in-sample for this change: a mechanism check, not recall). The
Non Nobis Domine and Honneur a Toi photos in data/piyanota_dataset are TEST-only (data/eval_fresh/PREREG.md): this
script never opens them and nothing here was tuned on them. Nothing is tuned at all: the quorum, the inference
rule and the duration check were fixed before the first run, and the script only observes.

Method: Stage 1 + 2 once per page and ClefKeyNet once per piece; per CRNN seed every strip is decoded once (a
memo around ``transcribe_strip``) and ``transcribe_voice_sequences`` runs twice on the same tokens, flag off then
on, each followed by Stage 4. The only variable is the flag. CPU only.

Usage (pipeline venv, repo root):  CUDA_VISIBLE_DEVICES=-1 python training/meter_ablation.py [--pieces moonriver]
Output: data/eval_meter_ablation/results.json (gitignored).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # empty string crashes ultralytics

import cv2  # noqa: E402
import torch  # noqa: E402

torch.cuda.is_available = lambda: False  # stage modules pick their device from this
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import stage1_preprocessing as s1  # noqa: E402
import stage3_clefkey as s3b  # noqa: E402
import stage3_transcription as s3  # noqa: E402
import stage4_reconstruction as s4  # noqa: E402
from stage2_detection import detect_staff_regions  # noqa: E402

MAIN = Path("D:/PiyaNota")  # model files and photos are not in the worktree
OUT = ROOT / "data" / "eval_meter_ablation"
YOLO = MAIN / "staff_detector_files/weights/best.pt"
CLEF_KEY = MAIN / "training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt"
CRNNS = {"seed1": MAIN / "music_symbol_detection/phase2_kaggle_models/seed1/phase2_seed1.pt",
         "seed2": MAIN / "music_symbol_detection/phase2_kaggle_models/seed2/phase2_seed2.pt"}
DEV_PHOTOS = MAIN / "data/piyanota_dataset"
TEST_ONLY = ("non_nobis_domine", "honneur_a_toi")  # PREREG.md: never opened here
PIECES: dict[str, list[Path]] = {
    "gaano_ko_ikaw_kamahal": [DEV_PHOTOS / f"gaano_ko_ikaw_kamahal_pg{p:02d}.jpg" for p in range(1, 10)],
    "handog": [DEV_PHOTOS / f"handog_pg{p:02d}.jpg" for p in range(1, 15)],
    "dont_stop_me_now": [DEV_PHOTOS / f"dont_stop_me_now_pg{p:02d}.jpg" for p in range(1, 6)],
    "both_sides_now": [MAIN / "data/raw/Raw" / f"IMG_{n}.JPG" for n in (1081, 1082, 1083, 1084, 1086, 1087, 1088)],
    "moonriver": [MAIN / "data/chords_dataset/Moonriver/Moonriver" / f"p{p:02d}.JPG" for p in range(1, 5)],
}
MOONRIVER_MXL = MAIN / "data/eval_moonriver_diag/Moonriver.mxl"
MOONRIVER_REF_TICKS = 58_560
IMG_HEIGHT = 64
SOURCE_FIELD = "time_signature_source"
METER_FLAGS = (s4.FLAG_METER_INFERRED, s4.FLAG_METER_NOT_INFERRED, s4.FLAG_METER_DURATION_MISMATCH)
BAR_FLAGS = (s4.FLAG_BAR_UNDERFULL, s4.FLAG_BAR_OVERFLOW, "bar_overflow_clipped", "suspected_missing_barline")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _baked(photo: Path, work: Path) -> Path:
    """EXIF orientation baked in, as the app uploads it (raw orientation-6 JPEGs otherwise fail Stage 2)."""
    from PIL import Image, ImageOps

    out = work / f"baked_{photo.stem}.jpg"
    if not out.exists():
        ImageOps.exif_transpose(Image.open(photo)).convert("RGB").save(out, "JPEG", quality=95)
    return out


def stage12(piece: str, ckm: s3b.ClefKeyModel) -> tuple[dict[str, list[tuple[Any, ...]]], dict[str, Any],
                                                       list[dict[str, Any]]]:
    """Stage 1 + 2 page by page (a failing page is skipped and recorded) and ClefKeyNet decisions."""
    if piece in TEST_ONLY:
        raise ValueError(f"{piece} is TEST-only (PREREG.md)")
    work = OUT / piece
    work.mkdir(parents=True, exist_ok=True)
    voices: dict[str, list[tuple[Any, ...]]] = {v: [] for v in s4.VOICES}
    readings: list[s3b.ClefKeyReading] = []
    pages: list[dict[str, Any]] = []
    for p, photo in enumerate(PIECES[piece], start=1):
        diag: dict[str, Any] = {"page": p, "photo": photo.name}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                page = s1.preprocess_score_page(str(_baked(photo, work)), keep_unmasked=True)
                manifest_path = work / f"page{p:02d}_manifest.json"
                vs = detect_staff_regions([(page.detect, p, page.strip_source)], model_weights=str(YOLO),
                                          output_dir=str(work / "strips"), save_strips=False, save_viz=False,
                                          manifest_path=str(manifest_path))
        except (ValueError, RuntimeError, cv2.error) as exc:
            diag["failure"] = f"{type(exc).__name__}: {exc}"
            pages.append(diag)
            print(f"[ablation] {piece} p{p}: page skipped, {diag['failure']}")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        diag["n_strips"] = len(manifest)
        for voice, items in vs.items():
            voices.setdefault(voice, []).extend(items)
        with torch.no_grad():
            readings += s3b.classify_page(page, manifest, ckm)
        pages.append(diag)
    return voices, s3b.decide(readings, ckm), pages


def _memo_decoder(real: Callable[..., Any]) -> tuple[Callable[..., Any], dict[str, Any]]:
    """transcribe_strip, decoded once per strip_id: the off and on runs read the very same tokens."""
    cache: dict[str, Any] = {}

    def decode(strip: Any, *args: Any, strip_id: str, spans_out: Any = None, **kw: Any) -> Any:
        if strip_id not in cache:
            spans: list[Any] = []
            cache[strip_id] = (real(strip, *args, strip_id=strip_id, spans_out=spans, **kw), spans)
        scored, spans = cache[strip_id]
        if spans_out is not None:
            spans_out.extend(spans)
        return copy.deepcopy(scored)

    return decode, cache


def _run(voices: dict[str, list[tuple[Any, ...]]], decisions: dict[str, Any], crnn: Path,
         apply: bool) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    s3.APPLY_MID_METER_CHANGE = apply
    with contextlib.redirect_stdout(io.StringIO()):
        events = s3.transcribe_voice_sequences(voices, model_weights=str(crnn), img_height=IMG_HEIGHT, viz_dir="",
                                               events_dir="", clef_key_decisions=decisions)
        satb, report = s4.reconstruct_satb_with_report(copy.deepcopy(events))
    return events, satb, report


def _strip_source(events: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {v: [{k: x for k, x in e.items() if k != SOURCE_FIELD} for e in es] for v, es in events.items()}


def _bar_list(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for s in report["systems"] for b in s.get("bars", [])]


def _moonriver_ref() -> dict[int, int]:
    """Printed bar -> length in ticks, from the .mscz export (scorer only; never fed to the apply path)."""
    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    from moonriver_diag_eval import reference  # needs music21 (pipeline venv)

    _, bars = reference(MOONRIVER_MXL)
    return {n: length for n, (_, length) in bars.items()}


def compare(piece: str, off: tuple[Any, ...], on: tuple[Any, ...], ref: dict[int, int] | None) -> dict[str, Any]:
    ev_off, satb_off, rep_off = off
    ev_on, satb_on, rep_on = on
    kinds_off, kinds_on = Counter(f["kind"] for f in rep_off["flags"]), Counter(f["kind"] for f in rep_on["flags"])
    bars_off, bars_on = _bar_list(rep_off), _bar_list(rep_on)
    out: dict[str, Any] = {
        "stage3_events_identical": json.dumps(_strip_source(ev_off), sort_keys=True)
        == json.dumps(_strip_source(ev_on), sort_keys=True),
        "stage4_events_identical": json.dumps(_strip_source(satb_off), sort_keys=True, default=str)
        == json.dumps(_strip_source(satb_on), sort_keys=True, default=str),
        "total_ticks": {"off": rep_off["total_ticks"], "on": rep_on["total_ticks"]},
        "n_bars": {"off": len(bars_off), "on": len(bars_on)},
        "bars_with_changed_length": sum(a["ticks"] != b["ticks"] for a, b in zip(bars_off, bars_on)),
        "bar_flags": {k: {"off": kinds_off[k], "on": kinds_on[k]} for k in BAR_FLAGS},
        "meter_flags_on": {k: kinds_on[k] for k in METER_FLAGS},
        "duration_mismatch_bars": [f["bar"] for f in rep_on["flags"] if f["kind"] == s4.FLAG_METER_DURATION_MISMATCH],
        "meters_on": dict(Counter(f"{b['time_signature']}/{b['meter_source']}" for b in bars_on)),
        "flag_kind_diff": {k: kinds_on[k] - kinds_off[k] for k in set(kinds_on) | set(kinds_off)
                           if kinds_on[k] != kinds_off[k]},
    }
    if ref is not None:
        def wrong(bars: list[dict[str, Any]], first: int) -> int:
            return sum(1 for i, b in enumerate(bars) if ref.get(first + i) not in (None, b["ticks"]))
        first_off = rep_off["systems"][0]["first_bar"] if rep_off["systems"] else 1
        first_on = rep_on["systems"][0]["first_bar"] if rep_on["systems"] else 1
        # Bar lengths in place; a missed barline shifts every later bar, so this is a rough count.
        out["reference"] = {"total_ticks": MOONRIVER_REF_TICKS, "ref_bars": len(ref),
                            "wrong_length_bars": {"off": wrong(bars_off, first_off), "on": wrong(bars_on, first_on)}}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pieces", nargs="*", default=list(PIECES))
    ap.add_argument("--seeds", nargs="*", default=list(CRNNS))
    args = ap.parse_args()
    if set(args.pieces) & set(TEST_ONLY):
        raise SystemExit(f"TEST-only pieces are never used here: {TEST_ONLY}")
    OUT.mkdir(parents=True, exist_ok=True)
    ckm = s3b.load_clef_key_model(CLEF_KEY)
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    meta = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "git_head": git.stdout.strip(),
            "stage_hashes": {f: sha256(ROOT / f) for f in ("stage3_transcription.py", "stage4_reconstruction.py")},
            "crnn": {k: sha256(v) for k, v in CRNNS.items() if k in args.seeds}, "clef_key": sha256(CLEF_KEY),
            "rules": {"stage3_meter_quorum": f"min({s3.HEADER_QUORUM}, readable voices), floor {s3.MIN_METER_QUORUM}",
                      "stage4_meter_quorum": s4.METER_QUORUM, "inferable": sorted(s4.INFERABLE_METERS.values()),
                      "inference_min_bars": s4.METER_INFERENCE_MIN_BARS}}
    results: dict[str, Any] = {"meta": meta, "pieces": {}}
    real_decode = s3.transcribe_strip
    for piece in args.pieces:
        voices, decisions, pages = stage12(piece, ckm)
        ref = _moonriver_ref() if piece == "moonriver" else None
        entry: dict[str, Any] = {"pages": pages}
        for seed in args.seeds:
            decode, _ = _memo_decoder(real_decode)
            s3.transcribe_strip = decode
            try:
                off = _run(voices, decisions, CRNNS[seed], False)
                on = _run(voices, decisions, CRNNS[seed], True)
            finally:
                s3.transcribe_strip = real_decode
                s3.APPLY_MID_METER_CHANGE = True
            entry[seed] = compare(piece, off, on, ref)
            print(f"[ablation] {piece} {seed}: {json.dumps(entry[seed])}", flush=True)
        results["pieces"][piece] = entry
        (OUT / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"[ablation] wrote {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
