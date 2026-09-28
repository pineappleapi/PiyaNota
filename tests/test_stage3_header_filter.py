"""Tests for Stage 3's header-zone hallucination filter (PIYA-106, docs/decisions/piya-106-ser-15-plan.md, E1c).

The CRNN copies Camera-PrIMuS's clef + key + time-signature opening onto continuation systems; the filter drops
those tokens unless the system's voices agree on them (choral-conductor review, 2026-09-29).

Run with ``python tests/test_stage3_header_filter.py``. Synthetic tests: they say nothing about accuracy.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage5_synthesis as s5  # noqa: E402
from stage3_transcription import (HEADER_METER_CHANGE_FLAG, HEADER_QUORUM,  # noqa: E402
                                   filter_header_hallucinations)

VOICES = ("Soprano", "Alto", "Tenor", "Bass")
BODY = ["note.quarter-L2", "barline-L1", "note.half-S3"]
METER_44 = ("digit.4-S5", "digit.4-S3")
METER_34 = ("digit.3-S5", "digit.4-S3")


def _system(per_voice: dict[str, list[str]]) -> dict[str, tuple[str, list]]:
    return {f"s_{v}": (v, toks) for v, toks in per_voice.items()}


def _kept(system: dict[str, tuple[str, list]], keep: dict[str, list[int]], voice: str) -> list[str]:
    syms = system[f"s_{voice}"][1]
    return [syms[i] for i in keep[f"s_{voice}"]]


def test_first_system_untouched_and_sets_running_meter() -> None:
    toks = ["clef.G-L2", *METER_34, "fermata.above-S6", *BODY]
    system = _system({v: list(toks) for v in VOICES})
    keep, flags, running = filter_header_hallucinations(system, {}, is_first_system=True)
    for v in VOICES:
        assert _kept(system, keep, v) == toks
        assert flags[f"s_{v}"] == []
        assert running[v] == METER_34


def test_lone_time_signature_dropped_on_continuation() -> None:
    system = _system({"Soprano": ["clef.G-L2", *METER_34, *BODY], "Alto": ["clef.G-L2", *BODY],
                      "Tenor": ["clef.G-L2", *BODY], "Bass": ["clef.F-L4", *BODY]})
    keep, flags, running = filter_header_hallucinations(system, {v: METER_44 for v in VOICES}, False)
    assert _kept(system, keep, "Soprano") == ["clef.G-L2", *BODY]
    assert flags["s_Soprano"] == [] and running["Soprano"] == METER_44


def test_time_signature_after_first_barline_is_body_and_kept() -> None:
    toks = ["clef.G-L2", "note.quarter-L2", "barline-L1", *METER_34, "note.half-S3"]
    system = _system({"Soprano": toks, "Alto": BODY, "Tenor": BODY, "Bass": BODY})
    keep, _, _ = filter_header_hallucinations(system, {}, False)
    assert _kept(system, keep, "Soprano") == toks


def test_quorum_meter_change_kept_flagged_once() -> None:
    per = {v: ["clef.G-L2", *METER_34, *BODY] for v in VOICES[:HEADER_QUORUM]}
    per["Bass"] = ["clef.F-L4", *BODY]
    system = _system(per)
    keep, flags, running = filter_header_hallucinations(system, {v: METER_44 for v in VOICES}, False)
    assert _kept(system, keep, "Soprano") == ["clef.G-L2", *METER_34, *BODY]
    assert flags["s_Soprano"] == [HEADER_METER_CHANGE_FLAG, "review_needed"]
    # A meter change is system-wide: the voice that missed it moves too, and is flagged for review.
    assert flags["s_Bass"] == [HEADER_METER_CHANGE_FLAG, "review_needed"]
    assert running["Soprano"] == METER_34 and running["Bass"] == METER_34
    # The same meter on the next system is the running meter again: dropped, not re-flagged.
    keep2, flags2, _ = filter_header_hallucinations(system, running, False)
    assert _kept(system, keep2, "Soprano") == ["clef.G-L2", *BODY]
    assert flags2["s_Soprano"] == []


def test_dissenting_meter_dropped_when_quorum_accepts_another() -> None:
    per = {v: ["clef.G-L2", *METER_34, *BODY] for v in VOICES[:HEADER_QUORUM]}
    per["Bass"] = ["clef.F-L4", "digit.6-S5", "digit.8-S3", *BODY]
    system = _system(per)
    keep, flags, running = filter_header_hallucinations(system, {v: METER_44 for v in VOICES}, False)
    assert _kept(system, keep, "Bass") == ["clef.F-L4", *BODY]
    assert flags["s_Bass"] == [HEADER_METER_CHANGE_FLAG, "review_needed"] and running["Bass"] == METER_34


def test_meter_matching_running_meter_is_dropped() -> None:
    system = _system({v: ["clef.G-L2", *METER_44, *BODY] for v in VOICES})
    keep, flags, _ = filter_header_hallucinations(system, {v: METER_44 for v in VOICES}, False)
    for v in VOICES:
        assert _kept(system, keep, v) == ["clef.G-L2", *BODY] and flags[f"s_{v}"] == []


def test_multirest_with_digits_kept_at_quorum_dropped_below() -> None:
    mr = ["clef.G-L2", "multirest-L3", "digit.8-S5", "barline-L1", "note.half-S3"]
    at_quorum = _system({v: list(mr) for v in VOICES[:HEADER_QUORUM]} | {"Bass": ["clef.F-L4", *BODY]})
    keep, flags, _ = filter_header_hallucinations(at_quorum, {}, False)
    assert _kept(at_quorum, keep, "Soprano") == mr and flags["s_Soprano"] == []
    below = _system({"Soprano": list(mr)} | {v: ["clef.G-L2", *BODY] for v in VOICES[1:]})
    keep, _, _ = filter_header_hallucinations(below, {}, False)
    # The multirest's digit is its bar count, so it goes with it and is not read as a time signature.
    assert _kept(below, keep, "Soprano") == ["clef.G-L2", "barline-L1", "note.half-S3"]


def test_fermata_dropped_only_before_first_note() -> None:
    # Known limit: Stage 3 emits a fermata before its note, so a real fermata on a system's first note is dropped
    # too. No stage plays fermatas yet (choral-conductor, 2026-09-29).
    toks = ["clef.G-L2", "fermata.above-S6", "note.quarter-L2", "fermata.above-S6", "barline-L1"]
    system = _system({"Soprano": toks, "Alto": BODY, "Tenor": BODY, "Bass": BODY})
    keep, _, _ = filter_header_hallucinations(system, {}, False)
    assert keep["s_Soprano"] == [0, 2, 3, 4]


def test_keep_indices_filter_confidences_in_parallel() -> None:
    toks = ["clef.G-L2", *METER_34, "fermata.above-S6", *BODY]
    confs = [0.1 * i for i in range(len(toks))]
    system = _system({"Soprano": toks, "Alto": BODY, "Tenor": BODY, "Bass": BODY})
    keep, _, _ = filter_header_hallucinations(system, {}, False)
    kept = [(toks[i], confs[i]) for i in keep["s_Soprano"]]
    assert kept == [(t, confs[toks.index(t)]) for t in ["clef.G-L2", *BODY]]


def test_build_review_lists_header_meter_change() -> None:
    ev = {"voice": "Alto", "page_index": 2, "sys_idx": 3, "clef_key_flags": [], "clef_key_strip_flags": [],
          "header_flags": [HEADER_METER_CHANGE_FLAG, "review_needed"], "review_needed": True}
    review, full = s5.build_review({"Alto": [ev, dict(ev)]}, [])
    assert review["reviewNeeded"] is True and HEADER_METER_CHANGE_FLAG in review["reasons"]
    assert full == [{"code": HEADER_METER_CHANGE_FLAG, "voice": "alto", "pageIndex": 2, "systemIndex": 3,
                     "bar": None}]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"PASS {name}")
    print(f"{len(tests)} passed")
