"""Tests for per-measure meter, multirest counts, muted measures and failed voices.

Covers PIYA-107 AC7-AC9 (Stage 3 meter/multirest parsing), PIYA-108 AC4-AC8 (Stage 4 per-bar layout,
inherit-on-default, lossy-repair spans, failed voices), PIYA-109 AC8/AC9 and PIYA-103 AC9/AC10 (Stage 5
silence and the result fields), and PIYA-117 AC9 (the ``bars`` table), plus the BUG-035/051/052 repros.

Run with ``python -m pytest tests/test_meter_and_muting.py``. No GPU, model or soundfont: tokens are
hand-written and MP3 rendering is stubbed. These tests show the parser and layout handle meter and
multirest tokens WHEN THEY ARE EMITTED; they say nothing about whether the CRNN emits them on real
images (BUG-035/051 real-image detection is unverified).
"""

import os
import sys
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")  # BUG-013: never touch the GPU
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage3_transcription as s3  # noqa: E402
import stage4_reconstruction as s4  # noqa: E402
import stage5_synthesis as s5  # noqa: E402

VOICES = ["Soprano", "Alto", "Tenor", "Bass"]
Q, H, E8 = "note.quarter-L2", "note.half-L2", "note.eighth-L2"
BAR = "barline-L1"
CLEF = "clef.G-L2"
M44, M34, M68 = ["digit.4-L4", "digit.4-L2"], ["digit.3-L4", "digit.4-L2"], ["digit.6-L4", "digit.8-L2"]
WHOLE, QUARTER = 1920, 480
BPM = 90


def _events(tokens: list[str], voice: str = "Soprano", page: int = 1, sys_idx: int = 1) -> list[dict]:
    return s3.infer_pitch(list(tokens), voice=voice, page_index=page, sys_idx=sys_idx)


def _all_voices(tokens: list[str], sys_idx: int = 1, **per_voice: list[str]) -> dict[str, list[dict]]:
    return {v: _events(per_voice.get(v, tokens), v, 1, sys_idx) for v in VOICES}


