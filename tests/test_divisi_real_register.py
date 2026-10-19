"""Tests for the real camera divisi test-set registration (PIYA-106, plan 2026-10-19 Task 2)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from divisi_real_register import load_training_pieces, register  # noqa: E402

TRAINING = {"bach_bwv10.7", "bach_bwv66.6"}


def _setup(tmp_path: Path, rows: list[str]) -> tuple[Path, Path]:
    photos = tmp_path / "photos"
    photos.mkdir()
    for name in ("p1.jpg", "p2.jpg"):
        (photos / name).write_bytes(name.encode())
    meta = tmp_path / "meta.csv"
    meta.write_text("piece,publisher,page,gt_kinds\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return photos, meta


def test_registration_rejects_training_piece(tmp_path: Path) -> None:
    photos, meta = _setup(tmp_path, ["Bach_BWV66.6,Breitkopf,p1.jpg,same_stem"])
    with pytest.raises(ValueError, match="training"):
        register(photos, meta, TRAINING, tmp_path / "registry.json")


def test_gt_kind_required(tmp_path: Path) -> None:
    photos, meta = _setup(tmp_path, ["ave_verum,Novello,p1.jpg,"])
    with pytest.raises(ValueError, match="gt_kind"):
        register(photos, meta, TRAINING, tmp_path / "registry.json")
    (tmp_path / "b").mkdir()
    photos2, meta2 = _setup(tmp_path / "b", ["ave_verum,Novello,p1.jpg,chorded"])
    with pytest.raises(ValueError, match="gt_kind"):
        register(photos2, meta2, TRAINING, tmp_path / "b" / "registry.json")


def test_registry_groups_pages_and_hashes(tmp_path: Path) -> None:
    photos, meta = _setup(tmp_path, ["ave_verum,Novello,p1.jpg,same_stem",
                                     "ave_verum,Novello,p2.jpg,split_same_rhythm;same_stem"])
    reg = register(photos, meta, TRAINING, tmp_path / "registry.json")
    assert reg["frozen"] is False
    (piece,) = reg["pieces"]
    assert piece["pages"] == ["p1.jpg", "p2.jpg"]
    assert piece["gt_kinds"] == ["same_stem", "split_same_rhythm"]
    assert len(piece["sha256"]["p1.jpg"]) == 64
    assert json.loads((tmp_path / "registry.json").read_text(encoding="utf-8")) == reg


def test_frozen_registry_immutable(tmp_path: Path) -> None:
    photos, meta = _setup(tmp_path, ["ave_verum,Novello,p1.jpg,same_stem"])
    out = tmp_path / "registry.json"
    register(photos, meta, TRAINING, out, freeze=True)
    assert register(photos, meta, TRAINING, out)["frozen"] is True     # unchanged: re-registering is a no-op
    (photos / "p1.jpg").write_bytes(b"retaken")
    with pytest.raises(ValueError, match="frozen"):
        register(photos, meta, TRAINING, out)


def test_missing_photo_rejected(tmp_path: Path) -> None:
    photos, meta = _setup(tmp_path, ["ave_verum,Novello,p9.jpg,same_stem"])
    with pytest.raises(ValueError, match="p9.jpg"):
        register(photos, meta, TRAINING, tmp_path / "registry.json")


def test_load_training_pieces_strips_divisi_suffix(tmp_path: Path) -> None:
    manifest = tmp_path / "m.jsonl"
    manifest.write_text('{"piece": "bach_bwv10.7"}\n{"piece": "bach_bwv10.7__divisi"}\n', encoding="utf-8")
    assert load_training_pieces(manifest) == {"bach_bwv10.7"}
