"""Mid-strip meter change applied on a system quorum, per-bar meters in Stage 4 (Task 3, 2026-11-04 plan).

Tokens are hand-written; no model, GPU or soundfont. These tests show the rule works WHEN the CRNN emits
the meter tokens; they say nothing about how often it does on real images (BUG-011).
"""

import os
import sys
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage3_transcription as s3  # noqa: E402
import stage4_reconstruction as s4  # noqa: E402
import stage5_synthesis as s5  # noqa: E402
import timing_export  # noqa: E402

VOICES = ["Soprano", "Alto", "Tenor", "Bass"]
Q, H = "note.quarter-L2", "note.half-L2"
BAR = "barline-L1"
CLEF = "clef.G-L2"
M44, M34, M24 = ["digit.4-L4", "digit.4-L2"], ["digit.3-L4", "digit.4-L2"], ["digit.2-L4", "digit.4-L2"]
WHOLE, QUARTER = 1920, 480
Systems = dict[tuple[int, int], dict[str, list[str]]]


def _stage3(systems: Systems) -> dict[str, list[dict[str, Any]]]:
    """Runs the system-level checks and pitch inference of transcribe_voice_sequences on token lists."""
    decoded: dict[str, dict[str, Any]] = {}
    for (page, sys_idx), per_voice in systems.items():
        for voice, toks in per_voice.items():
            decoded[f"p{page}s{sys_idx}{voice}"] = dict(voice=voice, voice_label=voice, page_index=page,
                                                        sys_idx=sys_idx, symbols=list(toks), decision=None)
    s3._apply_system_checks(decoded, set())
    out: dict[str, list[dict[str, Any]]] = {v: [] for v in VOICES}
    for d in decoded.values():
        events = s3.infer_pitch(d["symbols"], voice=d["voice"], page_index=d["page_index"], sys_idx=d["sys_idx"],
                                system_key_changes=d["system_key_changes"],
                                system_meter_changes=d["system_meter_changes"])
        for e in events:
            if d["mid_change_flags"]:
                e["mid_change_flags"] = list(d["mid_change_flags"])
        out[d["voice"]].extend(events)
    for v in VOICES:
        out[v].sort(key=lambda e: (e["page_index"], e["sys_idx"], e["tick_onset"]))
    return out


def _same(toks: list[str], **per_voice: list[str]) -> dict[str, list[str]]:
    return {v: per_voice.get(v, toks) for v in VOICES}


def _bars(report: dict[str, Any]) -> list[tuple[int, str, str]]:
    return [(b["ticks"], b["time_signature"], b["meter_source"]) for s in report["systems"] for b in s["bars"]]


def _kinds(report: dict[str, Any]) -> list[str]:
    return [f["kind"] for f in report["flags"]]


CHANGE = [CLEF, *M44, Q, Q, Q, Q, BAR, *M34, Q, Q, Q, BAR, Q, Q, Q, BAR]
NO_METER = [CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR, Q, Q, Q, BAR]
NO_GLYPH = [CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, Q, BAR, Q, Q, Q, BAR]  # CHANGE with the 3/4 glyph missed


def test_three_voices_agree_3_4_applied() -> None:
    # Moonriver shape: 4/4 in bar 1, 3/4 after it. Bass's glyph is missed; 3 of 4 is the quorum.
    systems = {(1, 1): _same(CHANGE, Bass=NO_GLYPH)}
    ev = _stage3(systems)
    assert [e["time_signature"] for e in ev["Bass"]] == ["4/4"] * 4 + ["3/4"] * 6
    _, report = s4.reconstruct_satb_with_report(ev)
    assert _bars(report) == [(WHOLE, "4/4", "explicit"), (3 * QUARTER, "3/4", "explicit"),
                             (3 * QUARTER, "3/4", "explicit")]
    assert s4.FLAG_BAR_UNDERFULL not in _kinds(report)
    assert report["total_ticks"] == WHOLE + 6 * QUARTER


def test_flag_off_reproduces_r3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3, "APPLY_MID_METER_CHANGE", False)
    ev = _stage3({(1, 1): _same(CHANGE, Bass=NO_GLYPH)})
    assert {e["time_signature"] for v in VOICES for e in ev[v]} == {"4/4"}
    assert not any("time_signature_source" in e for v in VOICES for e in ev[v])
    _, report = s4.reconstruct_satb_with_report(ev)
    assert _kinds(report).count(s4.FLAG_BAR_UNDERFULL) == 8


