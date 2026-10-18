"""Duration classifier of the A6 feasibility count (PIYA-106)."""

import sys
from pathlib import Path

import music21
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "phase1"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from divisi_a6_feasibility import duration_class, is_chord_capable  # noqa: E402


@pytest.mark.parametrize("quarter_length,expected", [
    (4.0, "whole"), (2.0, "half"), (1.0, "quarter"), (0.5, "beamed"), (0.25, "beamed"),
    (3.0, "dotted"), (1.5, "dotted"), (6.0, "dotted"), (8.0, "other")])
def test_duration_class(quarter_length: float, expected: str) -> None:
    assert duration_class(music21.duration.Duration(quarterLength=quarter_length)) == expected


def test_chord_capable_excludes_tied_grace_tuplet() -> None:
    plain = music21.note.Note("C4")
    tied = music21.note.Note("C4")
    tied.tie = music21.tie.Tie("start")
    grace = music21.note.Note("C4").getGrace()
    triplet = music21.note.Note("C4", quarterLength=1 / 3)
    assert is_chord_capable(plain)
    assert not any(is_chord_capable(n) for n in (tied, grace, triplet))
