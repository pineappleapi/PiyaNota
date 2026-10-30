"""Counting logic of the divisi accidental check (no PDF needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase1"))
import accid_check as ac  # noqa: E402


def test_label_bars_header_counts_in_bar_one() -> None:
    toks = ["clef.G-L2", "accidental.flat-L3", "accidental.flat-S1", "note.quarter-S0", "barline-L1",
            "accidental.sharp-L2", "note.half-L1", "barline-L1"]
    assert ac.label_bar_counts(toks) == [2, 1]


def test_label_trailing_courtesy_after_last_barline_is_a_bar() -> None:
    assert ac.label_bar_counts(["note.quarter-S0", "barline-L1", "accidental.flat-L3"]) == [0, 1]


def test_pdf_bars_and_compare() -> None:
    assert ac.pdf_bar_counts([10.0, 11.0, 60.0], [5.0, 50.0, 100.0], 5.0, 101.0) == [2, 1]
    assert ac.compare_bars([2, 1], [2, 2]) == [1]
    assert ac.compare_bars([2], [2, 1]) is None


def test_consensus_drops_stems() -> None:
    assert ac.consensus_barlines([[10.0, 50.0], [10.2, 80.0], [9.8, 50.5]]) == [9.8, 50.0]
