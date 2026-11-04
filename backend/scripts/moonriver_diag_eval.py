"""DEV-DATA DIAGNOSTIC ONLY, NOT AN ACCURACY RESULT: score the app's conversion output on Moonriver.

Moonriver is dev data (used for tuning). The numbers say where the pipeline fails; they are not evidence of
real-world accuracy. Run under the pipeline venv (it has torch and music21; the backend venv has neither):

    CUDA_VISIBLE_DEVICES=-1 D:/PiyaNota/.venv/Scripts/python.exe backend/scripts/moonriver_diag_eval.py [--reuse]

It runs the worker's real adapter (``backend.worker.pipeline.run_pipeline`` with ``PipelineConfig.from_env``
defaults: phase2_seed1 CRNN, ClefKeyNet on, Stage 4 tie fix, Stage 5) on the Moonriver p01-p04 photos baked the way
the app bakes them, then scores the reconstructed events (the ones that become the MIDI/MP3s) against the .mscz.
Reuses ``_lev``, ``_collapse`` and ``score_events`` from the read-only Stage 4 dev harness for edit distance and SER.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_CHECKOUT = Path("D:/PiyaNota")  # model files are not in the worktree
HARNESS_TOOLS = MAIN_CHECKOUT / ".claude/worktrees/piya106-stage4-fixes/tools"
PHOTO_DIR = MAIN_CHECKOUT / "data/chords_dataset/Moonriver/Moonriver"
MSCZ = MAIN_CHECKOUT / "data/chords_dataset/Moonriver/Moonriver.mscz"
MUSESCORE = "C:/Program Files/MuseScore 4/bin/MuseScore4.exe"
DEFAULT_OUT = MAIN_CHECKOUT / "data/eval_moonriver_diag"
PHOTOS = ("p01.JPG", "p02.JPG", "p03.JPG", "p04.JPG")
PAGE_RANGES = {1: (1, 12), 2: (13, 24), 3: (25, 36), 4: (37, 40)}  # printed measures per page (dev manifest)
PARTS = {"Soprano": "Soprano", "Alto": "Alto", "Tenor": "Tenor", "Bass": "Bass 1"}  # Bass 2 differs only in bar 40
BASS_DIVISI_BAR = 40
TEMPO_BPM = 90
PPQ = 480
BAR_SPAN = 100_000  # keeps bar-relative onsets of different bars apart
TOL = PPQ // 4 # one 16th, strict F1 tolerance on onset and duration
MODEL_ENV = {
    "PIYA_YOLO_WEIGHTS": MAIN_CHECKOUT / "staff_detector_files/weights/best.pt",
    "PIYA_CRNN_WEIGHTS": MAIN_CHECKOUT / "music_symbol_detection/phase2_kaggle_models/seed1/phase2_seed1.pt",
    "PIYA_CLEFKEY_WEIGHTS": MAIN_CHECKOUT / "training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt",
    "PIYA_SOUNDFONT": MAIN_CHECKOUT / "soundfont/piano.sf2",
}
Note = dict[str, Any]  # pitch, onset (rebased global ticks), dur, bar


def export_mxl(out: Path) -> Path:
    """Export the .mscz to MusicXML with MuseScore (the reference); skipped when already there."""
    mxl = out / "Moonriver.mxl"
    if not mxl.exists():
        subprocess.run([MUSESCORE, "-o", str(mxl), str(MSCZ)], check=True, timeout=170)
    return mxl


def reference(mxl: Path) -> tuple[dict[str, list[Note]], dict[int, tuple[int, int]]]:
    """Per voice: notes and rests with global onset, ties merged; plus bar -> (start, length) ticks.

    No repeats or pickup in this score, so the printed order is the played order.
    """
    import music21 as m

    score = m.converter.parse(str(mxl))
    out: dict[str, list[Note]] = {}
    bars: dict[int, tuple[int, int]] = {}
    for voice, part_name in PARTS.items():
        part = next(p for p in score.parts if p.partName == part_name)
        events: list[Note] = []
        for meas in part.getElementsByClass("Measure"):
            bars[meas.number] = (round(meas.offset * PPQ), round(meas.duration.quarterLength * PPQ))
            for n in meas.flatten().notesAndRests:
                dur = round(n.quarterLength * PPQ)
                if dur == 0:  # grace note
                    continue
                pitch = None if n.isRest else n.pitches[0].midi
                onset = round((meas.offset + n.offset) * PPQ)
                if (pitch is not None and n.tie is not None and n.tie.type in ("continue", "stop")
                        and events and events[-1]["pitch"] == pitch):
                    events[-1]["dur"] += dur
                    events[-1]["tied"] = True
                    continue
                events.append({"pitch": pitch, "onset": onset, "dur": dur, "bar": meas.number})
        out[voice] = events
    return out, bars


def divisi_report(mxl: Path) -> dict[str, Any]:
    """Count chords, multi-layer measures and Bass 1 vs Bass 2 differences in the reference."""
    import music21 as m

    score = m.converter.parse(str(mxl))
    chords = sum(1 for p in score.parts for n in p.recurse().notes if n.isChord)
    layered = sum(1 for p in score.parts for x in p.getElementsByClass("Measure") if len(x.voices) > 1)
    parts = {p.partName: list(p.getElementsByClass("Measure")) for p in score.parts}

    def sig(meas: Any) -> list[Any]:
        return [(None if n.isRest else n.pitches[0].midi, n.quarterLength) for n in meas.flatten().notesAndRests]

    differing = [a.number for a, b in zip(parts["Bass 1"], parts["Bass 2"]) if sig(a) != sig(b)]
    return {"parts": list(parts), "measures": len(parts["Soprano"]), "chords": chords, "layered_measures": layered,
            "bass1_vs_bass2_differing_bars": differing,
            "bass_bar40": {k: sig(parts[k][BASS_DIVISI_BAR - 1]) for k in ("Bass 1", "Bass 2")}}


def _app_like_jpeg(path: Path) -> bytes:
    """Bake EXIF orientation and strip EXIF as the Flutter app does (same as smoke_convert)."""
    from PIL import Image, ImageOps

    buf = io.BytesIO()
    ImageOps.exif_transpose(Image.open(path)).convert("RGB").save(buf, "JPEG", quality=95)
    return buf.getvalue()


def run_app_pipeline(out: Path) -> dict[str, Any]:
    """Run the worker's real run_pipeline with defaults on CPU; keep events, report and flags."""
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # empty string crashes ultralytics
    for k, v in MODEL_ENV.items():
        os.environ.setdefault(k, str(v))
    sys.path.insert(0, str(REPO_ROOT))
    from backend.worker.pipeline import PipelineConfig, run_pipeline

    with tempfile.TemporaryDirectory(prefix="piya-moonriver-diag-") as work:
        res = run_pipeline([_app_like_jpeg(PHOTO_DIR / p) for p in PHOTOS], tempo_bpm=TEMPO_BPM,
                           work_dir=Path(work), config=PipelineConfig.from_env(os.environ),
                           on_stage=lambda s, p: print(f"STAGE {s} {p}", flush=True), timing=True)
    data = {"events": res.events, "report": res.timing_inputs["report"], "review": res.review,
            "failed_voices": res.failed_voices, "mp3_bytes": {v: len(b) for v, b in res.mp3.items()},
            "stage_seconds": res.stage_seconds}
    (out / "pipeline_out.json").write_text(json.dumps(data, default=str), encoding="utf-8")
    return data


