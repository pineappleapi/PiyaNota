"""A7 tuning-half extras: triad 2+ share, dyad guard, middle/top, tie token, layer.split bars."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase2"))
import eval_divisi_a7 as e7  # noqa: E402

GT = ["clef.G-L2", "note.half-L2", "chordnote-L3", "chordnote-L4", "slur.start-L2", "barline-L1",
      "layer.split", "note.half-L2", "chordnote-L4", "note.whole.l2-S1", "barline-L1", "note.whole-L3"]


def test_perfect_read() -> None:
    x = e7.a7_extras(GT, GT)
    assert x["triad_2plus"] == [1, 1] and x["dyad_2plus"] == [0, 1]
    assert x["middle"] == [1, 1] and x["top"] == [1, 1] and x["tie_token"] == [1, 1]
    assert (x["layer_tp"], x["layer_gt"], x["layer_pred"], x["layer_fp_single"], x["single_bars"]) == (1, 1, 1, 0, 2)


def test_triad_read_as_dyad_and_lost_layer() -> None:
    pred = ["clef.G-L2", "note.half-L2", "chordnote-L4", "barline-L1", "note.half-L2", "chordnote-L4", "chordnote-L5",
            "note.whole.l2-S1", "barline-L1", "layer.split", "note.whole-L3"]
    x = e7.a7_extras(pred, GT)
    assert x["triad_2plus"] == [0, 1] and x["dyad_2plus"] == [1, 1]   # dyad emitting 2 chordnotes: the guard
    assert x["middle"] == [0, 1] and x["top"] == [1, 1] and x["tie_token"] == [0, 1]
    assert (x["layer_tp"], x["layer_fp_single"]) == (0, 1)
    s = e7.stop_checks({**x, "bucket": {}}, "CL")
    assert not s["chords_pass"] and not s["layers_pass"] and s["layer_false_on_single"] == 0.5


def test_bar_count_mismatch_scores_misses() -> None:
    x = e7.a7_extras([t for t in GT if t != "barline-L1"], GT)
    assert x["bars_misaligned_strips"] == 1 and x["layer_tp"] == 0 and x["layer_gt"] == 1