def _merge(*systems: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {v: [e for sysd in systems for e in sysd[v]] for v in VOICES}


def _bar_layout(report: dict[str, Any]) -> list[tuple[int, str, str]]:
    return [(b["ticks"], b["time_signature"], b["meter_source"])
            for sysd in report["systems"] for b in sysd["bars"]]


# ── Stage 3: meter and multirest tokens (PIYA-107 AC7-AC9) ─────────────────────

def test_bug051_mid_strip_meter_change() -> None:
    tokens = [CLEF, *M44, Q, Q, Q, Q, BAR, *M34, Q, Q, Q, BAR]
    ev = _events(tokens)
    assert [e["time_signature"] for e in ev] == ["4/4"] * 4 + ["3/4"] * 3
    assert {e["time_signature_source"] for e in ev} == {"detected"}
    assert not any(e.get("type") == "multirest" or "multirest" in str(e.get("symbol")) for e in ev)
    _, report = s4.reconstruct_satb_with_report(_all_voices(tokens))
    assert _bar_layout(report) == [(WHOLE, "4/4", "detected"), (3 * QUARTER, "3/4", "detected")]
    assert not [f for f in report["flags"] if f["kind"].startswith("bar_")]


def test_bug035_multirest_before_meter_keeps_its_bars() -> None:
    ev = _events([CLEF, "digit.4-S5", "multirest-L3", BAR, Q])
    rests = [e for e in ev if "multirest" in str(e.get("symbol"))]
    assert len(rests) == 1 and rests[0]["multirest_bars"] == 4
    assert rests[0]["duration_ticks"] == 4 * WHOLE
    note = [e for e in ev if e["type"] == "note"][0]
    assert note["tick_onset"] == 4 * WHOLE and note["time_signature_source"] == "default"
    assert not ev[0].get("meter_flags")


def test_multi_digit_multirest_count_is_decimal() -> None:
    ev = _events([CLEF, *M44, "digit.1-S5", "digit.6-S5", "multirest-L3", BAR, Q])
    assert [e["multirest_bars"] for e in ev if "multirest" in str(e.get("symbol"))] == [16]


def test_bug052_multirest_in_three_four() -> None:
    # Corpus order (count before the multirest): 4 bars of 3/4, not 5 bars of whole-note length.
    tokens = [CLEF, *M34, "digit.4-S5", "multirest-L3", BAR, Q, Q, Q, BAR]
    ev = _events(tokens)
    rest = [e for e in ev if "multirest" in str(e.get("symbol"))][0]
    assert rest["multirest_bars"] == 4 and rest["duration_ticks"] == 4 * 3 * QUARTER
    satb, report = s4.reconstruct_satb_with_report(_all_voices(tokens))
    assert report["systems"][0]["n_bars"] == 5
    assert [b["ticks"] for b in report["systems"][0]["bars"]] == [3 * QUARTER] * 5
    first_note = [e for e in satb["Soprano"] if e["type"] == "note"][0]
    assert first_note["tick_onset"] == 4 * 3 * QUARTER and first_note["global_bar"] == 5


def test_bug052_literal_repro_no_longer_counts_five_bars() -> None:
    # The bug row's order (count AFTER the multirest) is not a count in the corpus: the digit is flagged
    # as orphaned and the rest covers one bar, instead of silently becoming 5 bars.
    tokens = [CLEF, *M34, "multirest-L3", "digit.4-S5", BAR]
    ev = _events(tokens)
    assert ev[0]["meter_flags"] == [s3.METER_FLAG_ORPHAN_COUNT]
    _, report = s4.reconstruct_satb_with_report(_all_voices(tokens))
    assert report["systems"][0]["n_bars"] == 1


def test_orphan_s5_count_is_flagged_and_ignored() -> None:
    ev = _events([CLEF, *M44, Q, Q, Q, Q, BAR, "digit.3-S5", Q, Q, Q, Q, BAR])
    assert ev[0]["meter_flags"] == [s3.METER_FLAG_ORPHAN_COUNT]
    assert {e["time_signature"] for e in ev} == {"4/4"}
    assert [e["tick_onset"] for e in ev][4] == WHOLE


def test_lone_l4_digit_is_flagged_not_a_meter() -> None:
    ev = _events([CLEF, *M44, Q, Q, Q, Q, BAR, "digit.3-L4", Q, Q, Q, Q, BAR])
    assert ev[0]["meter_flags"] == [s3.METER_FLAG_UNPAIRED_DIGIT]
    assert {e["time_signature"] for e in ev} == {"4/4"}


def test_courtesy_meter_at_strip_end_does_not_change_meter() -> None:
    ev = _events([CLEF, *M44, Q, Q, Q, Q, BAR, *M34])
    assert {e["time_signature"] for e in ev} == {"4/4"} and not ev[0].get("meter_flags")


def test_default_meter_is_marked_default() -> None:
    ev = _events([CLEF, Q, Q, Q, Q, BAR])
    assert {(e["time_signature"], e["time_signature_source"]) for e in ev} == {("4/4", "default")}


# ── Stage 4: per-bar meter, inheritance, disagreement (PIYA-108 AC6/AC7) ──────

def test_meter_change_back_to_four_four() -> None:
    # Mid-strip 3/4 -> 4/4, then a system with no meter of its own: the detected 4/4 counts (it is not
    # mistaken for a default) and the next system inherits it.
    sys1 = _all_voices([CLEF, *M34, Q, Q, Q, BAR, *M44, Q, Q, Q, Q, BAR], sys_idx=1)
    sys2 = _all_voices([CLEF, Q, Q, Q, Q, BAR], sys_idx=2)
    _, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    assert _bar_layout(report) == [(3 * QUARTER, "3/4", "detected"), (WHOLE, "4/4", "detected"),
                                   (WHOLE, "4/4", "inherited")]
    assert report["total_ticks"] == 3 * QUARTER + 2 * WHOLE


def test_defaulted_system_inherits_non_four_four() -> None:
    sys1 = _all_voices([CLEF, *M34, Q, Q, Q, BAR], sys_idx=1)
    sys2 = _all_voices([CLEF, Q, Q, Q, BAR], sys_idx=2)
    _, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    assert _bar_layout(report) == [(3 * QUARTER, "3/4", "detected"), (3 * QUARTER, "3/4", "inherited")]
    assert not [f for f in report["flags"] if f["kind"].startswith("bar_")]


def test_meter_disagreement_is_flagged() -> None:
    agree = [CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR]
    odd = [CLEF, *M44, Q, Q, Q, Q, BAR, *M34, Q, Q, Q, BAR]
    _, report = s4.reconstruct_satb_with_report(_all_voices(agree, Soprano=odd))
    dis = [f for f in report["flags"] if f["kind"] == s4.FLAG_METER_DISAGREEMENT]
    assert len(dis) == 1 and dis[0]["review_needed"] is True
    assert _bar_layout(report)[1][1] == "4/4", "the 3-voice majority wins"


# ── Stage 4 spans + Stage 5 silence (PIYA-108 AC8, PIYA-109 AC8, PIYA-103 AC9) ─

PLAIN = [CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR]
OVERFULL = [CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, Q, Q, H, BAR, Q, Q, Q, Q, BAR]


def test_lossy_clip_carries_a_bar_span() -> None:
    _, report = s4.reconstruct_satb_with_report(_all_voices(PLAIN, Alto=OVERFULL))
    clipped = [f for f in report["flags"] if f["kind"] == "bar_overflow_clipped"]
    assert len(clipped) == 1
    f = clipped[0]
    assert f["muted"] is True and (f["start_tick"], f["end_tick"]) == (WHOLE, 2 * WHOLE)
    assert f["voice"] == "Alto" and f["bar"] == 2


def test_scaled_repair_is_not_muted() -> None:
    tuplet = [CLEF, *M44, Q, Q, Q, Q, BAR, H, H, H, BAR, Q, Q, Q, Q, BAR]
    _, report = s4.reconstruct_satb_with_report(_all_voices(PLAIN, Bass=tuplet))
    assert [f["kind"] for f in report["flags"]] == ["suspected_tuplet"]
    assert not any(f.get("muted") for f in report["flags"])


def test_clipped_with_no_drops_is_not_muted(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_loss(m_events: list, first_local: int, bar_ticks: int, total: int) -> tuple:
        return m_events, "bar_overflow_clipped", "nothing dropped", "clipped", 0
    monkeypatch.setattr(s4, "_repair_overflow", no_loss)
    _, report = s4.reconstruct_satb_with_report(_all_voices(PLAIN, Alto=OVERFULL))
    clipped = [f for f in report["flags"] if f["kind"] == "bar_overflow_clipped"]
    assert clipped and not any(f.get("muted") for f in clipped)


def _note(onset: int, dur: int, pitch: int = 60) -> dict:
    return {"type": "note", "pitch": pitch, "tick_onset": onset, "duration_ticks": dur}


def test_muted_span_drops_and_cuts_notes() -> None:
    events = [_note(0, 2 * WHOLE),           # sounds into the span: cut at its start
              _note(WHOLE + QUARTER, QUARTER),   # starts inside: dropped
              {"type": "rest", "pitch": None, "tick_onset": WHOLE + 2 * QUARTER, "duration_ticks": QUARTER},
              _note(2 * WHOLE, QUARTER)]     # span end is exclusive: kept
    out = s5.apply_muted_spans(events, [(WHOLE, 2 * WHOLE)])
    assert [(e["type"], e["tick_onset"], e["duration_ticks"]) for e in out] == [
        ("note", 0, WHOLE), ("rest", WHOLE + 2 * QUARTER, QUARTER), ("note", 2 * WHOLE, QUARTER)]
    assert events[0]["duration_ticks"] == 2 * WHOLE, "input not mutated"


def test_muted_measures_entries() -> None:
    flags = [
        {"kind": "bar_overflow_clipped", "voice": "Bass", "page_index": 1, "sys_idx": 2, "bar": 4,
         "muted": True, "start_tick": 3 * WHOLE, "end_tick": 4 * WHOLE, "review_needed": True},
        {"kind": "pickup_length_mismatch", "voice": "Alto", "page_index": 1, "sys_idx": 1, "bar": 0,
         "muted": True, "start_tick": 0, "end_tick": QUARTER, "review_needed": True},
        {"kind": "local_placement_overrun", "voice": "Soprano", "page_index": 2, "sys_idx": 1, "bar": None,
         "muted": True, "start_tick": 3 * WHOLE, "end_tick": 4 * WHOLE, "review_needed": True},
        {"kind": "bar_overflow_run_scaled", "voice": "Tenor", "page_index": 1, "sys_idx": 1, "bar": 1,
         "review_needed": True},
        {"kind": "bar_overflow_clipped", "voice": "Tenor", "page_index": 1, "sys_idx": 1, "bar": 2,
         "muted": True, "start_tick": WHOLE, "end_tick": 2 * WHOLE, "review_needed": True},
    ]
    muted = s5.build_muted_measures(flags, BPM, failed_voices=["tenor"])
    assert muted == [
        {"voice": "alto", "bar": 0, "pageIndex": 0, "systemIndex": 0, "startMs": 0, "endMs": 667,
         "reason": "pickup_length_mismatch"},
        {"voice": "soprano", "bar": None, "pageIndex": 1, "systemIndex": 0, "startMs": 8000, "endMs": 10667,
         "reason": "local_placement_overrun"},
        {"voice": "bass", "bar": 4, "pageIndex": 0, "systemIndex": 1, "startMs": 8000, "endMs": 10667,
         "reason": "bar_overflow_clipped"},
    ]
    review, full = s5.build_review({}, flags, ["tenor"])
    codes = {(i["code"], i["voice"], i["bar"], i["pageIndex"], i["systemIndex"]) for i in review["items"]}
    assert all((m["reason"], m["voice"], m["bar"], m["pageIndex"], m["systemIndex"]) in codes for m in muted)
    assert full == review["items"], "the stored review_detail uses the same 0-based indices"
    assert s5.muted_spans_by_voice(flags) == {"Bass": [(3 * WHOLE, 4 * WHOLE)], "Alto": [(0, QUARTER)],
                                              "Soprano": [(3 * WHOLE, 4 * WHOLE)],
                                              "Tenor": [(WHOLE, 2 * WHOLE)]}


# ── PIYA-117 AC9 bars table ────────────────────────────────────────────────────

def test_bars_table_matches_piya117_example() -> None:
    tokens = [CLEF, *M34, Q, BAR, Q, Q, Q, BAR, Q, Q, Q, BAR, *M68, E8, E8, E8, E8, E8, E8, BAR]
    _, report = s4.reconstruct_satb_with_report(_all_voices(tokens))
    meter = {"meterSource": "detected", "groups": None}
    assert s5.build_bars_table(report, BPM) == [
        {"bar": 0, "startMs": 0, "durMs": 667, "startTick": 0, "durTicks": 480, "numerator": 3,
         "denominator": 4, "pickup": True, **meter},
        {"bar": 1, "startMs": 667, "durMs": 2000, "startTick": 480, "durTicks": 1440, "numerator": 3,
         "denominator": 4, "pickup": False, **meter},
        {"bar": 2, "startMs": 2667, "durMs": 2000, "startTick": 1920, "durTicks": 1440, "numerator": 3,
         "denominator": 4, "pickup": False, **meter},
        {"bar": 3, "startMs": 4667, "durMs": 2000, "startTick": 3360, "durTicks": 1440, "numerator": 6,
         "denominator": 8, "pickup": False, **meter},
    ]


def test_bars_table_tiles_and_expands_multirest() -> None:
    sys1 = _all_voices([CLEF, *M34, "digit.3-S5", "multirest-L3", BAR, Q, Q, Q, BAR], sys_idx=1)
    sys2 = _all_voices([CLEF, Q, Q, Q, BAR], sys_idx=2)
    _, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    table = s5.build_bars_table(report, BPM)
    assert [b["bar"] for b in table] == [1, 2, 3, 4, 5]
    assert [b["meterSource"] for b in table] == ["detected"] * 4 + ["inherited"]
    for prev, cur in zip(table, table[1:]):
        assert cur["startTick"] == prev["startTick"] + prev["durTicks"]
        assert cur["startMs"] == prev["startMs"] + prev["durMs"]
    assert table[0]["startTick"] == 0 and not any(b["pickup"] for b in table)


# ── Failed voices (PIYA-108 AC4/AC5, PIYA-109 AC9, PIYA-103 AC10) ──────────────

def _stub_render(monkeypatch: pytest.MonkeyPatch, fail: set[str] = frozenset()) -> None:
    def render(midi_path: Path, wav_path: Path, mp3_path: Path, soundfont_path: str) -> bool:
        if Path(mp3_path).stem.capitalize() in fail:
            return False
        Path(mp3_path).write_bytes(b"ID3")
        return True
    monkeypatch.setattr(s5, "_render_to_mp3", render)


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, voice_events: dict) -> dict[str, Any]:
    monkeypatch.setattr(s3, "run_stages_1_to_3", lambda *a, **k: voice_events)
    return s5.run_full_pipeline_with_report(output_dir=str(tmp_path), clef_key_weights=None, bpm=BPM)


def test_one_empty_voice_completes_with_failed_voices(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    _stub_render(monkeypatch)
    ve = _all_voices(PLAIN, Alto=OVERFULL)
    ve["Tenor"] = []
    with pytest.warns(RuntimeWarning, match="Tenor"):
        result = _run(monkeypatch, tmp_path, ve)
    assert result["failedVoices"] == ["tenor"]
    assert set(result["audio"]) == {"Soprano", "Alto", "Bass"}
    assert "voice_failed" in result["review"]["reasons"]
    assert {"code": "voice_failed", "voice": "tenor", "pageIndex": None, "systemIndex": None,
            "bar": None} in result["review"]["items"]
    assert [m["voice"] for m in result["mutedMeasures"]] == ["alto"]
    assert result["review"]["reviewNeeded"] is True
    assert [b["bar"] for b in result["bars"]] == [1, 2, 3]


def test_render_failure_is_a_failed_voice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_render(monkeypatch, fail={"Alto"})
    result = _run(monkeypatch, tmp_path, _all_voices(PLAIN, Alto=OVERFULL))
    assert result["failedVoices"] == ["alto"] and "Alto" not in result["audio"]
    assert result["mutedMeasures"] == [], "a failed voice has no mutedMeasures entries"


def test_nothing_failed_or_muted_gives_empty_lists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_render(monkeypatch)
    result = _run(monkeypatch, tmp_path, _all_voices(PLAIN))
    assert result["failedVoices"] == [] and result["mutedMeasures"] == []
    assert len(result["audio"]) == 4


def test_all_four_empty_raises() -> None:
    with pytest.raises(ValueError, match="^incomplete_voice_sequence: ") as err:
        s4.reconstruct_satb_with_report({v: [] for v in VOICES})
    assert isinstance(err.value, s4.PipelineFailure)
    assert err.value.failure_reason == s4.FAILURE_INCOMPLETE_VOICE_SEQUENCE == "incomplete_voice_sequence"


def test_all_four_empty_through_the_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_render(monkeypatch)
    with pytest.raises(s4.PipelineFailure) as err:
        _run(monkeypatch, tmp_path, {v: [] for v in VOICES})
    assert err.value.failure_reason == "incomplete_voice_sequence"


def test_all_four_render_failures_are_synthesis_failed(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    # Every voice had events, so this is a server-side rendering fault, not a capture problem.
    _stub_render(monkeypatch, fail=set(VOICES))
    with pytest.raises(s4.PipelineFailure) as err:
        _run(monkeypatch, tmp_path, _all_voices(PLAIN))
    assert err.value.failure_reason == s5.FAILURE_SYNTHESIS == "synthesis_failed"


def test_empty_plus_render_failures_are_synthesis_failed(monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    _stub_render(monkeypatch, fail={"Soprano", "Alto", "Tenor"})
    ve = _all_voices(PLAIN)
    ve["Bass"] = []
    with pytest.warns(RuntimeWarning), pytest.raises(s4.PipelineFailure) as err:
        _run(monkeypatch, tmp_path, ve)
    assert err.value.failure_reason == "synthesis_failed"


def test_muted_span_is_silent_in_the_midi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rendered: dict[str, list] = {}
    real_build = s5.build_voice_midi

    def spy(events: list, bpm: int, total_ticks: int):  # noqa: ANN202 - midiutil type
        rendered[events[0]["voice"]] = events
        return real_build(events, bpm, total_ticks)
    monkeypatch.setattr(s5, "build_voice_midi", spy)
    _stub_render(monkeypatch)
    _run(monkeypatch, tmp_path, _all_voices(PLAIN, Alto=OVERFULL))
    alto_notes = [e for e in rendered["Alto"] if e["type"] == "note"]
    assert not [e for e in alto_notes if WHOLE <= e["tick_onset"] < 2 * WHOLE]
    assert all(e["tick_onset"] + e["duration_ticks"] <= WHOLE or e["tick_onset"] >= 2 * WHOLE
               for e in alto_notes)
    sop = [e for e in rendered["Soprano"] if e["type"] == "note"]
    assert len([e for e in sop if WHOLE <= e["tick_onset"] < 2 * WHOLE]) == 4, "other voices unaffected"


# ── Review round 2026-10-09 ────────────────────────────────────────────────────

def _notes(out: list[dict]) -> list[tuple[int, int]]:
    return [(e["tick_onset"], e["duration_ticks"]) for e in out if e["type"] == "note"]


def test_tie_out_of_a_muted_bar_is_restruck_in_the_clean_bar() -> None:
    # A tie-merged note starting at beat 3 of muted bar 2 and held into bar 3 still sounds in bar 3.
    out = s5.apply_muted_spans([_note(WHOLE + 2 * QUARTER, WHOLE)], [(WHOLE, 2 * WHOLE)])
    assert _notes(out) == [(2 * WHOLE, 2 * QUARTER)]
    assert out[0]["restruck_after_mute"] is True


def test_note_across_a_whole_muted_bar_plays_both_ends() -> None:
    out = s5.apply_muted_spans([_note(2 * QUARTER, 2 * WHOLE)], [(WHOLE, 2 * WHOLE)])
    assert _notes(out) == [(2 * QUARTER, WHOLE - 2 * QUARTER), (2 * WHOLE, 2 * QUARTER)]
    assert "restruck_after_mute" not in out[0] and out[1]["restruck_after_mute"] is True


def test_restruck_remainder_is_clipped_against_later_spans() -> None:
    spans = [(3 * WHOLE, 4 * WHOLE), (WHOLE, 2 * WHOLE)]          # unsorted on purpose
    out = s5.apply_muted_spans([_note(WHOLE + QUARTER, 3 * WHOLE)], spans)
    assert _notes(out) == [(2 * WHOLE, WHOLE), (4 * WHOLE, QUARTER)]


def test_note_fully_inside_a_span_is_still_dropped() -> None:
    out = s5.apply_muted_spans([_note(WHOLE, QUARTER), _note(WHOLE + QUARTER, 3 * QUARTER)],
                               [(WHOLE, 2 * WHOLE)])
    assert _notes(out) == []


def test_meter_change_read_by_one_of_four_is_not_applied() -> None:
    # Continuation system: only Soprano reads 3/4 (a misread); the bars really hold four quarters.
    sys1 = _all_voices([CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR], sys_idx=1)
    sys2 = _all_voices([CLEF, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR], sys_idx=2,
                       Soprano=[CLEF, *M34, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR])
    satb, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    assert [ts for _, ts, _ in _bar_layout(report)] == ["4/4"] * 4
    single = [f for f in report["flags"] if f["kind"] == s4.FLAG_METER_CHANGE_MINORITY]
    assert len(single) == 1 and single[0]["review_needed"] is True
    assert (single[0]["bar"], single[0]["bar_end"], single[0]["sys_idx"]) == (3, 4, 2)
    assert [f["kind"] for f in report["flags"]] == [s4.FLAG_METER_CHANGE_MINORITY], "no voice repaired"
    assert not any(f.get("muted") for f in report["flags"])
    assert all(len([e for e in satb[v] if e["type"] == "note"]) == 16 for v in VOICES)


def test_meter_change_by_all_voices_is_applied() -> None:
    sys1 = _all_voices([CLEF, *M44, Q, Q, Q, Q, BAR], sys_idx=1)
    sys2 = _all_voices([CLEF, *M34, Q, Q, Q, BAR], sys_idx=2)
    _, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    assert [ts for _, ts, _ in _bar_layout(report)] == ["4/4", "3/4"]
    assert not [f for f in report["flags"] if f["kind"] == s4.FLAG_METER_CHANGE_MINORITY]


def test_meter_disagreement_is_one_item_per_run() -> None:
    agree = [CLEF, *M44] + [Q, Q, Q, Q, BAR] * 4
    odd = [CLEF, *M44, Q, Q, Q, Q, BAR, *M34, Q, Q, Q, BAR, Q, Q, Q, BAR, Q, Q, Q, BAR]
    _, report = s4.reconstruct_satb_with_report(_all_voices(agree, Soprano=odd))
    dis = [f for f in report["flags"] if f["kind"] == s4.FLAG_METER_DISAGREEMENT]
    assert len(dis) == 1
    assert (dis[0]["bar"], dis[0]["bar_end"], dis[0]["system_bar_rank"]) == (2, 4, 1)


def test_local_mode_mutes_from_the_first_trimmed_note() -> None:
    # Alto lost a barline (2 bars vs 3), so it is placed by local ticks; its last half note crosses the
    # system end (trimmed) and the next one starts after it (dropped). Real code path, no monkeypatch.
    alto = [CLEF, *M44, Q, Q, Q, Q, Q, Q, Q, Q, BAR, Q, Q, Q, H, H, BAR]
    _, report = s4.reconstruct_satb_with_report(_all_voices(PLAIN, Alto=alto))
    over = [f for f in report["flags"] if f["kind"] == s4.FLAG_LOCAL_OVERRUN]
    assert len(over) == 1 and over[0]["muted"] is True
    assert (over[0]["start_tick"], over[0]["end_tick"]) == (11 * QUARTER, 3 * WHOLE)
    muted = s5.build_muted_measures(report["flags"], BPM, [])
    assert [(m["voice"], m["reason"], m["bar"]) for m in muted] == [("alto", "local_placement_overrun", None)]


def test_local_mode_shortened_rest_is_never_muted() -> None:
    alto = [CLEF, *M44, Q, Q, Q, Q, Q, Q, Q, Q, BAR, Q, Q, Q, "rest.half-L3", BAR]
    _, report = s4.reconstruct_satb_with_report(_all_voices(PLAIN, Alto=alto))
    assert not any(f.get("muted") for f in report["flags"])
    assert s5.build_muted_measures(report["flags"], BPM, []) == []


def test_trimmed_head_to_pickup_carries_a_span() -> None:
    # Real code path: three voices agree on a quarter pickup, Alto reads two quarters.
    _, report = s4.reconstruct_satb_with_report(
        _all_voices([CLEF, *M44, Q, BAR, Q, Q, Q, Q, BAR], Alto=[CLEF, *M44, Q, Q, BAR, Q, Q, Q, Q, BAR]))
    trimmed = [f for f in report["flags"] if f.get("action") == s4.ACTION_TRIMMED_PICKUP]
    assert len(trimmed) == 1 and trimmed[0]["voice"] == "Alto"
    assert trimmed[0]["muted"] is True and (trimmed[0]["start_tick"], trimmed[0]["end_tick"]) == (0, QUARTER)
    muted = s5.build_muted_measures(report["flags"], BPM, [])
    assert [(m["voice"], m["bar"], m["startMs"], m["endMs"]) for m in muted] == [("alto", 0, 0, 667)]


def test_real_clip_with_no_drops_is_not_muted() -> None:
    # H Q H overflows by a quarter with no run to rescale: the last half is trimmed, nothing dropped.
    alto = [CLEF, *M44, Q, Q, Q, Q, BAR, H, Q, H, BAR, Q, Q, Q, Q, BAR]
    _, report = s4.reconstruct_satb_with_report(_all_voices(PLAIN, Alto=alto))
    clipped = [f for f in report["flags"] if f["kind"] == "bar_overflow_clipped"]
    assert len(clipped) == 1 and not clipped[0].get("muted")
    assert s5.build_muted_measures(report["flags"], BPM, []) == []


def test_mid_measure_meter_is_flagged_not_applied() -> None:
    for meter in (M34, ["metersign.C/-L3"]):
        events = _events([CLEF, *M44, Q, Q, *meter, Q, Q, BAR, Q, Q, Q, Q, BAR])
        assert {e["time_signature"] for e in events} == {"4/4"}
        assert all(s3.METER_FLAG_MID_MEASURE in e["meter_flags"] for e in events)


def test_meter_right_after_a_barline_is_applied() -> None:
    events = _events([CLEF, *M44, Q, Q, Q, Q, BAR, *M34, Q, Q, Q, BAR])
    assert [e["time_signature"] for e in events] == ["4/4"] * 4 + ["3/4"] * 3
    assert not any(e.get("meter_flags") for e in events)


def test_pickup_row_uses_the_opening_meter() -> None:
    _, report = s4.reconstruct_satb_with_report(_all_voices([CLEF, *M34, Q, BAR, *M44, Q, Q, Q, Q, BAR]))
    table = s5.build_bars_table(report, BPM)
    assert (table[0]["pickup"], table[0]["numerator"], table[0]["denominator"]) == (True, 3, 4)
    assert (table[1]["bar"], table[1]["numerator"], table[1]["denominator"]) == (1, 4, 4)


def test_whole_rest_pickup_is_the_pickup_length() -> None:
    # Bass is silent through the anacrusis, engraved as a whole rest in the pickup bar.
    sat = [CLEF, *M44, Q, BAR, Q, Q, Q, Q, BAR, Q, Q, Q, BAR]
    bass = [CLEF, *M44, "rest.whole-L4", BAR, Q, Q, Q, Q, BAR, Q, Q, Q, BAR]
    satb, report = s4.reconstruct_satb_with_report(_all_voices(sat, Bass=bass))
    assert report["pickup_ticks"] == QUARTER
    assert [(e["type"], e["tick_onset"], e["duration_ticks"]) for e in satb["Bass"][:2]] == [
        ("rest", 0, QUARTER), ("note", QUARTER, QUARTER)]
    bass_kinds = {f["kind"] for f in report["flags"] if f.get("voice") == "Bass"}
    assert not bass_kinds & {"pickup_length_mismatch", "bar_count_mismatch", "local_placement_overrun"}
    assert not any(f.get("muted") for f in report["flags"])
    info = [f for f in report["flags"] if f["kind"] == s4.FLAG_WHOLE_REST_PICKUP]
    assert len(info) == 1 and info[0]["voice"] == "Bass" and info[0]["review_needed"] is False


def test_review_items_put_failed_then_muted_first() -> None:
    other = {"kind": "bar_underfull", "voice": "Soprano", "page_index": 1, "sys_idx": 1, "bar": 1,
             "review_needed": True}
    muted = [{"kind": "bar_overflow_clipped", "voice": v, "page_index": 1, "sys_idx": 1, "bar": 2,
              "muted": True, "start_tick": WHOLE, "end_tick": 2 * WHOLE, "review_needed": True}
             for v in ("Bass", "Alto")]
    many_others = [dict(other, bar=b) for b in range(1, s5.REVIEW_ITEMS_CAP + 5)]
    review, full = s5.build_review({}, many_others + muted, ["tenor"])
    assert [i["code"] for i in review["items"][:3]] == ["voice_failed", "bar_overflow_clipped",
                                                        "bar_overflow_clipped"]
    assert [i["voice"] for i in review["items"][1:3]] == ["alto", "bass"], "mutedMeasures order"
    assert review["truncated"] is True and len(review["items"]) == s5.REVIEW_ITEMS_CAP
    assert len(full) == len(many_others) + 3


def test_bars_table_short_final_bar() -> None:
    _, report = s4.reconstruct_satb_with_report(_all_voices([CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, BAR]))
    table = s5.build_bars_table(report, BPM)
    assert [(b["bar"], b["startTick"], b["durTicks"]) for b in table] == [(1, 0, WHOLE), (2, WHOLE, 2 * QUARTER)]
    assert table[-1]["durMs"] == 1333 and (table[-1]["numerator"], table[-1]["denominator"]) == (4, 4)


def test_bars_table_refuses_drift() -> None:
    sys1 = _all_voices([CLEF, *M44, Q, Q, Q, Q, BAR], sys_idx=1)
    sys2 = _all_voices([CLEF, Q, Q, Q, Q, BAR], sys_idx=2)
    _, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    report["systems"][1]["start_tick"] += QUARTER
    with pytest.raises(s4.PipelineFailure, match="^internal_error: bars table drift") as err:
        s5.build_bars_table(report, BPM)
    assert err.value.failure_reason == s5.FAILURE_INTERNAL_ERROR == "internal_error"


def test_meter_flags_reach_review_items(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_render(monkeypatch)
    orphan = [CLEF, *M44, "digit.3-S5", Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR, Q, Q, Q, Q, BAR]
    result = _run(monkeypatch, tmp_path, _all_voices(PLAIN, sys_idx=2, Tenor=orphan))
    assert {"code": "multirest_count_orphaned", "voice": "tenor", "pageIndex": 0, "systemIndex": 1,
            "bar": None} in result["review"]["items"]


def test_eventless_strip_meter_flags_reach_review(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    flags_out: list[str] = []
    assert s3.infer_pitch([CLEF, "digit.3-L4"], voice="Alto", page_index=1, sys_idx=1,
                          meter_flags_out=flags_out) == []
    assert flags_out == [s3.METER_FLAG_UNPAIRED_DIGIT]
    _stub_render(monkeypatch)

    def stages(*a: Any, **k: Any) -> dict:
        k["strip_flags_out"].append({"voice": "Alto", "page_index": 2, "sys_idx": 3,
                                     "meter_flags": flags_out})
        return _all_voices(PLAIN)
    monkeypatch.setattr(s3, "run_stages_1_to_3", stages)
    result = s5.run_full_pipeline_with_report(output_dir=str(tmp_path), clef_key_weights=None, bpm=BPM)
    assert {"code": "meter_digit_unpaired", "voice": "alto", "pageIndex": 1, "systemIndex": 2,
            "bar": None} in result["review"]["items"]


# ── Review round 3 (senior-reviewer / backend-lead 2026-10-14) ─────────────────

def test_meter_change_read_by_two_with_two_silent_is_applied() -> None:
    # Tenor/Bass read no meter in system 2 (no vote, not a vote against): 2 of 2 readers is a majority.
    sys1 = _all_voices([CLEF, *M44, Q, Q, Q, Q, BAR], sys_idx=1)
    sys2 = _all_voices([CLEF, *M34, Q, Q, Q, BAR, Q, Q, Q, BAR], sys_idx=2,
                       Tenor=[CLEF, Q, Q, Q, BAR, Q, Q, Q, BAR], Bass=[CLEF, Q, Q, Q, BAR, Q, Q, Q, BAR])
    satb, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    assert [ts for _, ts, _ in _bar_layout(report)] == ["4/4", "3/4", "3/4"]
    assert not [f for f in report["flags"] if f["kind"] == s4.FLAG_METER_CHANGE_MINORITY]
    assert not any(f.get("muted") for f in report["flags"])
    assert all(len([e for e in satb[v] if e["type"] == "note"]) == 10 for v in VOICES)


def test_meter_change_read_by_one_voice_inside_others_multirest_is_rejected() -> None:
    # Bar 3: Soprano reads 3/4 while the other three sit in a 2-bar multirest. One read is not enough.
    rest2 = [CLEF, "digit.2-S5", "multirest-L3", BAR]
    sys1 = _all_voices([CLEF, *M44, Q, Q, Q, Q, BAR], sys_idx=1)
    sys2 = _all_voices(rest2, sys_idx=2, Soprano=[CLEF, Q, Q, Q, Q, BAR, *M34, Q, Q, Q, BAR])
    _, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    assert [ts for _, ts, _ in _bar_layout(report)] == ["4/4"] * 3
    minority = [f for f in report["flags"] if f["kind"] == s4.FLAG_METER_CHANGE_MINORITY]
    assert len(minority) == 1 and minority[0]["bar"] == 3


def test_meter_change_in_a_one_voice_system_is_applied() -> None:
    sys1 = _all_voices([CLEF, *M44, Q, Q, Q, Q, BAR], sys_idx=1)
    sys2 = {v: [] for v in VOICES}
    sys2["Soprano"] = _events([CLEF, *M34, Q, Q, Q, BAR], "Soprano", 1, 2)
    _, report = s4.reconstruct_satb_with_report(_merge(sys1, sys2))
    assert [ts for _, ts, _ in _bar_layout(report)] == ["4/4", "3/4"]
    assert not [f for f in report["flags"] if f["kind"] == s4.FLAG_METER_CHANGE_MINORITY]


def test_pickup_trim_that_drops_only_a_rest_is_not_muted() -> None:
    # Alto's first bar is a quarter rest + the pickup quarter: trimming to the pickup loses only the rest.
    _, report = s4.reconstruct_satb_with_report(_all_voices(
        [CLEF, *M44, Q, BAR, Q, Q, Q, Q, BAR],
        Alto=[CLEF, *M44, "rest.quarter-L3", Q, BAR, Q, Q, Q, Q, BAR]))
    trimmed = [f for f in report["flags"] if f.get("action") == s4.ACTION_TRIMMED_PICKUP]
    assert len(trimmed) == 1 and trimmed[0]["voice"] == "Alto"
    assert not trimmed[0].get("muted") and "start_tick" not in trimmed[0]
    assert s5.build_muted_measures(report["flags"], BPM, []) == []


def test_pipeline_failure_pickles() -> None:
    import pickle
    err = pickle.loads(pickle.dumps(s4.PipelineFailure("synthesis_failed", "all four voices failed")))
    assert isinstance(err, s4.PipelineFailure) and isinstance(err, ValueError)
    assert err.failure_reason == "synthesis_failed"
    assert str(err) == "synthesis_failed: all four voices failed"


def test_muted_measures_and_review_items_share_tick_then_satb_order() -> None:
    def muted(voice: str, tick: int) -> dict:
        return {"kind": "bar_overflow_clipped", "voice": voice, "page_index": 1, "sys_idx": 1, "bar": 2,
                "review_needed": True, "muted": True, "start_tick": tick, "end_tick": tick + WHOLE}
    # Out of order on purpose. Bass and Soprano share a tick. At 240 bpm ticks 1 and 2 both round to
    # 1 ms, so Tenor (tick 1) must still precede Alto (tick 2): ordering by ms would flip them.
    fast_bpm = 240
    assert s5.tick_to_ms(1, fast_bpm) == s5.tick_to_ms(2, fast_bpm)
    flags = [muted("Alto", 2), muted("Bass", WHOLE), muted("Soprano", WHOLE), muted("Tenor", 1)]
    mm = s5.build_muted_measures(flags, fast_bpm, [])
    review, _ = s5.build_review({}, flags)
    order = [("tenor", 1), ("alto", 2), ("soprano", WHOLE), ("bass", WHOLE)]
    assert [m["voice"] for m in mm] == [v for v, _ in order]
    assert [i["voice"] for i in review["items"]] == [v for v, _ in order]


def test_two_note_chord_is_split_identically() -> None:
    chord = [{**_note(WHOLE + 2 * QUARTER, WHOLE, 60), "chord_id": 7},
             {**_note(WHOLE + 2 * QUARTER, WHOLE, 64), "chord_id": 7}]
    out = s5.apply_muted_spans(chord, [(WHOLE, 2 * WHOLE)])
    assert len(out) == 2, "each member keeps only its restruck tail"
    assert [(e["pitch"], e["tick_onset"], e["duration_ticks"], e["restruck_after_mute"]) for e in out] == [
        (60, 2 * WHOLE, 2 * QUARTER, True), (64, 2 * WHOLE, 2 * QUARTER, True)]
    split = s5.apply_muted_spans(chord, [(WHOLE + 3 * QUARTER, 2 * WHOLE)])
    assert len(split) == 4, "a split adds events: build timing from the pre-mute satb"
    assert sorted((e["pitch"], e["tick_onset"], e["duration_ticks"]) for e in split) == [
        (60, WHOLE + 2 * QUARTER, QUARTER), (60, 2 * WHOLE, 2 * QUARTER),
        (64, WHOLE + 2 * QUARTER, QUARTER), (64, 2 * WHOLE, 2 * QUARTER)]


def test_courtesy_meter_pair_at_strip_end_is_not_mid_measure() -> None:
    # A courtesy 3/4 after the strip's last notes (no closing barline) announces the next system.
    flags: list[str] = []
    s3.infer_pitch([CLEF, *M44, Q, Q, Q, Q, BAR, Q, Q, *M34], voice="Soprano", page_index=1, sys_idx=1,
                   meter_flags_out=flags)
    assert s3.METER_FLAG_MID_MEASURE not in flags
    flags.clear()
    s3.infer_pitch([CLEF, *M44, Q, Q, *M34, Q, Q, BAR], voice="Soprano", page_index=1, sys_idx=1,
                   meter_flags_out=flags)
    assert s3.METER_FLAG_MID_MEASURE in flags


def test_process_strip_reports_flags_of_an_eventless_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np
    import torch
    tokens = {"empty": [CLEF, "digit.3-L4"], "full": [CLEF, *M44, "digit.3-S5", Q, Q, Q, Q, BAR]}
    monkeypatch.setattr(s3, "transcribe_strip",
                        lambda strip, *a, strip_id="", **k: [(t, 0.99) for t in tokens[strip_id]])
    out: list[dict] = []
    strip = np.zeros((64, 64), dtype=np.uint8)
    ev = s3.process_strip(strip, "Tenor", 2, None, torch.device("cpu"), sys_idx=3, strip_id="empty",
                          strip_flags_out=out)
    assert ev == []
    assert out == [{"voice": "Tenor", "page_index": 2, "sys_idx": 3,
                    "meter_flags": [s3.METER_FLAG_UNPAIRED_DIGIT]}]
    ev = s3.process_strip(strip, "Tenor", 2, None, torch.device("cpu"), sys_idx=3, strip_id="full",
                          strip_flags_out=out)
    assert ev and len(out) == 1, "flags of a strip with events ride on its events"
