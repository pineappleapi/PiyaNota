"""Per-interval chordnote metrics and second_as_sequence (divisi freeze A3)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase2"))

from train_phase2 import chordnote_metrics, wilson95  # noqa: E402

SECOND = ["note.quarter-L2", "chordnote-S2"]


def test_second_read_as_chord_is_a_hit() -> None:
    m = chordnote_metrics([(SECOND, SECOND)])
    assert m["by_interval"]["2nd"]["gt"] == 1 and m["by_interval"]["2nd"]["hit"] == 1
    assert m["by_interval"]["2nd"]["recall"] == 1.0 and m["second_as_sequence"] == 0


def test_second_read_as_two_notes_is_counted() -> None:
    m = chordnote_metrics([(["note.quarter-L2", "note.quarter-S2"], SECOND)])
    assert m["by_interval"]["2nd"]["recall"] == 0.0 and m["second_as_sequence"] == 1


def test_interval_buckets() -> None:
    gt = ["note.half-L1", "chordnote-L2", "note.half-L1", "chordnote-S2", "note.half-L1", "chordnote-S4",
          "note.half-L1", "chordnote-L5", "note.half-S0", "chordnote-L3", "chordnote-L4"]
    m = chordnote_metrics([(gt, gt)])
    got = {k: v["gt"] for k, v in m["by_interval"].items() if v["gt"]}
    # L1-L2 3rd, L1-S2 4th, L1-S4 8ve, L1-L5 9th (other), S0-L3 6th, L3-L4 3rd (triad: vs the head below)
    assert got == {"3rd": 2, "4th5th": 1, "8ve": 1, "other": 1, "6th": 1}


def test_existing_keys_unchanged() -> None:
    m = chordnote_metrics([(SECOND, SECOND)])
    assert m["chordnote_recall"] == 1.0 and m["chordnote_precision"] == 1.0 and m["chordnote_gt"] == 1


def test_wilson95() -> None:
    lo, hi = wilson95(8, 10)
    assert lo == pytest.approx(0.490, abs=0.002) and hi == pytest.approx(0.943, abs=0.002)
    assert wilson95(0, 0) is None
