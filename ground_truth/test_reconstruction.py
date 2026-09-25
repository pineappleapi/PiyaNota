"""Regression tests for Stage 4 reconstruction and Stage 5 MIDI generation.

Run with plain ``python ground_truth/test_reconstruction.py`` (pytest also works).
No GPU is used; the Stage 3 token test imports torch on CPU only.

WHAT THIS DOES AND DOES NOT SHOW
    * Case A feeds the hand-authored ``dont_stop_me_now`` ground truth (page 1,
      system 1) through Stage 4/5. Those events were authored by one person,
      unreviewed by a second, and cover one system, so they exercise
      alignment / chord / tie / pickup *logic*. They are NOT evidence of
      recognition accuracy and no accuracy figure may be derived from this file.
    * Cases B-D are synthetic and only assert structural invariants.
    * Nothing here evaluates the CRNN; the events never touch a model.
"""

import copy
import json
import os
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")  # BUG-013: never touch the GPU
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import stage4_reconstruction as s4  # noqa: E402
import stage5_synthesis as s5  # noqa: E402

GT_DIR = Path(__file__).resolve().parent / "dont_stop_me_now"
VOICES = ["Soprano", "Alto", "Tenor", "Bass"]
WHOLE = 1920
HALF, QUARTER, EIGHTH = 960, 480, 240
TENOR_G4_SOUNDING = 55  # written G4, sounds an octave lower (Tenor 8vb)
MIDI_TRACK_INDEX = 1    # midiutil MIDIFile(1) writes a tempo track, then the voice


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_ground_truth() -> dict:
    return {v: json.loads((GT_DIR / f"{v.lower()}_events.json").read_text(encoding="utf8"))
            for v in VOICES}


def make_strip(voice: str, sys_idx: int, bars: list, first_measure_index: int = 1,
               time_signature: str = "4/4", page_index: int = 1) -> list:
    """Stage 3-shaped events. bars: list of bars; a bar is a list of
    (pitch_or_None, duration_ticks[, extras_dict]). Ticks run on across bars,
    exactly as Stage 3's single running current_tick does."""
    events, tick = [], 0
    for offset, bar in enumerate(bars):
        for item in bar:
            pitch, dur = item[0], item[1]
            extras = item[2] if len(item) > 2 else {}
            events.append({
                "type": "rest" if pitch is None else "note", "pitch": pitch,
                "duration_ticks": dur, "voice": voice, "page_index": page_index,
                "sys_idx": sys_idx, "chord_id": None,
                "symbol": "rest.quarter" if pitch is None else "note.quarter-L3",
                "tick_onset": tick, "slur": None,
                "measure_index": first_measure_index + offset,
                "time_signature": time_signature, **extras})
            tick += dur
    return events


def notes(events: list) -> list:
    return [e for e in events if e["type"] == "note"]


def flags_of(report: dict, kind: str, voice: Optional[str] = None) -> list:
    return [f for f in report["flags"]
            if f["kind"] == kind and (voice is None or f["voice"] == voice)]


def read_midi_track(path_or_bytes: bytes, track_index: int) -> dict:
    """Minimal SMF reader (no mido in this repo): {'notes': [(on, off, pitch)],
    'end': end_of_track_tick, 'ppq': ticks_per_quarter}."""
    data = path_or_bytes
    assert data[:4] == b"MThd"
    _fmt, ntracks, ppq = struct.unpack(">HHH", data[8:14])
    pos, tracks = 14, []
    for _ in range(ntracks):
        assert data[pos:pos + 4] == b"MTrk"
        (length,) = struct.unpack(">I", data[pos + 4:pos + 8])
        tracks.append(data[pos + 8:pos + 8 + length])
        pos += 8 + length
    chunk, i, tick, status = tracks[track_index], 0, 0, 0
    open_notes: dict = {}
    result = {"notes": [], "end": 0, "ppq": ppq}

    def varint() -> int:
        nonlocal i
        value = 0
        while True:
            byte = chunk[i]
            i += 1
            value = (value << 7) | (byte & 0x7F)
            if not byte & 0x80:
                return value

    while i < len(chunk):
        tick += varint()
        if chunk[i] == 0xFF:
            meta_type = chunk[i + 1]
            i += 2
            length = varint()
            i += length
            if meta_type == 0x2F:
                result["end"] = tick
            continue
        if chunk[i] & 0x80:
            status = chunk[i]
            i += 1
        kind = status & 0xF0
        nbytes = 1 if kind in (0xC0, 0xD0) else 2
        args = chunk[i:i + nbytes]
        i += nbytes
        if kind == 0x90 and args[1] > 0:
            open_notes[args[0]] = tick
        elif kind == 0x80 or (kind == 0x90 and args[1] == 0):
            result["notes"].append((open_notes.pop(args[0]), tick, args[0]))
    return result


def midi_bytes(events: list, total_ticks: int, bpm: int = 90) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        s5.build_voice_midi(events, bpm, total_ticks).writeFile(tmp)
        name = tmp.name
    try:
        return Path(name).read_bytes()
    finally:
        os.unlink(name)


# ── Case A: hand-authored ground truth, page 1 system 1 ───────────────────────

def test_ground_truth_alignment_pickup_chord_ties() -> None:
    gt = load_ground_truth()
    snapshot = copy.deepcopy(gt)
    satb, report = s4.reconstruct_satb_with_report(gt)
    assert gt == snapshot, "Stage 4 must not mutate its input"

    # Tenor alone sings an eighth pickup while S/A/B rest through it (Stage 4 never sees
    # the empty pickup segment). Structural pre-check: Tenor has one more measure than the
    # full-first-bar reference voices and its extra ticks equal its short first bar, so the
    # pickup is accepted and everyone shares the bar-1 downbeat.
    assert report["pickup_ticks"] == EIGHTH
    assert not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    (pk,) = flags_of(report, s4.FLAG_PICKUP)
    assert pk["review_needed"] is True and "bar-count excess" in pk["detail"]
    tenor = satb["Tenor"]
    assert (tenor[0]["tick_onset"], tenor[0]["duration_ticks"]) == (0, EIGHTH)
    assert not flags_of(report, s4.FLAG_BAR_UNDERFULL) and not flags_of(report, s4.FLAG_BAR_OVERFLOW)
    for v in VOICES:
        assert min(e["tick_onset"] for e in satb[v] if e["global_bar"] == 1) == EIGHTH, v
        assert min(e["tick_onset"] for e in satb[v] if e["global_bar"] == 2) == EIGHTH + WHOLE, v
    assert report["total_ticks"] == EIGHTH + 2 * WHOLE

    # Bass F3+F2 chord: same onset, same duration, same chord_id, both kept.
    chord = [e for e in satb["Bass"] if e.get("chord_id") == 1]
    assert sorted(e["pitch"] for e in chord) == [41, 53]
    assert {e["tick_onset"] for e in chord} == {EIGHTH} and {e["duration_ticks"] for e in chord} == {WHOLE}

    # Phrase slurs (different pitches) must NOT merge or change durations.
    assert [(e["pitch"], e["duration_ticks"]) for e in notes(satb["Soprano"])] == [
        (60, QUARTER), (65, QUARTER), (67, WHOLE)]
    assert [(e["pitch"], e["duration_ticks"]) for e in notes(satb["Alto"])] == [(60, WHOLE), (62, WHOLE)]
    assert [(e["pitch"], e["duration_ticks"]) for e in satb["Bass"] if e["type"] == "note"
            and e["global_bar"] == 2] == [(45, WHOLE)]
    tenor_notes = notes(tenor)
    assert [(e["pitch"], e["duration_ticks"]) for e in tenor_notes[:3]] == [
        (TENOR_G4_SOUNDING, EIGHTH), (TENOR_G4_SOUNDING, EIGHTH), (53, QUARTER)]

    # Tenor G4~ into a system that is not authored yet: not merged, but flagged.
    dangling = flags_of(report, s4.FLAG_TIE_UNRESOLVED, "Tenor")
    assert len(dangling) == 1 and "n012" in dangling[0]["detail"]
    last = tenor_notes[-1]
    assert last["tie_to_next"] is True and last["duration_ticks"] == EIGHTH

    # note_id passes through untouched; local tick preserved next to the global one.
    assert last["note_id"].endswith("Tenor_n012") and "local_tick_onset" in last
    assert all(e.get("tie_span", 1) == 1 for v in VOICES for e in satb[v])


