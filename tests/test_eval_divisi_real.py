"""Tests for the real camera divisi scorer (PIYA-106, plan 2026-10-19 Task 3) on hand-made token lists."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase2"))
from eval_divisi_real import score, second_as_sequence  # noqa: E402


def _write(tmp: Path, frozen: bool, gt: list[dict[str, object]], pred: list[dict[str, object]]) -> tuple[Path, Path, Path]:
    reg = tmp / "registry.json"
    reg.write_text(json.dumps({"frozen": frozen, "pieces": [{"piece": "ave", "publisher": "N", "pages": ["p1.jpg"],
                                                              "gt_kinds": ["same_stem"], "sha256": {}}]}))
    (tmp / "gt").mkdir()
    (tmp / "pred").mkdir()
    (tmp / "gt" / "ave.json").write_text(json.dumps({"strips": gt}))
    (tmp / "pred" / "ave.json").write_text(json.dumps({"strips": pred}))
    return reg, tmp / "pred", tmp / "gt"


def _strip(tokens: list[str], kind: str = "same_stem", conf: list[float] | None = None) -> dict[str, object]:
    s: dict[str, object] = {"page": "p1.jpg", "staff": 0, "tokens": tokens}
    if kind:
        s["gt_kind"] = kind
    if conf is not None:
        s["conf"] = conf
    return s


def test_sequence_read_is_miss() -> None:
    gt = ["note.quarter-L2", "chordnote-S2"]
    assert second_as_sequence(["note.quarter-L2", "note.quarter-S2"], gt) == 1
    assert second_as_sequence(["note.quarter-L2", "chordnote-S2"], gt) == 0


def test_sequence_read_scored_as_miss(tmp_path: Path) -> None:
    reg, pred, gt = _write(tmp_path, True, [_strip(["note.quarter-L2", "chordnote-S2"])],
                           [_strip(["note.quarter-L2", "note.quarter-S2"], kind="")])
    out = score(reg, pred, gt)
    b = out["buckets"]["same_stem:2nd_up"]
    assert (b["n"], b["recall"]) == (1, 0.0)
    assert out["kinds"]["same_stem"]["second_as_sequence"] == 1


def test_gt_kinds_scored_separately(tmp_path: Path) -> None:
    reg, pred, gt = _write(tmp_path, True,
                           [_strip(["note.half-L1", "chordnote-L2"], kind="split_same_rhythm")],
                           [_strip(["note.half-L1", "chordnote-L2"], kind="")])
    out = score(reg, pred, gt)
    assert "same_stem:3rd" not in out["buckets"]
    assert out["buckets"]["split_same_rhythm:3rd"]["n"] == 1
    assert out["kinds"].get("same_stem", {"heads": 0})["heads"] == 0


def test_underpowered_bucket(tmp_path: Path) -> None:
    gt_s = [dict(_strip(["note.half-L1", "chordnote-L2"]), staff=i) for i in range(40)]
    pred_s = [dict(_strip(["note.half-L1", "chordnote-L2"], kind=""), staff=i) for i in range(40)]
    reg, pred, gt = _write(tmp_path, True, gt_s, pred_s)
    b = score(reg, pred, gt)["buckets"]["same_stem:3rd"]
    assert (b["n"], b["recall"], b["verdict"]) == (40, 1.0, "UNDERPOWERED")
    assert 0.0 < b["wilson95"][0] < 1.0 and b["wilson95"][1] == pytest.approx(1.0)


def test_confident_wrong_counted(tmp_path: Path) -> None:
    reg, pred, gt = _write(tmp_path, True, [_strip(["note.half-L1", "chordnote-L2"])],
                           [_strip(["note.half-L1", "chordnote-L3"], kind="", conf=[0.99, 0.95])])
    k = score(reg, pred, gt)["kinds"]["same_stem"]
    assert k["confident_wrong_090"] == 1
    assert k["precision"] == pytest.approx(0.5)


def test_missing_prediction_counts_as_miss(tmp_path: Path) -> None:
    reg, pred, gt = _write(tmp_path, True, [_strip(["note.half-L1", "chordnote-L2"])], [])
    out = score(reg, pred, gt)
    assert out["buckets"]["same_stem:3rd"]["recall"] == 0.0
    assert out["missing_strips"] == 1


def test_refuses_unfrozen_registry(tmp_path: Path) -> None:
    reg, pred, gt = _write(tmp_path, False, [_strip(["note.half-L1"])], [_strip(["note.half-L1"], kind="")])
    with pytest.raises(ValueError, match="frozen"):
        score(reg, pred, gt)
