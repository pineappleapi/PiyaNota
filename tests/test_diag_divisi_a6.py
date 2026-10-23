"""Tests for training/phase2/diag_divisi_a6.py on hand-made token lists (no checkpoints or renders)."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "training" / "phase2"))
import diag_divisi_a6 as dg  # noqa: E402

GT = ["clef.G-L2", "note.half-L1", "chordnote-L3", "chordnote-L5", "barline-L1", "note.half-L2"]


def _m(out, k):
    return [m[k] for m in out["members"]]


def test_triad_member_positions_and_miss():
    pred = ["clef.G-L2", "note.half-L1", "chordnote-L5", "barline-L1", "note.half-L2"]   # middle dropped
    out = dg.triad_breakdown(pred, GT, {1: 3.0, 4: 9.0})
    assert sorted(zip(_m(out, "pos"), _m(out, "hit"))) == [("middle", False), ("top", True)]
    assert _m(out, "gap") == [3.0, 3.0] and _m(out, "has_2nd") == [False, False]
    assert _m(out, "n_pred_ext") == [1, 1] and _m(out, "dur") == ["note.half", "note.half"]


def test_has_2nd_flags_cluster():
    gt = ["note.half-L1", "chordnote-S1", "chordnote-L3"]                  # steps 0, 1, 4
    out = dg.triad_breakdown(["note.half-L1", "chordnote-L3"], gt, {0: 6.0})
    assert _m(out, "has_2nd") == [True, True]


def test_unaligned_triad_counts_all_missed():
    out = dg.triad_breakdown(["clef.G-L2", "barline-L1"], GT, {})
    assert _m(out, "hit") == [False, False] and _m(out, "gap") == [None, None]


def test_gap_none_when_next_base_token_misread():
    pred = ["clef.G-L2", "note.half-L1", "chordnote-L3", "chordnote-L5", "rest.half-L3", "note.half-L2"]
    out = dg.triad_breakdown(pred, GT, {1: 3.0, 5: 9.0})
    assert _m(out, "gap") == [None, None] and _m(out, "hit") == [True, True]


def test_gap_ignores_preceding_accidental_and_runs_to_strip_end():
    pred = ["accidental.sharp-L3", "note.half-L1", "chordnote-L3", "note.half-L2"]
    spans = [(0, 4), (8, 12), (12, 16), (40, 44)]
    assert dg.frame_gaps(pred, spans, strip_height=64, strip_width=100) == {1: (40 - 8) / 4, 3: (100 - 40) / 4}


def test_gap_skips_dot_and_scales_height():
    pred = ["note.half-L1", "chordnote-L3", "dot-S3", "barline-L1"]
    assert dg.frame_gaps(pred, [(0, 4), (4, 8), (8, 12), (20, 24)], 64, 100)[0] == 20 / 4
    assert dg.frame_gaps(pred, [(0, 8), (8, 16), (16, 24), (40, 48)], 128, 200)[0] == 20 / 4   # 2x strip


def test_ledger_rows_flag_triad_membership():
    gt = ["note.half-L1", "chordnote-L7"]                                  # L7 = step 12, 2 ledger lines
    out = dg.triad_breakdown(["note.half-L1"], gt, {0: 5.0})
    assert out["ledger"] == [{"gi": 0, "lines": 2, "in_triad": False, "hit": False}]


def _mem(piece, hit, gap=6.0, has_2nd=False, dur="note.half"):
    return {"piece": piece, "hit": hit, "gap": gap, "has_2nd": has_2nd, "dur": dur, "gi": 0, "n_pred_ext": 2}


def test_ratio_and_none_group():
    ms = [_mem("a", False, 2), _mem("a", True, 2), _mem("b", False, 8), _mem("b", True, 8), _mem("b", True, 8),
          _mem("b", True, 8), _mem("c", False, None)]
    assert dg.ratio(ms, lambda m: None if m["gap"] is None else m["gap"] <= 4) == 0.5 / 0.25


def test_ratio_none_when_complement_never_misses():
    assert dg.ratio([_mem("a", False, 2), _mem("b", True, 8)], lambda m: m["gap"] <= 4) is None


def test_boot_ci_skips_undefined_resamples():
    ms = [_mem("a", False, 2), _mem("b", True, 8), _mem("c", False, 8)]
    lo, hi = dg.boot_ci(ms, lambda s: dg.ratio(s, lambda m: m["gap"] <= 4), b=200)
    assert lo <= hi


def test_verdict_clear_frame_gap_routes_crop():
    ms = [_mem(p, i % 4 == 0, gap=2.0) for p in "abcdefghijklmn" for i in range(20)]     # tight: 75% miss
    ms += [_mem(p, i % 10 != 0, gap=8.0) for p in "abcdefghijklmn" for i in range(40)]   # wide: 10% miss
    v = dg.verdict(ms, [])
    assert v["r1a"] and v["route"] == "A7-crop"


def test_cli_refuses_test_half():
    r = subprocess.run([sys.executable, "-I", str(REPO / "training/phase2/diag_divisi_a6.py"), "--build", "x",
                        "--halves", "x", "--half", "test", "--ckpt", "a=b", "--out", "o.json"], capture_output=True)
    assert r.returncode != 0 and b"tuning half only" in r.stderr