def test_ground_truth_stage5_midi_alignment() -> None:
    satb, report = s4.reconstruct_satb_with_report(load_ground_truth())
    total = s5._piece_end_tick(satb)
    assert total == report["total_ticks"]
    ends = set()
    for voice in VOICES:
        track = read_midi_track(midi_bytes(satb[voice], total), MIDI_TRACK_INDEX)
        assert track["ppq"] == s5.PPQ == s4.TICKS_PER_QUARTER
        ends.add(track["end"])
        expected = sorted((e["tick_onset"], e["tick_onset"] + e["duration_ticks"], e["pitch"])
                          for e in notes(satb[voice]))
        assert sorted(track["notes"]) == expected, voice
    assert ends == {total}, f"voice tracks differ in length: {ends}"

    # Soprano's whole-bar half rest keeps time: first sung note is at 240 + 960.
    sop = read_midi_track(midi_bytes(satb["Soprano"], total), MIDI_TRACK_INDEX)
    assert min(n[0] for n in sop["notes"]) == EIGHTH + HALF


# ── Case B: synthetic multi-system (pickup + cross-system ties + phrase slur) ──

def synthetic_two_systems() -> dict:
    """Sys 1: pickup measure (measure_index 0) + 2 bars. Tenor sings the eighth pickup;
    S/A/B rest through it (a rest-only first bar of the same length, as engraved).
    Sys 2: 2 bars whose LAST bar is 1680 ticks (a whole minus the pickup), so the final
    bar completes the pickup: a lone short bar against full bars would now be outvoted
    by "no pickup" (evidence scoring). make_strip stamps the default 4/4 on sys 2, as
    Stage 3 does for a continuation strip."""
    final = WHOLE - EIGHTH
    return {
        "Soprano": make_strip("Soprano", 1, [[(None, EIGHTH)], [(72, WHOLE)], [(74, HALF), (76, HALF)]], 0)
                   + make_strip("Soprano", 2, [[(77, WHOLE)], [(79, final)]], 0),
        # Alto ends sys 1 on 72 with an open slur start; sys 2 opens on 72 -> tie by inference.
        "Alto":    make_strip("Alto", 1, [[(None, EIGHTH)], [(67, WHOLE)],
                                          [(69, HALF), (72, HALF, {"slur": "start"})]], 0)
                   + make_strip("Alto", 2, [[(72, WHOLE)], [(74, final)]], 0),
        # Tenor: pickup eighth, then 2 bars, last note G4~ tied (explicitly) into sys 2.
        "Tenor":   make_strip("Tenor", 1, [[(50, EIGHTH)], [(52, WHOLE)],
                                           [(53, HALF), (55, HALF, {"tie_to_next": True})]], 0)
                   + make_strip("Tenor", 2, [[(55, WHOLE)], [(57, final)]], 0),
        "Bass":    make_strip("Bass", 1, [[(None, EIGHTH)], [(40, WHOLE)], [(43, HALF), (45, HALF)]], 0)
                   + make_strip("Bass", 2, [[(48, WHOLE)], [(50, final)]], 0),
    }


def test_synthetic_multi_system_pickup_and_ties() -> None:
    satb, report = s4.reconstruct_satb_with_report(synthetic_two_systems())

    assert report["pickup_ticks"] == EIGHTH
    # Every voice's sys-2 downbeat (global bar 3) is at pickup + 2 bars, although
    # Tenor's sys 1 has 3 written measures (pickup + 2).
    sys2_start = EIGHTH + 2 * WHOLE
    assert report["systems"][1]["start_tick"] == sys2_start
    for voice in ("Soprano", "Bass"):
        bar3 = [e for e in satb[voice] if e["global_bar"] == 3]
        assert min(e["tick_onset"] for e in bar3) == sys2_start, voice

    # Tenor: explicit tie G4~ (sys 1, bar 2) + first note of sys 2 merge across the system.
    tenor_g = [e for e in notes(satb["Tenor"]) if e["pitch"] == 55]
    assert len(tenor_g) == 1 and tenor_g[0]["duration_ticks"] == HALF + WHOLE
    assert tenor_g[0]["tie_span"] == 2 and tenor_g[0]["tie_to_next"] is False
    # the tie's far end lands exactly at the end of global bar 3 (sys-2 downbeat + one bar)
    assert tenor_g[0]["tick_onset"] + tenor_g[0]["duration_ticks"] == sys2_start + WHOLE
    # Alto: inferred cross-system tie (open slur start + same-pitch first note of next system).
    alto_72 = [e for e in notes(satb["Alto"]) if e["pitch"] == 72]
    assert [e["duration_ticks"] for e in alto_72] == [HALF + WHOLE], alto_72
    assert alto_72[0]["tick_onset"] + alto_72[0]["duration_ticks"] == sys2_start + WHOLE
    assert not flags_of(report, s4.FLAG_TIE_UNRESOLVED)

    # Global ticks never overlap within a voice (no system collides with the next).
    for voice in VOICES:
        seq = sorted(notes(satb[voice]), key=lambda e: e["tick_onset"])
        for a, b in zip(seq, seq[1:]):
            assert a["tick_onset"] + a["duration_ticks"] <= b["tick_onset"], (voice, a, b)


def test_ties_only_when_adjacent_and_same_pitch() -> None:
    def satb_with(tenor_bars: list) -> tuple:
        v = {name: make_strip(name, 1, [[(60, WHOLE)], [(60, WHOLE)]], 0) for name in VOICES}
        v["Tenor"] = make_strip("Tenor", 1, tenor_bars, 0)
        return s4.reconstruct_satb_with_report(v)

    # different pitch -> phrase slur, untouched
    satb, report = satb_with([[(60, WHOLE, {"slur": "start"})], [(62, WHOLE, {"slur": "end"})]])
    assert [e["duration_ticks"] for e in satb["Tenor"]] == [WHOLE, WHOLE]
    # same pitch, adjacent -> tie
    satb, _ = satb_with([[(60, WHOLE, {"slur": "start"})], [(60, WHOLE, {"slur": "end"})]])
    assert [e["duration_ticks"] for e in satb["Tenor"]] == [2 * WHOLE]
    # rest between -> no tie (and the explicit tie is flagged)
    satb, report = satb_with([[(60, HALF, {"tie_to_next": True}), (None, HALF)], [(60, WHOLE)]])
    assert len(notes(satb["Tenor"])) == 2 and flags_of(report, s4.FLAG_TIE_UNRESOLVED, "Tenor")
    # 3-note slur over C C D is a phrase slur even though the first two pitches match
    satb, _ = satb_with([[(60, HALF, {"slur": "start"}), (60, HALF, {"slur": "middle"})],
                         [(62, WHOLE, {"slur": "end"})]])
    assert [e["duration_ticks"] for e in notes(satb["Tenor"])] == [HALF, HALF, WHOLE]
    # chain A~A~A merges into the first note
    satb, _ = satb_with([[(60, WHOLE, {"tie_to_next": True})], [(60, WHOLE, {"tie_to_next": True})]])
    # (second bar's tie has nothing after it -> flagged, survivor keeps tie_to_next)
    assert satb["Tenor"][0]["duration_ticks"] == 2 * WHOLE and satb["Tenor"][0]["tie_to_next"] is True