def test_two_voices_stray_digit_not_applied() -> None:
    ev = _stage3({(1, 1): _same(NO_METER, Soprano=CHANGE, Alto=CHANGE)})
    assert {e["time_signature"] for v in VOICES for e in ev[v]} == {"4/4"}
    assert s3.MID_METER_UNCONFIRMED_FLAG in ev["Soprano"][0]["mid_change_flags"]


def test_quorum_is_three_of_the_readable_voices() -> None:
    three = _same(CHANGE, Bass=NO_METER)
    del three["Bass"]
    ev = _stage3({(1, 1): three})
    assert ev["Alto"][-1]["time_signature"] == "3/4"
    two = _same(CHANGE, Tenor=NO_METER)
    del two["Bass"]
    ev = _stage3({(1, 1): two})
    assert ev["Alto"][-1]["time_signature"] == "4/4"


def test_explicit_token_beats_inference() -> None:
    assert s4.resolve_bar_meter("2/4", None, [3 * QUARTER] * 6) == ("2/4", "explicit")
    assert s4.resolve_bar_meter("2/4", "3/4", [3 * QUARTER] * 6) == ("2/4", "explicit")
    # Header 2/4 read in every voice while the bars sum to three quarters: the token wins.
    ev = _stage3({(1, 1): _same([CLEF, *M24, Q, Q, Q, BAR, Q, Q, Q, BAR, Q, Q, Q, BAR])})
    _, report = s4.reconstruct_satb_with_report(ev)
    assert {b[1] for b in _bars(report)} == {"2/4"}
    assert "meter_inferred" not in _kinds(report)


def test_carry_forward_across_system_break() -> None:
    # 3/4 header on page 1, no meter on the next system or page: both keep 3/4, never reset to 4/4.
    systems = {(1, 1): _same([CLEF, *M34, Q, Q, Q, BAR, Q, Q, Q, BAR]),
               (1, 2): _same([CLEF, Q, Q, Q, BAR, Q, Q, Q, BAR]),
               (2, 1): _same([CLEF, Q, Q, Q, BAR])}
    _, report = s4.reconstruct_satb_with_report(_stage3(systems))
    assert _bars(report) == ([(3 * QUARTER, "3/4", "explicit")] * 2 + [(3 * QUARTER, "3/4", "carried")] * 3)
    assert s4.FLAG_BAR_UNDERFULL not in _kinds(report)


def test_courtesy_change_back_to_4_4_carries_into_next_system() -> None:
    # Moonriver p2: 3/4 bars, a courtesy 4/4 after the last barline, next system one 4/4 bar then 3/4.
    # The 4/4 reading is a real change, not a default.
    systems = {(1, 1): _same([CLEF, *M34, Q, Q, Q, BAR, Q, Q, Q, BAR, *M44]),
               (1, 2): _same([CLEF, Q, Q, Q, Q, BAR, *M34, Q, Q, Q, BAR])}
    _, report = s4.reconstruct_satb_with_report(_stage3(systems))
    assert [b[:2] for b in _bars(report)] == [(3 * QUARTER, "3/4"), (3 * QUARTER, "3/4"), (WHOLE, "4/4"),
                                              (3 * QUARTER, "3/4")]
    assert s4.FLAG_BAR_UNDERFULL not in _kinds(report)
    assert s4.FLAG_BAR_OVERFLOW not in _kinds(report)


def test_inferred_three_quarters_is_3_4_flagged_internally() -> None:
    # No meter token anywhere: three-quarter bars infer 3/4, flagged; the client review never sees it.
    ev = _stage3({(1, 1): _same([CLEF, Q, Q, Q, BAR, Q, Q, Q, BAR, Q, Q, Q, BAR, Q, Q, Q, BAR])})
    assert {e["time_signature_source"] for v in VOICES for e in ev[v]} == {"default"}
    _, report = s4.reconstruct_satb_with_report(ev)
    assert {b[:2] for b in _bars(report)} == {(3 * QUARTER, "3/4")}
    assert _bars(report)[0][2] == "inferred"
    assert s4.FLAG_METER_INFERRED in _kinds(report)
    assert s4.FLAG_BAR_UNDERFULL not in _kinds(report)
    review, _ = s5.build_review(ev, report["flags"])
    assert review["reviewNeeded"] is False


