"""Tune-group halves (A6.1): transposed copies join, titles join, a group is never split."""
import json
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase1"))
import divisi_halves as dh  # noqa: E402

TUNE = [2, 2, -4, 2, 2, -4, 5, -1, -2, 2, 2, -4, 2, 2, -3]       # 15 intervals
OTHER = [-1, -2, 5, 2, 2, 1, -3, 4, 4, -2, -2, 7, 1]


def test_transposed_copy_joins_the_same_group():
    # bwv312 is bwv311 a fourth up: same intervals, every pitch moved.
    groups = dh.tune_groups(["bach_bwv311", "bach_bwv312", "bach_bwv400"],
                            {"bach_bwv311": TUNE, "bach_bwv312": list(TUNE), "bach_bwv400": OTHER})
    assert groups["bach_bwv311"] == groups["bach_bwv312"] == "bach_bwv311"
    assert groups["bach_bwv400"] == "bach_bwv400"


def test_only_the_first_twelve_intervals_count_and_short_melodies_use_all():
    tail_differs = TUNE[:12] + [9, 9, 9]
    short = TUNE[:7]
    groups = dh.tune_groups(["a", "b", "c", "d"], {"a": TUNE, "b": tail_differs, "c": short, "d": list(short)})
    assert groups["a"] == groups["b"] == "a"
    assert groups["c"] == groups["d"] == "c" and groups["c"] != groups["a"]


def test_same_title_joins_and_melodyless_pieces_stay_alone():
    groups = dh.tune_groups(["p1", "p2", "p3", "p4"], {"p1": TUNE, "p2": OTHER, "p3": [], "p4": []},
                            titles={"p1": "o haupt", "p2": "o haupt", "p3": None, "p4": None})
    assert groups["p1"] == groups["p2"] == "p1"
    assert groups["p3"] == "p3" and groups["p4"] == "p4"


def test_chain_through_hash_and_title_takes_the_smallest_id():
    groups = dh.tune_groups(["z", "m", "a"], {"z": TUNE, "m": TUNE, "a": OTHER}, titles={"m": "t", "a": "t"})
    assert set(groups.values()) == {"a"}


def test_half_is_a_function_of_the_group_with_the_old_crc_input():
    groups = {"bach_x": "bach_g", "bach_y": "bach_g", "bach_solo": "bach_solo"}
    assert dh.is_test_half("bach_x", groups) == dh.is_test_half("bach_y__divisi", groups)
    assert dh.is_test_half("bach_x", groups) == (zlib.crc32(b"bach_g__divisi") % 2 == 1)
    assert dh.is_test_half("bach_solo", groups) == (zlib.crc32(b"bach_solo__divisi") % 2 == 1)


def test_unknown_piece_raises_instead_of_falling_back():
    with pytest.raises(KeyError):
        dh.is_test_half("bach_missing", {"bach_x": "bach_x"})


def test_report_flags_test_pieces_that_share_a_tune_with_train(tmp_path):
    ids = [f"bach_{i:03d}" for i in range(40)]
    melodies = {p: [i % 7, i % 5, i % 3, i % 11, 1, 2, 3, 4, 5, 6, 7, 8] for i, p in enumerate(ids)}
    groups = dh.tune_groups(ids, melodies)
    split_of = {p: ("val" if i % 4 == 0 else "train") for i, p in enumerate(ids)}
    rep = dh.halves_report(groups, split_of)
    val = {p for p, s in split_of.items() if s == "val"}
    assert set(rep["half_of"]) == val
    for key, members in rep["groups"].items():
        assert len({rep["half_of"].get(m) for m in members if m in val}) <= 1    # a group is never split
    for p, shared in rep["test_group_has_train_piece"].items():
        assert shared == any(split_of[q] == "train" for q in rep["groups"][groups[p]])
    path = tmp_path / "halves.json"
    path.write_text(json.dumps(rep), encoding="utf-8")
    assert dh.load_groups(path) == groups
    assert dh.load_clean_test_pieces(path) == {p for p, s in rep["test_group_has_train_piece"].items() if not s}