# ── Case C: one voice misreads a rhythm; others must stay aligned ──────────────

def test_misread_rhythm_is_contained_and_flagged() -> None:
    v = {name: make_strip(name, 1, [[(60, WHOLE)], [(62, WHOLE)]], 0)
         + make_strip(name, 2, [[(64, WHOLE)], [(65, WHOLE)]], 0) for name in VOICES}
    # Bass loses an eighth in system 1, bar 2 (62 becomes a dotted-half + quarter run 1680 ticks)
    v["Bass"] = (make_strip("Bass", 1, [[(60, WHOLE)], [(62, WHOLE - EIGHTH)]], 0)
                 + make_strip("Bass", 2, [[(64, WHOLE)], [(65, WHOLE)]], 0))
    # Tenor gains an extra quarter in system 2, bar 1 (overflow)
    v["Tenor"] = (make_strip("Tenor", 1, [[(60, WHOLE)], [(62, WHOLE)]], 0)
                  + make_strip("Tenor", 2, [[(64, HALF), (64, HALF), (66, QUARTER)], [(65, WHOLE)]], 0))
    satb, report = s4.reconstruct_satb_with_report(v)

    for voice in VOICES:  # system 2 downbeat (bar 3) at 2 whole notes for every voice
        bar3 = [e for e in satb[voice] if e["global_bar"] == 3 and e["type"] == "note"]
        assert min(e["tick_onset"] for e in bar3) == 2 * WHOLE, voice
        assert min(e["tick_onset"] for e in satb[voice] if e["global_bar"] == 4) == 3 * WHOLE, voice
    under = flags_of(report, s4.FLAG_BAR_UNDERFULL, "Bass")
    assert len(under) == 1 and under[0]["bar"] == 2 and under[0]["actual_ticks"] == WHOLE - EIGHTH
    over = flags_of(report, s4.FLAG_BAR_OVERFLOW, "Tenor")
    assert len(over) == 1 and over[0]["bar"] == 3
    tenor_bar3 = [e for e in satb["Tenor"] if e["global_bar"] == 3]
    assert max(e["tick_onset"] + e["duration_ticks"] for e in tenor_bar3) <= 3 * WHOLE
    assert len(tenor_bar3) == 2, "note starting after the bar end is dropped, and flagged"


def test_bar_count_disagreement_falls_back_and_is_flagged() -> None:
    v = {name: make_strip(name, 1, [[(60, WHOLE)], [(62, WHOLE)]], 0) for name in VOICES}
    # Alto's barline was dropped: both whole notes land in one measure (2 bars of content, 1 measure).
    v["Alto"] = make_strip("Alto", 1, [[(60, WHOLE), (62, WHOLE)]], 0)
    satb, report = s4.reconstruct_satb_with_report(v)
    assert flags_of(report, s4.FLAG_BAR_COUNT, "Alto")
    assert [e["tick_onset"] for e in satb["Alto"]] == [0, WHOLE], "local ticks are still right here"


def test_time_signature_sets_bar_length() -> None:
    v = {name: make_strip(name, 1, [[(60, 1440)], [(62, 1440)]], 0, "3/4") for name in VOICES}
    v["Soprano"] += make_strip("Soprano", 2, [[(64, 1440)]], 0, "4/4")  # continuation default
    for name in ("Alto", "Tenor", "Bass"):
        v[name] += make_strip(name, 2, [[(64, 1440)]], 0, "4/4")
    satb, report = s4.reconstruct_satb_with_report(v)
    assert report["systems"][1]["time_signature"] == "3/4", "default 4/4 on a continuation strip must inherit"
    assert min(e["tick_onset"] for e in satb["Bass"] if e["global_bar"] == 3) == 2 * 1440
    assert report["total_ticks"] == 3 * 1440


# ── Refinements: pickup guard, overflow policy, tie span, small checks ────────

def full_bars(n: int = 2, pitch: int = 60) -> list:
    return [[(pitch, WHOLE)] for _ in range(n)]


def test_pickup_guard_accepts_valid_pickup_and_flags_confidence() -> None:
    # All four voices open on the quarter: a lone short bar among full ones is now
    # outvoted by "no pickup" (evidence scoring), so the fixture needs real consensus.
    v = {name: make_strip(name, 1, [[(60, QUARTER)], [(62, WHOLE)], [(64, WHOLE)]], 0) for name in VOICES}
    satb, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == QUARTER
    (flag,) = flags_of(report, s4.FLAG_PICKUP)
    assert not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    assert flag["review_needed"] is True, "no final bar completes it, so it is not confirmed"


def test_pickup_length_grid() -> None:
    assert s4._is_valid_pickup_length(360, WHOLE), "dotted eighth is a legal pickup"
    assert not s4._is_valid_pickup_length(100, WHOLE), "off the sixteenth grid"
    assert not s4._is_valid_pickup_length(60, WHOLE), "shorter than a sixteenth"
    assert not s4._is_valid_pickup_length(WHOLE, WHOLE), "a full bar is not a pickup"


def test_pickup_guard_rejects_bad_length_and_places_as_bar_1() -> None:
    v = {name: make_strip(name, 1, full_bars(2), 0) for name in VOICES}
    v["Soprano"] = make_strip("Soprano", 1, [[(60, 100)], [(62, WHOLE)], [(64, WHOLE)]], 0)
    satb, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == 0
    assert flags_of(report, s4.FLAG_PICKUP_SUSPECT, "Soprano")
    assert not flags_of(report, s4.FLAG_PICKUP)
    assert satb["Soprano"][0]["tick_onset"] == 0, "short bar sits at the start; no silence inserted"
    assert flags_of(report, s4.FLAG_BAR_COUNT, "Soprano"), "extra measure is still reported"


def test_pickup_final_bar_mismatch_flags_but_still_accepts() -> None:
    def four(final_bar: int) -> tuple:
        v = {n: make_strip(n, 1, [[(60, HALF)], [(62, WHOLE)], [(64, final_bar)]], 0) for n in VOICES}
        return s4.reconstruct_satb_with_report(v)

    _, ok = four(HALF)                       # HALF + HALF == one bar: a real anacrusis
    assert ok["pickup_ticks"] == HALF and not flags_of(ok, s4.FLAG_PICKUP_SUSPECT)
    assert flags_of(ok, s4.FLAG_PICKUP)[0]["review_needed"] is False
    _, bad = four(WHOLE)                     # complement missing: now a review flag, not a veto
    assert bad["pickup_ticks"] == HALF and not flags_of(bad, s4.FLAG_PICKUP_SUSPECT)
    assert flags_of(bad, s4.FLAG_PICKUP)[0]["review_needed"] is True


def pickup_voices(first_bars: dict, final: int = WHOLE - QUARTER) -> dict:
    """Each voice: a first bar of the given (pitch_or_None, ticks), a whole bar, then a
    final bar of `final` ticks (default: the complement of a quarter pickup, as in a
    real piece that ends on the bar the pickup completes)."""
    return {n: make_strip(n, 1, [[first_bars[n]], [(62, WHOLE)], [(64, final)]], 0) for n in VOICES}


def test_pickup_three_agree_one_deviant_is_quarantined() -> None:
    fb = {n: (60, QUARTER) for n in VOICES}
    fb["Bass"] = (60, EIGHTH)
    satb, report = s4.reconstruct_satb_with_report(pickup_voices(fb))
    assert report["pickup_ticks"] == QUARTER and not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    (mm,) = flags_of(report, s4.FLAG_PICKUP_MISMATCH)
    assert mm["voice"] == "Bass" and mm["review_needed"] is True
    assert flags_of(report, s4.FLAG_PICKUP)[0]["review_needed"] is True
    assert satb["Bass"][0]["tick_onset"] == QUARTER - EIGHTH, "right-aligned to the downbeat"
    assert min(e["tick_onset"] for e in satb["Bass"] if e["global_bar"] == 1) == QUARTER


