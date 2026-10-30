"""A7 design 14.8: dyad_train.2nd_none is waived only at the reviewed count; any other count still fails."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase1"))
import divisi_a7_gates as g  # noqa: E402


def _build(tmp_path: Path, n_none: int) -> Path:
    (tmp_path / "corpus").mkdir(parents=True)
    plan = {"split": "train", "divisi": {"class": {"S:2nd_none": n_none, "A:3rd": 100}}}
    (tmp_path / "corpus" / "p.plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(("n_none", "status"), [(257, "warn"), (256, "fail"), (281, "fail")])
def test_waiver_needs_exact_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, n_none: int, status: str) -> None:
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps({"class_counts": {"2nd_none": 281, "3rd": 100}}), encoding="utf-8")
    monkeypatch.setattr(g, "A6V2_REFERENCE", ref)
    gates = {x["name"]: x["status"] for x in g.dyad_train_gates(_build(tmp_path / "b", n_none))}
    assert gates == {"dyad_train.2nd_none": status, "dyad_train.3rd": "pass"}
