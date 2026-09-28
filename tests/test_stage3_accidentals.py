"""Regression tests for the Stage 3 accidental fixes (PIYA-106, BUG-024).

F1  a mid-strip key change needs a burst of >= 2 accidentals in engraving order;
    anything else after a barline is an inline candidate.
F2  an inline accidental holds for that step until the barline; a tie across the
    barline keeps it for the tied note only.
F3  an inline accidental is absolute (a flat on B in F major is still B-flat,
    not B-double-flat; a natural cancels the key).
PM  an inline accidental only applies when the next note sits on its position;
    measured sharp precision on camera strips was 26-36%, so unanchored ones are
    treated as phantoms.

Run with ``python tests/test_stage3_accidentals.py``. Synthetic token-level tests:
they say nothing about CRNN accuracy.
"""

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage3_transcription as s3  # noqa: E402

TREBLE = ["clef.G-L2"]
BASS = ["clef.F-L4"]
BAR = "barline-L1"

# Treble-clef MIDI pitches for the positions used below.
G4, B4, B_FLAT4, C5, C_SHARP5, F5, F_SHARP5 = 67, 71, 70, 72, 73, 77, 78
B2, B_FLAT2 = 47, 46


def _pitches(tokens: list, voice: str = "Soprano") -> list:
    with contextlib.redirect_stdout(io.StringIO()):
        events = s3.infer_pitch(tokens, voice=voice, page_index=1, sys_idx=1)
    return [e["pitch"] for e in events if e["type"] == "note"]


# ── key signature / F1 ───────────────────────────────────────────────────────

def test_opening_key_signature_applies() -> None:
    tokens = TREBLE + ["accidental.sharp-L5", "accidental.sharp-S3",
                       "note.quarter-L5", "note.quarter-S3"]
    assert _pitches(tokens) == [F_SHARP5, C_SHARP5]


def test_bass_clef_flat_key_signature() -> None:
    assert _pitches(BASS + ["accidental.flat-L2", "note.quarter-L2"], voice="Bass") == [B_FLAT2]


def test_mid_strip_burst_in_order_is_key_change() -> None:
    tokens = TREBLE + ["note.quarter-L5", BAR,
                       "accidental.sharp-L5", "accidental.sharp-S3",
                       "note.quarter-L2", "note.quarter-L5", BAR, "note.quarter-S3"]
    assert _pitches(tokens) == [F5, G4, F_SHARP5, C_SHARP5]


def test_single_unanchored_accidental_after_barline_is_dropped() -> None:
    tokens = TREBLE + ["note.quarter-L2", BAR, "accidental.sharp-L5",
                       "note.quarter-L2", "note.quarter-L5"]
    assert _pitches(tokens) == [G4, G4, F5]


def test_single_anchored_accidental_after_barline_is_inline() -> None:
    tokens = TREBLE + ["note.quarter-L2", BAR, "accidental.sharp-L5",
                       "note.quarter-L5", BAR, "note.quarter-L5"]
    assert _pitches(tokens) == [G4, F_SHARP5, F5]


def test_burst_with_note_on_last_position_is_inline_not_key_change() -> None:
    tokens = TREBLE + ["note.quarter-L2", BAR,
                       "accidental.sharp-L5", "accidental.sharp-S3",
                       "note.quarter-S3", "note.quarter-L5", BAR, "note.quarter-S3"]
    assert _pitches(tokens) == [G4, C_SHARP5, F5, C5]


def test_out_of_order_burst_is_not_key_change() -> None:
    tokens = TREBLE + ["note.quarter-L2", BAR,
                       "accidental.sharp-S3", "accidental.sharp-L5",
                       "note.quarter-L2", "note.quarter-S3"]
    assert _pitches(tokens) == [G4, G4, C5]


def test_key_change_kept_when_first_note_carries_last_glyph() -> None:
    # 2# key change, then a G#5 whose sharp directly follows the key signature (senior-reviewer probe).
    tokens = TREBLE + ["note.quarter-L2", BAR, "accidental.sharp-L5", "accidental.sharp-S3",
                       "accidental.sharp-S5", "note.quarter-S5", "note.quarter-L5", "note.quarter-S3"]
    assert _pitches(tokens) == [G4, 80, F_SHARP5, C_SHARP5]


def test_naturals_then_flats_switch_sharp_key_to_flat_key() -> None:
    # 2# (D) -> 3b (Eb), the common "up a step" modulation: E5 becomes Eb5 and F#5 becomes F5.
    tokens = TREBLE + ["accidental.sharp-L5", "accidental.sharp-S3", "note.quarter-L2", BAR,
                       "accidental.natural-L5", "accidental.natural-S3", "accidental.flat-L3",
                       "accidental.flat-S4", "accidental.flat-S2", "note.quarter-S4", "note.quarter-L5"]
    assert _pitches(tokens) == [G4, 75, F5]