def test_pickup_longer_deviant_or_invalid_length_never_sounds_before_tick_0() -> None:
    fb = {n: (60, QUARTER) for n in VOICES}
    fb["Bass"] = (60, HALF)                  # longer than the agreed pickup
    satb, report = s4.reconstruct_satb_with_report(pickup_voices(fb))
    assert report["pickup_ticks"] == QUARTER
    (mm,) = flags_of(report, s4.FLAG_PICKUP_MISMATCH, "Bass")
    assert mm["action"] == "trimmed_head_to_pickup"
    assert min(e["tick_onset"] for e in satb["Bass"]) >= 0
    assert all(e["tick_onset"] + e["duration_ticks"] <= QUARTER
               for e in satb["Bass"] if e["global_bar"] == 0)
    fb["Bass"] = (60, 100)                   # fails the length gate, still quarantined
    satb, report = s4.reconstruct_satb_with_report(pickup_voices(fb))
    assert report["pickup_ticks"] == QUARTER and flags_of(report, s4.FLAG_PICKUP_MISMATCH, "Bass")
    assert not flags_of(report, s4.FLAG_PICKUP_SUSPECT)


def test_pickup_two_sounding_voices_agree_others_silent() -> None:
    fb = {"Soprano": (60, QUARTER), "Alto": (60, QUARTER),
          "Tenor": (None, QUARTER), "Bass": (None, QUARTER)}
    satb, report = s4.reconstruct_satb_with_report(pickup_voices(fb))
    assert report["pickup_ticks"] == QUARTER
    assert not flags_of(report, s4.FLAG_PICKUP_MISMATCH) and not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    assert min(e["tick_onset"] for e in satb["Bass"] if e["global_bar"] == 1) == QUARTER


def test_pickup_no_majority_rejects_and_places_as_bar_1() -> None:
    # Chosen fallback: with no unique winning cluster nothing is aligned (the
    # old conservative behaviour) and every short-first-bar voice is flagged.
    two_disagree = {"Soprano": (60, QUARTER), "Alto": (60, HALF),
                    "Tenor": (None, QUARTER), "Bass": (None, QUARTER)}
    tie = {"Soprano": (60, QUARTER), "Alto": (60, QUARTER),
           "Tenor": (60, HALF), "Bass": (60, HALF)}
    all_different = {"Soprano": (60, QUARTER), "Alto": (60, HALF),
                     "Tenor": (60, EIGHTH), "Bass": (60, 360)}
    for fb in (two_disagree, tie, all_different):
        # Full final bars: nothing completes any candidate, so no pickup can win.
        _, report = s4.reconstruct_satb_with_report(pickup_voices(fb, final=WHOLE))
        assert report["pickup_ticks"] == 0, fb
        assert flags_of(report, s4.FLAG_PICKUP_SUSPECT) and not flags_of(report, s4.FLAG_PICKUP)


def test_pickup_only_on_first_strip_and_midbar_break_flagged() -> None:
    # System 1 ends on a half bar in every voice; system 2 opens with the other half.
    v = {n: make_strip(n, 1, [[(60, WHOLE)], [(62, HALF)]], 0)
         + make_strip(n, 2, [[(64, HALF)], [(65, WHOLE)]], 0) for n in VOICES}
    _, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == 0, "gate 3: a later system's short first bar is never a pickup"
    (brk,) = flags_of(report, s4.FLAG_MIDBAR_BREAK)
    assert brk["sys_idx"] == 2 and brk["review_needed"] is True


def test_rest_only_first_bar_matching_pickup_right_aligns() -> None:
    v = {n: make_strip(n, 1, [[(None, QUARTER)], [(62, WHOLE)], [(64, WHOLE - QUARTER)]], 0) for n in VOICES}
    v["Soprano"] = make_strip("Soprano", 1, [[(60, QUARTER)], [(62, WHOLE)], [(64, WHOLE - QUARTER)]], 0)
    satb, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == QUARTER and not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    assert min(e["tick_onset"] for e in satb["Bass"] if e["global_bar"] == 1) == QUARTER


# ── Evidence-scored pickup choice (bar = 1920) ────────────────────────────────

def scored_voices(spec: dict) -> dict:
    """spec[voice] = (first_bar_items, final_bar_items); a middle whole bar is added.
    Items are make_strip tuples, so extras such as {"confidence": 0.9} pass through."""
    return {n: make_strip(n, 1, [spec[n][0], [(62, WHOLE)], spec[n][1]], 0) for n in VOICES}


def cn(pitch: Optional[int], ticks: int, conf: Optional[float]) -> tuple:
    return (pitch, ticks) if conf is None else (pitch, ticks, {"confidence": conf})


def cand_ticks(flag: dict) -> list:
    return [c["ticks"] for c in flag["candidates"]]


def test_scored_pickup_two_short_two_long_complement_decides() -> None:
    fin = [cn(64, 1440, 0.9)]
    spec = {"Soprano": ([cn(60, 480, 0.9)], fin), "Alto": ([cn(60, 480, 0.9)], fin),
            "Tenor": ([cn(60, 960, 0.9)], fin), "Bass": ([cn(60, 960, 0.9)], fin)}
    satb, report = s4.reconstruct_satb_with_report(scored_voices(spec))
    assert report["pickup_ticks"] == 480
    assert not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    for voice in ("Tenor", "Bass"):
        (mm,) = flags_of(report, s4.FLAG_PICKUP_MISMATCH, voice)
        assert mm["review_needed"] is True and mm["action"] == "trimmed_head_to_pickup"
        first = [e for e in satb[voice] if e["global_bar"] == 0]
        assert [(e["tick_onset"], e["duration_ticks"]) for e in first] == [(0, 480)], "kept the LAST 480"
        assert min(e["tick_onset"] for e in satb[voice] if e["global_bar"] == 1) == 480


def test_scored_pickup_two_two_full_final_bars_is_a_tie_refused_or_960() -> None:
    fin = [(64, WHOLE)]
    spec = {"Soprano": ([(60, 480)], fin), "Alto": ([(60, 480)], fin),
            "Tenor": ([(60, 960)], fin), "Bass": ([(60, 960)], fin)}
    _, report = s4.reconstruct_satb_with_report(scored_voices(spec))
    # SPEC CONFLICT (reported): literal scoring gives 0 -> 2.75, 960 -> 2.50, 480 -> 2.25
    # (full final bars are a +2.0 complement for "no pickup" plus its 0.75 prior), so the
    # spec's expected order [960, 480, 0] / suggested 960 does not arise. Margin 0.25 < 0.75.
    assert report["pickup_ticks"] == 0
    (first, *_) = flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    assert cand_ticks(first) == [0, 960, 480], cand_ticks(first)
    assert first["suggested_pickup_ticks"] == 0 and first["review_needed"] is True


def test_scored_pickup_full_bars_are_votes_for_no_pickup() -> None:
    full = [(60, WHOLE)]
    spec = {"Soprano": ([(60, 480)], [(64, WHOLE)]), "Alto": (full, [(64, WHOLE)]),
            "Tenor": (full, [(64, WHOLE)]), "Bass": (full, [(64, WHOLE)])}
    _, report = s4.reconstruct_satb_with_report(scored_voices(spec))
    assert report["pickup_ticks"] == 0
    assert not flags_of(report, s4.FLAG_PICKUP)
    assert flags_of(report, s4.FLAG_PICKUP_SUSPECT, "Soprano")


