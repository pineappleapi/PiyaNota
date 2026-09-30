"""Synthetic token tests for key / time-signature continuity (PIYA-106 R1-R4, reviews of 2026-09-30).

R1  a ClefKeyNet system key that breaks from the carried key needs a corroborating sign, else the old key is
    held and the system flagged with both candidates (stage3_clefkey.apply_key_continuity).
R2  a post-barline key change directly followed by a time signature needs only one glyph; a full cancel may
    be followed by a restated key on the same positions.
R3  a mid-strip time signature is reported, never applied.
R4  a mid-strip key change applies only when HEADER_QUORUM voices read it at the same bar
    (stage3_transcription.decide_mid_changes).

Token-level only: they say nothing about CRNN or ClefKeyNet accuracy.
"""

import contextlib
import io
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage3_clefkey as s3ck  # noqa: E402
import stage3_transcription as s3  # noqa: E402
from clef_voice_rules import ClefDecision  # noqa: E402

TREBLE = ["clef.G-L2"]
BASS = ["clef.F-L4"]
BAR = "barline-L1"
THREE_FOUR = ["digit.3-L4", "digit.4-L2"]
G4, C5, C_SHARP5, F5, F_SHARP5 = 67, 72, 73, 77, 78
VOICES = ["Soprano", "Alto", "Tenor", "Bass"]


def _run(tokens: list, key: int = 0, clef: str = "clef.G-L2", voice: str = "Soprano",
         next_key: Optional[int] = None, gate: Optional[dict] = None) -> tuple[list, list]:
    out: list = []
    with contextlib.redirect_stdout(io.StringIO()):
        events = s3.infer_pitch(list(tokens), voice=voice, page_index=1, sys_idx=1,
                                header_override=s3.HeaderOverride(clef, key, 0), next_system_key=next_key,
                                system_key_changes=gate, mid_changes_out=out)
    return events, out


def _pitches(tokens: list, **kw) -> list:
    return [e["pitch"] for e in _run(tokens, **kw)[0] if e["type"] == "note"]


# ── R2: meter-corroborated one-glyph change, full cancel + restate ──────────────────────────────────────────

def test_one_glyph_key_change_with_digit_meter() -> None:
    tokens = TREBLE + ["note.quarter-L5", BAR, "accidental.sharp-L5"] + THREE_FOUR + ["note.quarter-L5"]
    events, cands = _run(tokens)
    assert [e["pitch"] for e in events] == [F5, F_SHARP5]
    assert {"kind": "meter", "bar": 1, "meter": "3/4"} in cands
    assert any(c["kind"] == "key" and c["key"] == 1 and c["meter_follows"] for c in cands)


def test_one_glyph_key_change_with_metersign() -> None:
    tokens = TREBLE + ["note.quarter-L5", BAR, "accidental.flat-L3", "metersign.C/-L3", "note.quarter-L3"]
    assert _pitches(tokens) == [F5, 70]


def test_one_glyph_without_meter_is_still_inline_candidate() -> None:
    # Unchanged single-strip rule: a lone unanchored glyph after a barline is dropped, not a key change.
    tokens = TREBLE + ["note.quarter-L5", BAR, "accidental.sharp-L5", "note.quarter-L2", "note.quarter-L5"]
    assert _pitches(tokens) == [F5, G4, F5]


def test_meter_digits_are_clef_independent() -> None:
    tokens = BASS + ["note.quarter-L4", BAR, "accidental.sharp-L4"] + THREE_FOUR + ["note.quarter-L4"]
    assert _pitches(tokens, clef="clef.F-L4", voice="Bass") == [53, 54]


def test_twelve_eight_numerator_is_one_token() -> None:
    tokens = TREBLE + ["note.quarter-L5", BAR, "accidental.sharp-L5", "digit.12-L4", "digit.8-L2",
                       "note.quarter-L5"]
    events, cands = _run(tokens)
    assert [e["pitch"] for e in events] == [F5, F_SHARP5]
    assert {"kind": "meter", "bar": 1, "meter": "12/8"} in cands


def test_natural_then_meter_cancels_to_c() -> None:
    tokens = TREBLE + ["note.quarter-L5", BAR, "accidental.natural-L5"] + THREE_FOUR + ["note.quarter-L5"]
    assert _pitches(tokens, key=1) == [F_SHARP5, F5]


def test_full_cancel_then_restate_same_type() -> None:
    # 3# -> 1#: ♮F ♮C ♮G ♯F. Used to be rejected because ♯F re-uses a cancelled position.
    tokens = TREBLE + ["note.quarter-S3", BAR, "accidental.natural-L5", "accidental.natural-S3",
                       "accidental.natural-S5", "accidental.sharp-L5", "note.quarter-S3", "note.quarter-L5"]
    assert _pitches(tokens, key=3) == [C_SHARP5, C5, F_SHARP5]