def test_natural_then_sharp_switches_flat_key_to_sharp_key() -> None:
    tokens = TREBLE + ["accidental.flat-L3", "note.quarter-L3", BAR,
                       "accidental.natural-L3", "accidental.sharp-L5",
                       "note.quarter-L2", "note.quarter-L5", "note.quarter-L3"]
    assert _pitches(tokens) == [B_FLAT4, G4, F_SHARP5, B4]


def test_naturals_alone_cancel_tail_of_old_key() -> None:
    # 3b -> 1b: Eb and Ab cancelled, Bb kept.
    tokens = TREBLE + ["accidental.flat-L3", "accidental.flat-S4", "accidental.flat-S2",
                       "note.quarter-L2", BAR, "accidental.natural-S4", "accidental.natural-S2",
                       "note.quarter-L3", "note.quarter-S4", "note.quarter-S2"]
    assert _pitches(tokens) == [G4, B_FLAT4, 76, 69]


def test_naturals_cancel_whole_key_to_c_major() -> None:
    tokens = TREBLE + ["accidental.sharp-L5", "accidental.sharp-S3", "note.quarter-L2", BAR,
                       "accidental.natural-L5", "accidental.natural-S3",
                       "note.quarter-L2", "note.quarter-L5", "note.quarter-S3"]
    assert _pitches(tokens) == [G4, G4, F5, C5]


def test_naturals_off_key_positions_are_not_key_change() -> None:
    tokens = TREBLE + ["accidental.sharp-L5", "accidental.sharp-S3", "note.quarter-L2", BAR,
                       "accidental.natural-L2", "accidental.natural-L3",
                       "note.quarter-L5", "note.quarter-S3"]
    assert _pitches(tokens) == [G4, F_SHARP5, C_SHARP5]


# ── position match (PM) ──────────────────────────────────────────────────────

def test_phantom_accidental_on_other_position_is_ignored() -> None:
    tokens = TREBLE + ["note.quarter-L2", "accidental.sharp-L4", "note.quarter-L3"]
    assert _pitches(tokens) == [G4, B4]


def test_accidental_not_anchored_across_barline() -> None:
    tokens = TREBLE + ["note.quarter-L2", "accidental.sharp-L3", BAR, "note.quarter-L3"]
    assert _pitches(tokens) == [G4, B4]


# ── measure memory (F2) ──────────────────────────────────────────────────────

def test_inline_accidental_carries_to_end_of_measure() -> None:
    tokens = TREBLE + ["note.quarter-L2", "accidental.sharp-S3", "note.quarter-S3",
                       "note.quarter-S3", BAR, "note.quarter-S3"]
    assert _pitches(tokens) == [G4, C_SHARP5, C_SHARP5, C5]


def test_tie_across_barline_keeps_alteration_for_tied_note_only() -> None:
    tokens = TREBLE + ["note.quarter-L2", "accidental.sharp-S3", "slur.start-S3",
                       "note.quarter-S3", BAR,
                       "slur.end-S3", "note.quarter-S3", "note.quarter-S3"]
    assert _pitches(tokens) == [G4, C_SHARP5, C_SHARP5, C5]


def test_inherited_accidental_keeps_its_confidence() -> None:
    tokens = TREBLE + ["note.quarter-L2", "accidental.sharp-S3", "note.quarter-S3", "note.quarter-S3",
                       BAR, "note.quarter-S3"]
    confs = [1.0, 0.9, 0.2, 0.9, 0.9, 1.0, 0.9]
    with contextlib.redirect_stdout(io.StringIO()):
        events = s3.infer_pitch(tokens, voice="Soprano", page_index=1, sys_idx=1, confidences=confs)
    assert [round(e["confidence"], 2) for e in events] == [0.9, 0.2, 0.2, 0.9]


# ── absolute accidentals (F3) ────────────────────────────────────────────────

def test_flat_in_key_with_that_flat_is_not_double_flat() -> None:
    tokens = TREBLE + ["accidental.flat-L3", "note.quarter-L2",
                       "accidental.flat-L3", "note.quarter-L3"]
    assert _pitches(tokens) == [G4, B_FLAT4]


def test_natural_cancels_key_signature_for_the_measure() -> None:
    tokens = TREBLE + ["accidental.flat-L3", "note.quarter-L3",
                       "accidental.natural-L3", "note.quarter-L3", "note.quarter-L3",
                       BAR, "note.quarter-L3"]
    assert _pitches(tokens) == [B_FLAT4, B4, B4, B_FLAT4]


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("ok", name)
            except AssertionError as exc:
                failures += 1
                print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