def test_scored_pickup_rest_only_voices_are_half_votes() -> None:
    fin = [(64, 1440)]
    spec = {"Soprano": ([(60, 480)], fin), "Alto": ([(None, 480)], fin),
            "Tenor": ([(None, 480)], fin), "Bass": ([(None, 480)], fin)}
    satb, report = s4.reconstruct_satb_with_report(scored_voices(spec))
    assert report["pickup_ticks"] == 480
    assert not flags_of(report, s4.FLAG_PICKUP_MISMATCH) and not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    assert flags_of(report, s4.FLAG_PICKUP)[0]["review_needed"] is False
    for voice in VOICES:
        assert min(e["tick_onset"] for e in satb[voice] if e["global_bar"] == 1) == 480


def test_scored_pickup_two_agree_two_deviants_never_move_the_winner() -> None:
    # Vote weight is constant (confidence is uncalibrated and no longer used): the
    # winner is decided structurally, by two agreeing voices plus the 1440 complement
    # bar, and the two dissenting voices (720 / 960) are quarantined as deviants.
    fin = [(64, 1440)]
    spec = {"Soprano": ([(60, 480)], fin), "Alto": ([(60, 480)], fin),
            "Tenor": ([(60, 720)], fin), "Bass": ([(60, 960)], fin)}
    _, report = s4.reconstruct_satb_with_report(scored_voices(spec))
    assert report["pickup_ticks"] == 480
    cands = flags_of(report, s4.FLAG_PICKUP)[0]["candidates"]
    assert cands[0]["ticks"] == 480 and set(cands[0]["voters"]) >= {"Soprano", "Alto"}
    assert {f["voice"] for f in flags_of(report, s4.FLAG_PICKUP_MISMATCH)} == {"Tenor", "Bass"}


def test_scored_pickup_all_different_partial_complement_refuses_with_candidates() -> None:
    spec = {"Soprano": ([(60, 480)], [(64, 1440)]), "Alto": ([(60, 960)], [(64, WHOLE)]),
            "Tenor": ([(60, 240)], [(64, WHOLE)]), "Bass": ([(60, 360)], [(64, 1560)])}
    _, report = s4.reconstruct_satb_with_report(scored_voices(spec))
    assert report["pickup_ticks"] == 0
    flag = flags_of(report, s4.FLAG_PICKUP_SUSPECT, "Soprano")[0]
    assert len(flag["candidates"]) == 3 and flag["review_needed"] is True
    top = flag["candidates"][0]
    assert set(top) == {"ticks", "score", "voters", "complement_voices", "standard"}
    want = top["ticks"] if top["score"] >= s4.PICKUP_SUGGEST_MIN_SCORE else None
    assert flag["suggested_pickup_ticks"] == want


def test_scored_pickup_dropped_note_deviant_is_suffix_consistent() -> None:
    fin = [(64, 1440)]
    two = [(60, EIGHTH), (62, EIGHTH)]
    spec = {"Soprano": (two, fin), "Alto": (two, fin), "Bass": (two, fin),
            "Tenor": ([(62, EIGHTH)], fin)}
    satb, report = s4.reconstruct_satb_with_report(scored_voices(spec))
    assert report["pickup_ticks"] == 480
    (mm,) = flags_of(report, s4.FLAG_PICKUP_MISMATCH, "Tenor")
    assert not mm.get("review_needed"), "consistent with a dropped leading note: informational"
    first = [e for e in satb["Tenor"] if e["global_bar"] == 0]
    assert [e["tick_onset"] for e in first] == [EIGHTH], "right-aligned to the downbeat"


# ── Structural pickup pre-check (bar-count excess + tick congruence) ──────────

def excess_voices(tenor_bars: list, others: list, first_idx: int = 1,
                  tenor_idx: int = 1, other_over: Optional[dict] = None) -> dict:
    v = {n: make_strip(n, 1, others, first_idx) for n in VOICES}
    v["Tenor"] = make_strip("Tenor", 1, tenor_bars, tenor_idx)
    for n, bars in (other_over or {}).items():
        v[n] = make_strip(n, 1, bars, first_idx)
    return v


def test_excess_bar_dsmn_pickup_accepted() -> None:
    v = excess_voices([[(60, EIGHTH)], [(62, WHOLE)], [(64, WHOLE)]], full_bars(2))
    satb, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == EIGHTH
    assert not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    (pk,) = flags_of(report, s4.FLAG_PICKUP)
    assert pk["review_needed"] is True, "complement count < 2: a human should still confirm"
    assert "bar-count excess" in pk["detail"] and "tick congruence" in pk["detail"]
    assert not flags_of(report, s4.FLAG_PICKUP_MISMATCH), "reference voices are not deviants"
    for n in VOICES:
        assert min(e["tick_onset"] for e in satb[n] if e["global_bar"] == 1) == EIGHTH, n


def test_excess_bar_real_stage3_numbering() -> None:
    # Stage 3 skips a barline before the first note: S/A/B idx {0,1}, Tenor {0,1,2}.
    v = excess_voices([[(60, EIGHTH)], [(62, WHOLE)], [(64, WHOLE)]], full_bars(2), 0, 0)
    assert {e["measure_index"] for e in v["Soprano"]} == {0, 1}
    assert {e["measure_index"] for e in v["Tenor"]} == {0, 1, 2}
    satb, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == EIGHTH and not flags_of(report, s4.FLAG_PICKUP_SUSPECT)
    assert flags_of(report, s4.FLAG_PICKUP)[0]["review_needed"] is True
    for n in VOICES:
        assert min(e["tick_onset"] for e in satb[n] if e["global_bar"] == 1) == EIGHTH, n


def test_excess_bar_absent_equal_counts_still_suspects_soprano() -> None:
    spec = {"Soprano": ([(60, 480)], [(64, WHOLE)]), "Alto": ([(60, WHOLE)], [(64, WHOLE)]),
            "Tenor": ([(60, WHOLE)], [(64, WHOLE)]), "Bass": ([(60, WHOLE)], [(64, WHOLE)])}
    satb, report = s4.reconstruct_satb_with_report(scored_voices(spec))
    assert report["pickup_ticks"] == 0
    assert flags_of(report, s4.FLAG_PICKUP_SUSPECT, "Soprano")


def test_excess_bar_split_bar_hallucination_is_not_a_pickup() -> None:
    # Tenor 240 + 1680 + 1920: n+1 measures but total 3840 - 240 != 3840 -> not congruent.
    v = excess_voices([[(60, EIGHTH)], [(62, WHOLE - EIGHTH)], [(64, WHOLE)]], full_bars(2))
    _, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == 0
    assert flags_of(report, s4.FLAG_PICKUP_SUSPECT, "Tenor")
    assert not any("bar-count excess" in f["detail"] for f in flags_of(report, s4.FLAG_PICKUP))


def test_excess_bar_rest_only_pickup_via_half_votes() -> None:
    # Complement finals (bar - 240) support the pickup; rest-only S/A/B are half votes.
    fin = WHOLE - EIGHTH
    v = {n: make_strip(n, 1, [[(None, EIGHTH)], [(62, WHOLE)], [(64, fin)]], 0)
         for n in ("Soprano", "Alto", "Bass")}
    v["Tenor"] = make_strip("Tenor", 1, [[(60, EIGHTH)], [(62, WHOLE)], [(64, fin)]], 0)
    _, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == EIGHTH
    assert not flags_of(report, s4.FLAG_PICKUP_SUSPECT)