def pred_notes(events: list[dict[str, Any]], pickup: int) -> list[Note]:
    """Reconstructed events as Notes; onset rebased so bar 1's downbeat is tick 0 (the reference has no pickup)."""
    out = [{"pitch": e["pitch"] if e["type"] == "note" else None, "onset": e["tick_onset"] - pickup,
            "dur": e["duration_ticks"], "bar": e.get("global_bar"), "tie_span": e.get("tie_span", 1),
            "page": e.get("page_index")} for e in events if e["type"] in ("note", "rest")]
    return sorted(out, key=lambda n: n["onset"])


def seq_counts(ref: list[Any], pred: list[Any], lev: Any) -> dict[str, int]:
    """Matched/substituted/missing/extra from edit distance d and match count M (S+D=n-M, S+I=k-M, S+D+I=d)."""
    d, matched = lev(ref, pred, lambda x, y: x == y)
    n, k, mm = len(ref), len(pred), sum(matched)
    ins, dele = d - (n - mm), d - (k - mm)
    return {"ref": n, "pred": k, "matched": mm, "wrong": n - mm - dele, "missing": dele, "extra": ins}


def f1_strict(ref: list[Note], pred: list[Note]) -> dict[str, float]:
    """One-to-one note matching: same pitch, onset and duration each within a 16th."""
    r = [n for n in ref if n["pitch"] is not None]
    p = [n for n in pred if n["pitch"] is not None]
    used: set[int] = set()
    tp = 0
    for a in r:
        best, best_d = None, TOL + 1
        for j, b in enumerate(p):
            if j in used or b["pitch"] != a["pitch"] or abs(b["dur"] - a["dur"]) > TOL:
                continue
            dist = abs(b["onset"] - a["onset"])
            if dist < best_d:
                best, best_d = j, dist
        if best is not None:
            used.add(best)
            tp += 1
    prec, rec = tp / max(1, len(p)), tp / max(1, len(r))
    return {"tp": tp, "ref_notes": len(r), "pred_notes": len(p), "precision": prec, "recall": rec,
            "f1": 2 * prec * rec / max(1e-9, prec + rec)}