def test_partial_cancel_overlapping_burst_is_rejected() -> None:
    # 2# with only ♮F then ♯F: a partial cancel that re-sharps the same line is a misread, not a key change.
    tokens = TREBLE + ["note.quarter-S3", BAR, "accidental.natural-L5", "accidental.sharp-L5",
                       "note.quarter-L2", "note.quarter-S3"]
    events, cands = _run(tokens, key=2)
    assert not [c for c in cands if c["kind"] == "key"]
    assert [e["pitch"] for e in events][-1] == C_SHARP5


def test_courtesy_signature_at_strip_end() -> None:
    tokens = TREBLE + ["note.quarter-L5", BAR, "accidental.sharp-L5"] + THREE_FOUR
    cands = _run(tokens)[1]
    assert any(c["kind"] == "key" and c["courtesy"] and c["key"] == 1 for c in cands)


# ── R3: meters reported, not applied; negatives that must not read as meters ────────────────────────────────

def test_mid_strip_meter_not_applied() -> None:
    tokens = TREBLE + ["digit.4-L4", "digit.4-L2", "note.quarter-L2", BAR] + THREE_FOUR + ["note.quarter-L2"]
    events, cands = _run(tokens)
    assert [e["time_signature"] for e in events] == ["4/4", "4/4"]
    assert cands == [{"kind": "meter", "bar": 1, "meter": "3/4"}]


def test_meter_digits_in_body_are_not_a_multirest_count() -> None:
    tokens = TREBLE + ["note.quarter-L2", "digit.3-L4", "digit.4-L2", "multirest-L3", BAR, "note.quarter-L2"]
    events = _run(tokens)[0]
    rest = next(e for e in events if e["symbol"].startswith("multirest"))
    assert rest["duration_ticks"] == s3.NOTE_DURATION_TICKS["whole"]


def test_multirest_count_after_barline_is_not_a_meter() -> None:
    tokens = TREBLE + ["note.quarter-L2", BAR, "digit.4-S5", "multirest-L3", BAR, "note.quarter-L2"]
    events, cands = _run(tokens)
    assert not cands
    rest = next(e for e in events if e["symbol"].startswith("multirest"))
    assert rest["duration_ticks"] == 4 * s3.NOTE_DURATION_TICKS["whole"]


def test_lone_digit_like_tuplet_three_is_not_a_meter() -> None:
    tokens = TREBLE + ["note.quarter-L2", BAR, "digit.3-L4", "note.eighth-L2", "note.eighth-L2"]
    assert not _run(tokens)[1]


def test_one_glyph_before_multirest_count_is_not_a_key_change() -> None:
    tokens = TREBLE + ["note.quarter-L5", BAR, "accidental.sharp-L5", "digit.4-S5", "multirest-L3", BAR,
                       "note.quarter-L5"]
    events, cands = _run(tokens)
    assert not [c for c in cands if c["kind"] == "key"]
    assert [e["pitch"] for e in events if e["type"] == "note"] == [F5, F5]


def test_phantom_out_of_order_burst_before_meter_is_not_a_key_change() -> None:
    tokens = TREBLE + ["note.quarter-L5", BAR, "accidental.sharp-S3", "accidental.sharp-L5"] + THREE_FOUR + [
        "note.quarter-L5"]
    assert not [c for c in _run(tokens)[1] if c["kind"] == "key"]


# ── R4: system quorum ──────────────────────────────────────────────────────────────────────────────────────

CHANGE = TREBLE + ["note.quarter-L5", BAR, "accidental.sharp-L5", "accidental.sharp-S3", "note.quarter-L2",
                   "note.quarter-L5"]
PLAIN = TREBLE + ["note.quarter-L5", BAR, "note.quarter-L2", "note.quarter-L5"]


def _system(strips: list) -> dict:
    return {f"s{i}": (VOICES[i], s3.scan_mid_changes(t, VOICES[i], 1, 1, s3.HeaderOverride("clef.G-L2", 0, 0)))
            for i, t in enumerate(strips)}


def test_quorum_change_applies_to_every_voice() -> None:
    gate, flags = s3.decide_mid_changes(_system([CHANGE, CHANGE, CHANGE, PLAIN]))
    assert gate == {1: 2}
    assert _pitches(PLAIN, gate=gate) == [F5, G4, F_SHARP5]      # the voice with no glyphs follows
    assert _pitches(CHANGE, gate=gate) == [F5, G4, F_SHARP5]
    assert all(s3.MID_KEY_CHANGE_FLAG in f and "review_needed" in f for f in flags.values())


def test_change_in_two_voices_is_rejected_and_flagged() -> None:
    gate, flags = s3.decide_mid_changes(_system([CHANGE, CHANGE, PLAIN, PLAIN]))
    assert gate == {}
    assert _pitches(CHANGE, gate=gate) == [F5, G4, F5]
    assert s3.MID_KEY_CHANGE_REJECTED_FLAG in flags["s0"] and flags["s2"] == []


def test_change_at_different_bars_has_no_quorum() -> None:
    late = TREBLE + ["note.quarter-L5", BAR, "note.quarter-L2", BAR, "accidental.sharp-L5",
                     "accidental.sharp-S3", "note.quarter-L2"]
    gate, _ = s3.decide_mid_changes(_system([CHANGE, CHANGE, late, late]))
    assert gate == {}