def test_excess_bar_conflicting_extras_skip_precheck() -> None:
    v = excess_voices([[(60, EIGHTH)], [(62, WHOLE)], [(64, WHOLE)]], full_bars(2),
                      other_over={"Bass": [[(60, 480)], [(62, WHOLE)], [(64, WHOLE)]]})
    v["Soprano"] = make_strip("Soprano", 1, full_bars(2), 1)
    v["Alto"] = make_strip("Alto", 1, full_bars(2), 1)
    _, report = s4.reconstruct_satb_with_report(v)
    assert report["pickup_ticks"] == 0, "old scoring decides"
    assert not any("bar-count excess" in f["detail"] for f in flags_of(report, s4.FLAG_PICKUP))
    assert flags_of(report, s4.FLAG_PICKUP_SUSPECT)


def test_excess_bar_single_reference_voice_does_not_fire() -> None:
    v = {"Soprano": make_strip("Soprano", 1, full_bars(2), 1),
         "Alto": make_strip("Alto", 1, [[(60, HALF)], [(62, WHOLE)]], 1),
         "Bass": make_strip("Bass", 1, [[(60, HALF)], [(62, WHOLE)]], 1),
         "Tenor": make_strip("Tenor", 1, [[(60, EIGHTH)], [(62, WHOLE)], [(64, WHOLE)]], 1)}
    _, report = s4.reconstruct_satb_with_report(v)
    for kind in (s4.FLAG_PICKUP, s4.FLAG_PICKUP_SUSPECT, s4.FLAG_PICKUP_MISMATCH):
        assert not any("bar-count excess" in f["detail"] for f in flags_of(report, kind))


# ── Review-driven fixes: invariant fallback, tie chains, local-mode clamp ─────

def test_run_repair_invariant_failure_flags_and_clips_instead_of_asserting() -> None:
    # Force the "repair did not land on bar_ticks" case by disabling the rescale.
    # Nine eighths (2160 ticks) go through the run repair; without a fallback the old
    # assert would abort (or, under python -O, silently emit an over-long bar).
    original = s4._rescale_slots
    s4._rescale_slots = lambda *a, **k: None
    try:
        satb, report = overflow_case([(60 + i, EIGHTH) for i in range(9)])
    finally:
        s4._rescale_slots = original
    (f,) = flags_of(report, s4.FLAG_BAR_INVARIANT, "Tenor")
    assert f["review_needed"] is True and f["action"] == s4.ACTION_CLIPPED
    bar1 = [e for e in satb["Tenor"] if e["global_bar"] == 1]
    assert sum(e["duration_ticks"] for e in bar1) == WHOLE, "clipped to exactly one bar"


def test_stage3_tie_chain_preserves_both_marks_and_stage4_chains_ties() -> None:
    try:
        import stage3_transcription as s3
    except ImportError as exc:
        print(f"  SKIP test_stage3_tie_chain: cannot import stage3 ({exc})")
        return
    # A~A~A: note slur.start slur.end note slur.start slur.end note. The middle note
    # both ends one tie and starts the next; the later "start" used to erase the "end".
    tie = ["clef.G-L2", "metersign.C-L3", "note.quarter-L3", "slur.start-L3", "slur.end-L3",
           "note.quarter-L3", "slur.start-L3", "slur.end-L3", "note.quarter-L3",
           "rest.quarter-L3"]
    plain = ["clef.G-L2", "metersign.C-L3", "note.whole-L3"]
    ev = s3.infer_pitch(tie, "Alto", 1, 1)
    ns = [e for e in ev if e["type"] == "note"]
    assert [e.get("slur") for e in ns] == ["start", "start", "end"]
    assert [bool(e.get("slur_end")) for e in ns] == [False, True, True]
    voices = {v: s3.infer_pitch(plain, v, 1, 1) for v in VOICES}
    voices["Alto"] = ev
    satb, report = s4.reconstruct_satb_with_report(voices)
    merged = notes(satb["Alto"])
    assert len(merged) == 1 and merged[0]["tie_span"] == 3
    assert merged[0]["duration_ticks"] == 3 * QUARTER


def test_local_placement_is_clamped_at_the_next_system() -> None:
    # Alto has 3 bars in system 1 where the consensus is 2: local mode used to let
    # its third bar sound over system 2's first bar (only Stage 5's overlap warning).
    sys1 = {n: make_strip(n, 1, full_bars(2), 1) for n in VOICES}
    sys1["Alto"] = make_strip("Alto", 1, full_bars(3, 67), 1)
    sys2 = {n: make_strip(n, 2, full_bars(2, 72), 1) for n in VOICES}
    v = {n: sys1[n] + sys2[n] for n in VOICES}
    satb, report = s4.reconstruct_satb_with_report(v)
    assert flags_of(report, s4.FLAG_BAR_COUNT, "Alto")
    (f,) = flags_of(report, s4.FLAG_LOCAL_OVERRUN, "Alto")
    assert f["review_needed"] is True and "67" in f["detail"]
    sys1_alto = [e for e in satb["Alto"] if e["sys_idx"] == 1]
    assert max(e["tick_onset"] + e["duration_ticks"] for e in sys1_alto) <= 2 * WHOLE
    assert {e["pitch"] for e in satb["Alto"] if e["sys_idx"] == 2} == {72}


def overflow_case(tenor_bar: list) -> tuple:
    v = {n: make_strip(n, 1, full_bars(2), 0) for n in VOICES}
    v["Tenor"] = make_strip("Tenor", 1, [tenor_bar, [(62, WHOLE)]], 0)
    return s4.reconstruct_satb_with_report(v)


def test_overflow_drops_tail_and_lists_pitches() -> None:
    satb, report = overflow_case([(60, HALF), (62, HALF), (64, QUARTER)])
    (f,) = flags_of(report, s4.FLAG_BAR_OVERFLOW, "Tenor")
    assert f["review_needed"] is True and "midi 64" in f["detail"], f["detail"]
    bar1 = [e for e in satb["Tenor"] if e["global_bar"] == 1]
    assert [e["tick_onset"] for e in bar1] == [0, HALF], "kept notes stay at their onsets"


def test_overflow_120_tick_error_is_not_swallowed() -> None:
    _, report = overflow_case([(60, HALF), (62, HALF + 120)])
    assert flags_of(report, s4.FLAG_BAR_OVERFLOW, "Tenor"), "a sixteenth of overshoot must be flagged"
    assert not flags_of(report, s4.FLAG_SUSPECTED_TUPLET)


def test_overflow_trims_duration_of_straddling_note() -> None:
    satb, _ = overflow_case([(60, HALF), (62, HALF + QUARTER)])
    bar1 = [e for e in satb["Tenor"] if e["global_bar"] == 1]
    assert bar1[-1]["tick_onset"] + bar1[-1]["duration_ticks"] == WHOLE


def test_overflow_off_grid_is_suspected_tuplet_and_drops_nothing() -> None:
    # 960 + 480 + 160 + 160 + 240 = 2000: 80 ticks over, not a multiple of a sixteenth.
    satb, report = overflow_case([(60, HALF), (62, QUARTER), (64, 160), (65, 160), (67, 240)])
    (f,) = flags_of(report, s4.FLAG_SUSPECTED_TUPLET, "Tenor")
    assert f["review_needed"] is True
    bar1 = [e for e in satb["Tenor"] if e["global_bar"] == 1]
    assert len(bar1) == 5, "nothing dropped"
    assert max(e["tick_onset"] + e["duration_ticks"] for e in bar1) <= WHOLE


def test_overflow_uses_confidence_to_drop_one_short_value() -> None:
    bar = [(60, HALF, {"confidence": 0.99}), (62, QUARTER, {"confidence": 0.20}),
           (64, HALF, {"confidence": 0.95})]        # 960 + 480 + 960: one quarter over
    satb, report = overflow_case(bar)
    (f,) = flags_of(report, s4.FLAG_BAR_OVERFLOW, "Tenor")
    assert "lowest-confidence" in f["detail"]
    bar1 = notes([e for e in satb["Tenor"] if e["global_bar"] == 1])
    assert [e["pitch"] for e in bar1] == [60, 64], "the low-confidence note went, not the tail"
    assert [e["tick_onset"] for e in bar1] == [0, HALF], "later note closed up inside the bar"