DB_MAJOR_PCS = {0, 1, 3, 5, 6, 8, 10}  # the reference key signature is 5 flats


def _in_key(notes: list[Note]) -> float:
    return sum(n["pitch"] % 12 in DB_MAJOR_PCS for n in notes) / max(1, len(notes))


def _repeats(events: list[Note]) -> int:
    return sum(a["pitch"] is not None and a["pitch"] == b["pitch"] for a, b in zip(events, events[1:]))


def score_voice(ref: list[Note], pred: list[Note], bars: dict[int, tuple[int, int]], lev: Any) -> dict[str, Any]:
    ref_len = {b: length for b, (_, length) in bars.items()}
    ref_start = {b: start for b, (start, _) in bars.items()}
    ref_notes = [n for n in ref if n["pitch"] is not None]
    # (1a) position aligned: same (bar, onset inside bar)
    pos = {(n["bar"], n["onset"] - ref_start[n["bar"]]): n for n in ref}
    # Pred bar start = its first event: the pipeline lays bars on a fixed 4/4 grid when it misreads the meter,
    # so absolute ticks drift from the reference while the bar's inner rhythm can still be right.
    pred_start: dict[int, int] = {}
    for n in pred:
        if n["bar"]:
            pred_start[n["bar"]] = min(pred_start.get(n["bar"], n["onset"]), n["onset"])
    by_pos = {(n["bar"], n["onset"] - pred_start[n["bar"]]): n for n in pred if n["bar"]}
    p_ok = r_ok = 0
    diffs: list[int] = []
    for key, rn in pos.items():
        pn = by_pos.get(key)
        if pn is None:
            continue
        r_ok += pn["dur"] == rn["dur"] and (pn["pitch"] is None) == (rn["pitch"] is None)
        if rn["pitch"] is not None and pn["pitch"] is not None:
            p_ok += pn["pitch"] == rn["pitch"]
            diffs.append(pn["pitch"] - rn["pitch"])
    # (1b) sequence aligned (edit distance), rests ignored for pitch; durations over notes+rests for rhythm
    pitch_seq = seq_counts([n["pitch"] for n in ref_notes], [n["pitch"] for n in pred if n["pitch"] is not None], lev)
    rhythm_seq = seq_counts([(n["pitch"] is None, n["dur"]) for n in ref], [(n["pitch"] is None, n["dur"]) for n in pred], lev)
    # (4) bars
    pred_bars: dict[int, int] = {}
    for n in pred:
        if n["bar"]:
            pred_bars[n["bar"]] = pred_bars.get(n["bar"], 0) + n["dur"]
    # Error typing on position-aligned wrong pitches.
    typed: Counter[str] = Counter()
    for d in diffs:
        if d == 0:
            continue
        typed["octave" if d % 12 == 0 else "semitone(accidental/key)" if abs(d) == 1 else
              "whole_tone" if abs(d) == 2 else "other"] += 1
    return {
        "ref_notes": len(ref_notes), "ref_events": len(ref),
        "pos_aligned_pairs": len(diffs), "pitch_acc_position": sum(d == 0 for d in diffs) / max(1, len(ref_notes)),
        "rhythm_acc_position": r_ok / max(1, len(ref)),
        "pitch_seq": pitch_seq, "pitch_acc_sequence": pitch_seq["matched"] / max(1, pitch_seq["ref"]),
        "rhythm_seq": rhythm_seq, "rhythm_acc_sequence": rhythm_seq["matched"] / max(1, rhythm_seq["ref"]),
        "f1": f1_strict(ref, pred),
        # Same test with onsets taken inside their own bar: separates a misread meter from misread notes.
        "f1_bar_relative": f1_strict(
            [{**n, "onset": n["bar"] * BAR_SPAN + n["onset"] - ref_start[n["bar"]]} for n in ref],
            [{**n, "onset": n["bar"] * BAR_SPAN + n["onset"] - pred_start[n["bar"]]} for n in pred if n["bar"]]),
        "bars": {"ref": len(ref_len), "pred_numbered": len(pred_bars), "pred_pickup_events": sum(not n["bar"] for n in pred),
                 "correct_total_length": sum(pred_bars.get(b) == L for b, L in ref_len.items())},
        "wrong_pitch_error_types_on_aligned": dict(typed),
        "median_pred_minus_ref_semitones": statistics.median(diffs) if diffs else None,
        "rests": {"ref": sum(n["pitch"] is None for n in ref), "pred": sum(n["pitch"] is None for n in pred)},
        "median_pitch": {"ref": statistics.median(n["pitch"] for n in ref_notes),
                         "pred": statistics.median(n["pitch"] for n in pred if n["pitch"] is not None)},
        "share_in_key_db_major": {"ref": _in_key(ref_notes), "pred": _in_key([n for n in pred if n["pitch"] is not None])},
        "adjacent_same_pitch_pairs": {"ref": _repeats(ref), "pred": _repeats(pred)},  # unmerged ties show up here
        "ref_tied_notes": sum(1 for n in ref if n.get("tied")),
        "pred_tie_merged_notes": sum(1 for n in pred if n.get("tie_span", 1) > 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--reuse", action="store_true", help="score the saved pipeline_out.json instead of re-running")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(HARNESS_TOOLS))
    from stage4_eval import _lev, aligned_voice_pages, score_events  # noqa: E402

    mxl = export_mxl(args.out)
    ref, bars = reference(mxl)
    data = json.loads((args.out / "pipeline_out.json").read_text(encoding="utf-8")) if args.reuse \
        else run_app_pipeline(args.out)
    pickup = int(data["report"].get("pickup_ticks", 0) or 0)
    voices = {v: pred_notes(data["events"][v.lower()], pickup) for v in PARTS}
    per_voice = {v: score_voice(ref[v], voices[v], bars, _lev) for v in PARTS}
    # Overall = pooled counts (not a mean of ratios).
    pooled: dict[str, Any] = {}
    for key, num, den in (("pitch_acc_position", None, "ref_notes"), ("rhythm_acc_position", None, "ref_events")):
        pooled[key] = sum(per_voice[v][key] * per_voice[v][den] for v in PARTS) / sum(per_voice[v][den] for v in PARTS)
    for key, seq in (("pitch_acc_sequence", "pitch_seq"), ("rhythm_acc_sequence", "rhythm_seq")):
        pooled[key] = sum(per_voice[v][seq]["matched"] for v in PARTS) / sum(per_voice[v][seq]["ref"] for v in PARTS)
        pooled[seq] = {k: sum(per_voice[v][seq][k] for v in PARTS) for k in per_voice["Soprano"][seq]}
    for fk in ("f1", "f1_bar_relative"):
        tp = sum(per_voice[v][fk]["tp"] for v in PARTS)
        nr, npd = sum(per_voice[v][fk]["ref_notes"] for v in PARTS), sum(per_voice[v][fk]["pred_notes"] for v in PARTS)
        prec, rec = tp / max(1, npd), tp / max(1, nr)
        pooled[fk] = {"tp": tp, "ref_notes": nr, "pred_notes": npd, "precision": prec, "recall": rec,
                      "f1": 2 * prec * rec / max(1e-9, prec + rec)}
    pooled["errors_on_aligned"] = dict(sum((Counter(per_voice[v]["wrong_pitch_error_types_on_aligned"]) for v in PARTS), Counter()))
    # Reused harness scorer: strict SER (ties merged only where the reference ties) per page-aligned bars.
    pred_titled = {v: data["events"][v.lower()] for v in PARTS}
    harness = {}
    for mode in ("page", "voice_page"):
        r = score_events(pred_titled, mxl, set(range(1, 41)), PAGE_RANGES, PARTS, align_by=mode)
        harness[mode] = {"total": r["total"], "voices": r["voices"], "unaligned_pages": r["unaligned"]}
    harness["aligned_voice_pages"] = sorted(map(list, aligned_voice_pages(pred_titled, PAGE_RANGES, tuple(PARTS))))
    bar40 = {v: [(n["pitch"], n["dur"]) for n in voices[v] if n["bar"] == BASS_DIVISI_BAR] for v in ("Bass",)}
    flags = Counter(f.get("kind", "?") for f in data["report"].get("flags", []))
    ref_ticks = max(s + length for s, length in bars.values())
    silence = {v: sum(f["expected_ticks"] - f["actual_ticks"] for f in data["report"]["flags"]
                      if f.get("kind") == "bar_underfull" and f.get("voice") == v) for v in PARTS}
    timeline = {"ref_total_ticks": ref_ticks, "pred_total_ticks": data["report"].get("total_ticks"),
                "underfull_silence_ticks_per_voice": silence,
                "pred_time_signatures": dict(Counter(e.get("time_signature") for v in PARTS
                                                     for e in data["events"][v.lower()]))}
    out = {"BANNER": "DEV DATA, DIAGNOSTIC ONLY, NOT AN ACCURACY RESULT", "reference": divisi_report(mxl),
           "pickup_ticks": pickup, "timeline": timeline, "per_voice": per_voice,
           "overall": pooled, "harness": harness, "bass_bar40_pred": bar40, "report_flag_counts": dict(flags),
           "failed_voices": data["failed_voices"], "review": data["review"], "mp3_bytes": data["mp3_bytes"]}
    (args.out / "scores.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