def test_default_4_4_last_resort() -> None:
    assert s4.resolve_bar_meter(None, None, []) == ("4/4", "default")
    assert s4.resolve_bar_meter(None, "3/4", [WHOLE] * 9) == ("3/4", "carried")
    assert s4.resolve_bar_meter(None, None, [WHOLE] * 4) == ("4/4", "inferred")
    assert s4.resolve_bar_meter(None, None, [2 * QUARTER] * 3) == ("2/4", "inferred")
    # Five quarters (likely a merged bar) and 2.5 quarters are never inferred.
    assert s4.resolve_bar_meter(None, None, [5 * QUARTER] * 6) == ("4/4", "default")
    assert s4.resolve_bar_meter(None, None, [5 * QUARTER // 2] * 6) == ("4/4", "default")
    # Two bars that disagree: no clear majority, no inference.
    assert s4.resolve_bar_meter(None, None, [3 * QUARTER, WHOLE]) == ("4/4", "default")
    ev = _stage3({(1, 1): _same([CLEF, Q, Q, Q, "note.eighth-L2", BAR, Q, Q, Q, "note.eighth-L2", BAR,
                                 Q, Q, Q, "note.eighth-L2", BAR])})
    _, report = s4.reconstruct_satb_with_report(ev)
    assert s4.FLAG_METER_NOT_INFERRED in _kinds(report)
    assert {b[1] for b in _bars(report)} == {"4/4"}


def _strip_source(satb: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {v: [{k: x for k, x in e.items() if k != "time_signature_source"} for e in evs]
            for v, evs in satb.items()}


def test_no_change_piece_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    systems = {(1, 1): _same([CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, H, BAR]),
               (1, 2): _same([CLEF, Q, Q, Q, Q, BAR, H, H, BAR], Tenor=[CLEF, Q, Q, Q, BAR, H, H, BAR])}
    on_satb, on_rep = s4.reconstruct_satb_with_report(_stage3(systems))
    monkeypatch.setattr(s3, "APPLY_MID_METER_CHANGE", False)
    off_satb, off_rep = s4.reconstruct_satb_with_report(_stage3(systems))
    assert _strip_source(on_satb) == off_satb
    assert on_rep["flags"] == off_rep["flags"] and on_rep["total_ticks"] == off_rep["total_ticks"]


def test_correlated_misread_is_flagged_for_review() -> None:
    # Three voices read 3/4 but every bar still holds four quarters: applied (quorum), but the bar
    # durations contradict it, so it is flagged review_needed instead of shifting ticks silently.
    toks = [CLEF, *M44, Q, Q, Q, Q, BAR, *M34, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR]
    plain = [CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR]
    _, report = s4.reconstruct_satb_with_report(_stage3({(1, 1): _same(toks, Bass=plain)}))
    hits = [f for f in report["flags"] if f["kind"] == s4.FLAG_METER_DURATION_MISMATCH]
    assert len(hits) == 1 and hits[0]["review_needed"] is True and hits[0]["bar"] == 2


def test_confirmed_change_has_no_duration_flag() -> None:
    _, report = s4.reconstruct_satb_with_report(_stage3({(1, 1): _same(CHANGE, Bass=NO_METER)}))
    assert s4.FLAG_METER_DURATION_MISMATCH not in _kinds(report)


def test_mid_strip_meter_change_flag_not_client_review() -> None:
    ev = _stage3({(1, 1): _same(CHANGE, Bass=NO_METER)})
    assert s3.MID_METER_CHANGE_FLAG in ev["Soprano"][0]["mid_change_flags"]
    _, report = s4.reconstruct_satb_with_report(ev)
    review, full = s5.build_review(ev, report["flags"])
    assert review["reviewNeeded"] is False and review["items"] == []
    assert s3.MID_METER_CHANGE_FLAG in {i["code"] for i in full}


def test_timing_bars_use_per_bar_meter() -> None:
    _, report = s4.reconstruct_satb_with_report(_stage3({(1, 1): _same(CHANGE, Bass=NO_METER)}))
    bars = timing_export._bar_layout(report)
    assert [(b["startTick"], b["durTicks"], b["numerator"]) for b in bars] == [
        (0, WHOLE, 4), (WHOLE, 3 * QUARTER, 3), (WHOLE + 3 * QUARTER, 3 * QUARTER, 3)]