def test_tie_needs_exactly_two_notes_g_a_a_b() -> None:
    v = {n: make_strip(n, 1, full_bars(1), 0) for n in VOICES}
    v["Alto"] = make_strip("Alto", 1, [[(67, QUARTER, {"slur": "start"}), (69, QUARTER, {"slur": "middle"}),
                                        (69, QUARTER, {"slur": "middle"}), (71, QUARTER, {"slur": "end"})]], 0)
    satb, _ = s4.reconstruct_satb_with_report(v)
    assert [e["pitch"] for e in notes(satb["Alto"])] == [67, 69, 69, 71]
    assert all(e["tie_span"] == 1 for e in notes(satb["Alto"])), "phrase slur must not merge repeated A"


def test_whole_rest_fills_non_4_4_bar() -> None:
    v = {n: make_strip(n, 1, [[(60, 1440)], [(62, 1440)]], 0, "3/4") for n in VOICES}
    bass = make_strip("Bass", 1, [[(None, WHOLE)], [(43, 1440)]], 0, "3/4")
    bass[0]["symbol"] = "rest.whole-L4"
    v["Bass"] = bass
    satb, report = s4.reconstruct_satb_with_report(v)
    assert satb["Bass"][0]["duration_ticks"] == 1440
    assert not flags_of(report, s4.FLAG_BAR_OVERFLOW, "Bass")
    assert satb["Bass"][1]["tick_onset"] == 1440


def test_tenor_high_pitch_flagged() -> None:
    v = {n: make_strip(n, 1, full_bars(1), 0) for n in VOICES}
    v["Tenor"] = make_strip("Tenor", 1, [[(60, WHOLE)]], 0)   # sounding C4 = written C5
    _, report = s4.reconstruct_satb_with_report(v)
    assert flags_of(report, s4.FLAG_TENOR_RANGE, "Tenor")
    v["Tenor"] = make_strip("Tenor", 1, [[(55, WHOLE)]], 0)
    _, report = s4.reconstruct_satb_with_report(v)
    assert not flags_of(report, s4.FLAG_TENOR_RANGE)


def test_stage5_chord_notes_dedupe_and_no_trailing_padding() -> None:
    chord = [{"type": "note", "pitch": p, "duration_ticks": WHOLE, "tick_onset": 0} for p in (40, 47)]
    beats = s5.voice_notes(chord + [dict(chord[0])])
    assert sorted(b[2] for b in beats) == [40, 47], "both chord notes sound once"
    seq = {n: make_strip(n, 1, full_bars(2), 0) for n in VOICES}
    satb, report = s4.reconstruct_satb_with_report(seq)
    assert s5._piece_end_tick(satb) == 2 * WHOLE == report["total_ticks"]


# ── Case D: Stage 3 -> Stage 4 with the real Camera-PrIMuS tie token pattern ───

def test_stage3_tie_tokens_reach_stage4() -> None:
    try:
        import stage3_transcription as s3
    except ImportError as exc:  # explicit skip, not a silent pass
        print(f"  SKIP test_stage3_tie_tokens_reach_stage4: cannot import stage3 ({exc})")
        return
    # Token order copied from corpus sample 000051661-1_1_2:
    #   note slur.start slur.end note      (adjacent tie)
    #   note slur.start barline slur.end note   (tie across a barline)
    clef = {"Soprano": "clef.G-L2", "Alto": "clef.G-L2", "Tenor": "clef.G-L2", "Bass": "clef.F-L4"}
    alto_sys1 = ["note.half-L3", "slur.start-L3", "slur.end-L3", "note.half-L3", "barline-L1",   # tie in a bar
                 "note.half-L4", "note.half-L3", "slur.start-L3", "barline-L1", "slur.end-L3",  # tie over a barline
                 "note.half-L3", "note.half-L4", "slur.start-L4"]                               # dangling at strip end
    alto_sys2 = ["slur.end-L4", "note.half-L4", "note.half-L4", "barline-L1", "note.whole-L3"]
    whole3 = "note.whole-L3"
    voices = {}
    for voice in VOICES:
        body1 = alto_sys1 if voice == "Alto" else [whole3, "barline-L1", whole3, "barline-L1", whole3]
        body2 = alto_sys2 if voice == "Alto" else [whole3, "barline-L1", whole3]
        voices[voice] = (s3.infer_pitch([clef[voice], "metersign.C-L3"] + body1, voice, 1, 1)
                         + s3.infer_pitch([clef[voice]] + body2, voice, 1, 2))
    # Stage 3 now puts "end" on the note AFTER slur.end (it used to overwrite note 1's "start").
    alto1 = [e for e in voices["Alto"] if e["sys_idx"] == 1 and e["type"] == "note"]
    assert [e["slur"] for e in alto1] == ["start", "end", None, "start", "end", "start"], \
        [e["slur"] for e in alto1]
    # a rest after slur.end cannot receive the "end" mark
    rest_case = s3.infer_pitch([clef["Alto"], "note.half-L3", "slur.start-L3", "slur.end-L3",
                                "rest.half-L3", "note.half-L3"], "Alto", 1, 1)
    assert [e["slur"] for e in rest_case] == ["start", None, None]

    satb, report = s4.reconstruct_satb_with_report(voices)
    assert [e["duration_ticks"] for e in notes(satb["Alto"])] == [WHOLE, HALF, WHOLE, WHOLE, HALF, WHOLE]
    assert [e["tie_span"] for e in notes(satb["Alto"])] == [2, 1, 2, 2, 1, 1]
    assert not flags_of(report, s4.FLAG_BAR_COUNT) and not flags_of(report, s4.FLAG_BAR_UNDERFULL)


# ── Run-based overflow repair (BUG-015 follow-up) ──────────────────────────────

EIGHTH_RUN_BAR = [(60 + i, EIGHTH) for i in range(9)]           # 9 eighths: 2160


def tenor_bar1(satb: dict) -> list:
    return [e for e in satb["Tenor"] if e["global_bar"] == 1]


def test_run_nine_eighths_scaled_evenly_from_worked_example() -> None:
    satb, report = overflow_case(EIGHTH_RUN_BAR)
    (f,) = flags_of(report, s4.FLAG_RUN_SCALED, "Tenor")
    assert f["action"] == "scaled_run" and f["review_needed"] is True
    assert "over-counted" in f["detail"] and "tuplet" in f["detail"]
    bar1 = tenor_bar1(satb)
    t0 = min(e["tick_onset"] for e in bar1)
    assert [e["duration_ticks"] for e in bar1] == [214] * 3 + [213] * 6
    assert [e["tick_onset"] - t0 for e in bar1] == \
        [0, 214, 428, 642, 855, 1068, 1281, 1494, 1707]
    assert sum(e["duration_ticks"] for e in bar1) == WHOLE
    assert len(bar1) == 9, "nothing dropped"


def test_run_five_quarters_scaled_to_384() -> None:
    satb, report = overflow_case([(60 + i, QUARTER) for i in range(5)])
    assert flags_of(report, s4.FLAG_RUN_SCALED, "Tenor")
    bar1 = tenor_bar1(satb)
    t0 = bar1[0]["tick_onset"]
    assert [e["duration_ticks"] for e in bar1] == [384] * 5
    assert [e["tick_onset"] - t0 for e in bar1] == [0, 384, 768, 1152, 1536]