def test_meter_quorum_flags_system_single_meter_flags_strip() -> None:
    meter = TREBLE + ["note.quarter-L2", BAR] + THREE_FOUR + ["note.quarter-L2"]
    _, flags = s3.decide_mid_changes(_system([meter, meter, meter, PLAIN]))
    assert all(s3.MID_METER_CHANGE_FLAG in f for f in flags.values())
    _, flags = s3.decide_mid_changes(_system([meter, PLAIN, PLAIN, PLAIN]))
    assert flags["s0"] == [s3.MID_METER_UNCONFIRMED_FLAG, "review_needed"] and flags["s1"] == []


# ── R1: key continuity between systems ───────────────────────────────────────────────────────────────────────

def _decisions(votes: list) -> tuple[dict, dict]:
    """Four-voice systems on page 1 with the given ClefKeyNet majority votes and a plain body."""
    clef = ClefDecision(clef_class="G", token="clef.G-L2", octave_shift=0, source="voice_default",
                        classifier_top="G", flags=[])
    decisions, systems = {}, {}
    for s, vote in enumerate(votes, start=1):
        for v in VOICES:
            sid = f"p1s{s}{v}"
            decisions[sid] = s3ck.StripDecision(clef=clef, key=vote, key_source="system_majority", vote_key=vote)
            systems.setdefault((1, s), {})[sid] = (v, TREBLE + ["note.quarter-L2", BAR, "note.quarter-L2"])
    return decisions, systems


def _keys(out: dict, n: int) -> list:
    return [out[f"p1s{s}Soprano"].key for s in range(1, n + 1)]


def test_isolated_misread_to_c_is_held() -> None:
    # BUG-037 shape: 3# 0 3#.
    dec, systems = _decisions([3, 0, 3])
    out = s3ck.apply_key_continuity(dec, systems, set())
    assert _keys(out, 3) == [3, 3, 3]
    mid = out["p1s2Alto"]
    assert s3ck.KEY_CHANGE_UNCONFIRMED_FLAG in mid.flags and "review_needed" in mid.flags
    assert mid.key_candidates == [3, 0]
    assert out["p1s1Soprano"].next_key == 3
    assert dec["p1s2Alto"].key == 0      # input not modified


def test_change_confirmed_by_next_system() -> None:
    dec, systems = _decisions([-3, -1, -1])
    out = s3ck.apply_key_continuity(dec, systems, set())
    assert _keys(out, 3) == [-3, -1, -1]
    assert not out["p1s2Bass"].flags and out["p1s1Bass"].next_key == -1


def test_isolated_change_held_then_reevaluated() -> None:
    dec, systems = _decisions([2, 1, 2, 2])
    out = s3ck.apply_key_continuity(dec, systems, set())
    assert _keys(out, 4) == [2, 2, 2, 2]


def test_change_by_meter_change() -> None:
    dec, systems = _decisions([2, 1, 2])
    out = s3ck.apply_key_continuity(dec, systems, {(1, 2)})
    assert _keys(out, 3)[1] == 1


def test_change_to_c_needs_two_signs_without_naturals() -> None:
    dec, systems = _decisions([2, 0, 0, 0])
    out = s3ck.apply_key_continuity(dec, systems, set())
    # System 2 has only the next system; system 3 has the previous and the next, so C holds from there.
    assert _keys(out, 4) == [2, 2, 0, 0]
    assert out["p1s2Tenor"].key_candidates == [2, 0]


def test_change_to_c_with_cancelling_naturals() -> None:
    dec, systems = _decisions([1, 0, 0])
    for v in VOICES[:3]:
        systems[(1, 2)][f"p1s2{v}"] = (v, TREBLE + ["accidental.natural-L5", "note.quarter-L2"])
    out = s3ck.apply_key_continuity(dec, systems, set())
    assert _keys(out, 3) == [1, 0, 0]


def test_courtesy_signature_corroborates() -> None:
    dec, systems = _decisions([0, 1, 0])
    for v in VOICES[:3]:
        systems[(1, 1)][f"p1s1{v}"] = (v, TREBLE + ["note.quarter-L2", BAR, "accidental.sharp-L5"])
    out = s3ck.apply_key_continuity(dec, systems, set())
    assert _keys(out, 3)[1] == 1


def test_uncorroborated_change_on_last_system_accepted_with_flag() -> None:
    dec, systems = _decisions([2, 1])
    out = s3ck.apply_key_continuity(dec, systems, set())
    assert _keys(out, 2) == [2, 1]
    assert s3ck.KEY_CHANGE_UNVERIFIABLE_FLAG in out["p1s2Soprano"].flags
    assert out["p1s2Soprano"].key_candidates == [1, 2]


def test_no_majority_carries_revised_key() -> None:
    dec, systems = _decisions([3, 0, None, 3])
    for sid, d in dec.items():
        if d.vote_key is None:
            d.key = 0        # decide() carried its unrevised chain
    out = s3ck.apply_key_continuity(dec, systems, set())
    assert _keys(out, 4) == [3, 3, 3, 3]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
