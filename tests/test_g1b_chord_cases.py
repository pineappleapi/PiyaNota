"""G1b chord-case classifier on token lists (divisi A6 Task 4)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "phase1"))
import g1b_page  # noqa: E402
from g1b_page import chord_case_columns, chord_cases  # noqa: E402


def test_whole_second() -> None:
    assert "chord_whole_second" in chord_cases(["note.whole-L2", "chordnote-S2"])


def test_second_needs_stem_and_follows_it() -> None:
    tokens = ["note.quarter-L2", "chordnote-S2"]
    assert not {"chord_second_up", "chord_second_down"} & chord_cases(tokens)
    assert "chord_second_up" in chord_cases(tokens, {0: "up"})
    assert "chord_second_down" in chord_cases(tokens, {0: "down"})
    assert "chord_whole_second" not in chord_cases(tokens, {0: "up"})


def test_second_stem_is_per_column() -> None:
    tokens = ["note.quarter-L1", "chordnote-L2", "note.quarter-L2", "chordnote-S2"]
    cols = chord_case_columns(tokens, {0: "up", 1: "down"})
    assert cols == {"chord_second_down": 1}


def test_seventh_is_six_steps() -> None:
    assert "chord_seventh" in chord_cases(["note.quarter-L1", "chordnote-L4"])
    assert "chord_seventh" not in chord_cases(["note.quarter-L1", "chordnote-S3"])   # 6th
    assert "chord_seventh" not in chord_cases(["note.quarter-L1", "chordnote-S4"])   # octave


def test_cluster_is_triad_with_second() -> None:
    assert "chord_cluster" in chord_cases(["note.half-L2", "chordnote-S2", "chordnote-S3"])
    assert "chord_cluster" not in chord_cases(["note.half-L2", "chordnote-L3", "chordnote-L4"])
    assert "chord_cluster" not in chord_cases(["note.half-L2", "chordnote-S2"])


def test_triad_accidental_only_on_triads() -> None:
    triad = ["accidental.sharp-L3", "note.quarter-L2", "chordnote-L3", "chordnote-L4"]
    assert "chord_triad_accidental" in chord_cases(triad)
    assert "chord_triad_accidental" not in chord_cases(["accidental.sharp-L3", "note.quarter-L2", "chordnote-L3"])
    elsewhere = ["accidental.sharp-L5", "note.quarter-L2", "chordnote-L3", "chordnote-L4"]
    assert "chord_triad_accidental" not in chord_cases(elsewhere)


def test_ledger_above_and_below() -> None:
    assert "chord_ledger_above" in chord_cases(["note.quarter-L6", "chordnote-S6"])
    assert "chord_ledger_above" not in chord_cases(["note.quarter-L4", "chordnote-S5"])
    assert "chord_ledger_below" in chord_cases(["note.quarter-L0", "chordnote-L2"])
    assert "chord_ledger_below" in chord_cases(["note.quarter-S-1", "chordnote-L2"])
    assert "chord_ledger_below" not in chord_cases(["note.quarter-S0", "chordnote-L2"])


def test_ledger_head_may_be_the_base_note() -> None:
    assert "chord_ledger_above" in chord_cases(["note.quarter-L3", "chordnote-L6"])


def test_tie_marks_next_to_chord() -> None:
    after = ["note.half-L2", "chordnote-L4", "slur.start-L4", "barline", "slur.end-L4"]
    assert "chord_tie" in chord_cases(after)
    assert "chord_tie" not in chord_cases(["note.half-L2", "chordnote-L4", "barline"])
    assert "chord_tie" in chord_cases(["slur.end-L4", "note.half-L2", "chordnote-L4"])


def test_a6_cases_listed_and_labelled() -> None:
    assert set(g1b_page.A6_CHORD_CASES) <= set(g1b_page.CASES)
    assert len(g1b_page.A6_CHORD_CASES) == 9