def test_run_seven_eighths_then_quarter_shifts_tail_left() -> None:
    satb, report = overflow_case([(60 + i, EIGHTH) for i in range(7)] + [(70, QUARTER)])
    assert flags_of(report, s4.FLAG_RUN_SCALED, "Tenor")
    bar1 = tenor_bar1(satb)
    t0 = bar1[0]["tick_onset"]
    assert [e["duration_ticks"] for e in bar1[:7]] == [206] * 5 + [205] * 2
    assert [e["tick_onset"] - t0 for e in bar1[:7]] == [0, 206, 412, 618, 824, 1030, 1235]
    assert bar1[7]["tick_onset"] - t0 == 1440 and bar1[7]["duration_ticks"] == QUARTER


def test_run_exact_triplet_after_half_and_quarter() -> None:
    satb, report = overflow_case([(60, HALF), (62, QUARTER), (64, EIGHTH), (65, EIGHTH), (67, EIGHTH)])
    (f,) = flags_of(report, s4.FLAG_SUSPECTED_TUPLET, "Tenor")
    assert f["action"] == "scaled_tuplet" and f["review_needed"] is True
    assert [e["duration_ticks"] for e in tenor_bar1(satb)][2:] == [160, 160, 160]
    assert not flags_of(report, s4.FLAG_RUN_SCALED)


def test_run_partial_triplet_single_beat_aligned_group() -> None:
    # 2 x 120 puts a 4-eighth run at offset 240: only the group starting at
    # offset 480 is on a beat. Half at the end.
    bar = [(59, 120), (60, 120)] + [(61 + i, EIGHTH) for i in range(4)] + [(70, HALF)]
    satb, report = overflow_case(bar)
    (f,) = flags_of(report, s4.FLAG_SUSPECTED_TUPLET, "Tenor")
    assert f["action"] == "scaled_tuplet"
    bar1 = tenor_bar1(satb)
    assert [e["duration_ticks"] for e in bar1[2:6]] == [EIGHTH, 160, 160, 160]
    assert bar1[6]["tick_onset"] - bar1[0]["tick_onset"] == HALF, "half lands on beat 3"


def test_run_rests_join_run_and_are_never_dropped() -> None:
    bar = [(60, QUARTER), (None, QUARTER), (62, QUARTER), (63, QUARTER), (64, QUARTER)]
    satb, report = overflow_case(bar)
    assert flags_of(report, s4.FLAG_RUN_SCALED, "Tenor")
    bar1 = tenor_bar1(satb)
    assert sum(e["type"] == "rest" for e in bar1) == 1 and len(bar1) == 5


def test_run_needs_two_notes() -> None:
    # Only one note slot in the eighth run -> not a qualifying run.
    bar = [(60, HALF), (None, EIGHTH), (None, EIGHTH), (61, EIGHTH), (62, HALF)]  # 2160
    _, report = overflow_case(bar)
    assert not flags_of(report, s4.FLAG_RUN_SCALED)
    assert flags_of(report, s4.FLAG_BAR_OVERFLOW, "Tenor")


def test_two_slot_case_still_trims() -> None:
    _, report = overflow_case([(60, HALF), (62, HALF), (64, HALF)])
    assert not flags_of(report, s4.FLAG_RUN_SCALED)


def test_confidence_drop_never_fires_when_a_run_exists() -> None:
    bar = [(60 + i, QUARTER, {"confidence": 0.9 - 0.1 * i}) for i in range(5)]
    _, report = overflow_case(bar)
    assert flags_of(report, s4.FLAG_RUN_SCALED, "Tenor")
    assert not [f for f in report["flags"] if "lowest-confidence" in f["detail"]]


def test_confidence_drop_ignores_unusable_confidence_values() -> None:
    # A None / missing confidence on one note means "no signal": fall back to
    # clipping instead of raising or dropping on partial data.
    bar = [(60, HALF, {"confidence": 0.99}), (62, QUARTER, {"confidence": None}),
           (64, HALF, {"confidence": 0.95})]
    _, report = overflow_case(bar)
    (f,) = flags_of(report, s4.FLAG_BAR_OVERFLOW, "Tenor")
    assert "lowest-confidence" not in f["detail"]
    assert s4._has_confidence({"confidence": 0.5})
    assert not any(s4._has_confidence({"confidence": v})
                   for v in (None, "0.9", float("nan"), True))
    assert not s4._has_confidence({})


def test_missing_barline_is_clipped_not_scaled() -> None:
    satb, report = overflow_case([(60 + i % 7, EIGHTH) for i in range(16)])   # 2 bars worth
    (f,) = flags_of(report, s4.FLAG_MISSING_BARLINE, "Tenor")
    assert f["action"] == "clipped" and f["review_needed"] is True
    bar1 = tenor_bar1(satb)
    assert all(e["duration_ticks"] == EIGHTH for e in bar1) and len(bar1) == 8


def test_voice_level_flag_when_many_bars_need_run_scaling() -> None:
    v = {n: make_strip(n, 1, full_bars(4), 0) for n in VOICES}
    v["Tenor"] = make_strip("Tenor", 1, [[(60 + i, QUARTER) for i in range(5)]] * 2 +
                            [[(62, WHOLE)]] * 2, 0)
    _, report = s4.reconstruct_satb_with_report(v)
    (f,) = flags_of(report, s4.FLAG_VOICE_RUN_SCALING, "Tenor")
    assert f["review_needed"] is True
    assert not flags_of(report, s4.FLAG_VOICE_RUN_SCALING, "Bass")


# ── Confidence plumbing ────────────────────────────────────────────────────────

def test_ground_truth_events_have_no_confidence_field() -> None:
    v = {n: make_strip(n, 1, full_bars(2), 0) for n in VOICES}
    satb, _ = s4.reconstruct_satb_with_report(v)
    assert all("confidence" not in e for evs in satb.values() for e in evs)


def test_stage4_preserves_confidence_and_ties_take_the_min() -> None:
    bar = [(60, HALF, {"tie_to_next": True, "confidence": 0.9}),
           (60, HALF, {"confidence": 0.5})]
    satb, _ = overflow_case(bar)
    (tied,) = tenor_bar1(satb)
    assert tied["tie_span"] == 2 and tied["confidence"] == 0.5
    assert all("confidence" not in e for e in notes(satb["Soprano"]))
    v = {n: make_strip(n, 1, [[(60, WHOLE, {"confidence": 0.8})]], 0) for n in VOICES}
    satb2, _ = s4.reconstruct_satb_with_report(v)
    assert all(e["confidence"] == 0.8 for evs in satb2.values() for e in evs)


def test_stage3_confidence_is_min_over_note_accidental_and_dot() -> None:
    try:
        import stage3_transcription as s3
    except ImportError as exc:
        print(f"  SKIP test_stage3_confidence: cannot import stage3 ({exc})")
        return
    syms = ["clef.G-L2", "metersign.C-L3", "accidental.sharp-L3", "note.quarter-L3",
            "dot-S3", "rest.quarter-L3", "note.half-L4"]
    conf = [0.9, 0.9, 0.4, 0.8, 0.3, 0.7, 0.95]
    ev = s3.infer_pitch(syms, "Alto", 1, 1, confidences=conf)
    assert [e["confidence"] for e in ev] == [0.3, 0.7, 0.95], "min(note, accidental, dot); rest; later note unaffected"
    ev2 = s3.infer_pitch(syms[:4] + syms[5:], "Alto", 1, 1, confidences=conf[:4] + conf[5:])
    assert ev2[0]["confidence"] == 0.4
    assert all("confidence" not in e for e in s3.infer_pitch(syms, "Alto", 1, 1))
    try:
        s3.infer_pitch(syms, "Alto", 1, 1, confidences=[0.5])
    except ValueError:
        pass
    else:
        raise AssertionError("length mismatch must raise")


# ── Runner ─────────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc!r}")
        else:
            print(f"PASS {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
