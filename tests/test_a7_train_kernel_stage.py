"""A7 GPU kernel + staging helper: copies differ only in ARM/SEED, PLACEHOLDER pins refused, real staging exact."""
import importlib.util
import json
from pathlib import Path

import pytest

KDIR = Path(__file__).resolve().parents[1] / "training" / "phase2" / "kaggle" / "divisi_a7"


def _load(name: str, fname: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, KDIR / fname)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kernel = _load("a7_kernel", "phase2_divisi_a7_kernel.py")
stage = _load("a7_stage", "stage_datasets.py")


def test_copies_differ_only_in_arm_seed(tmp_path: Path) -> None:
    names = stage.stage_kernels(tmp_path)
    assert sorted(names) == sorted(f"piyanota-divisi-a7-train-{a}-s{s}" for a in ("c", "cl") for s in (1, 2))
    template = (KDIR / "phase2_divisi_a7_kernel.py").read_text(encoding="utf-8")
    for n in names:
        text = (tmp_path / n / "phase2_divisi_a7_kernel.py").read_text(encoding="utf-8")
        arm, seed = n.split("-")[-2], int(n[-1])
        assert f'ARM = "{arm.upper()}"' in text and f"SEED = {seed}" in text
        stage.assert_only_arm_seed_differ(template, text)
        meta = json.loads((tmp_path / n / "kernel-metadata.json").read_text(encoding="utf-8"))
        assert meta["id"] == f"piamac/{n}" and meta["kernel_sources"][1].endswith(f"a7-{arm}")
    with pytest.raises(AssertionError):
        stage.assert_only_arm_seed_differ(template, template.replace("SESSION_BUDGET_MIN = 11", "SESSION_BUDGET_MIN = 9"))


def test_kernel_refuses_placeholders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert len(kernel.pin_errors()) == 2   # template ships PLACEHOLDER commit and divisi sha
    monkeypatch.setattr(kernel, "COMMIT", "a" * 40)
    monkeypatch.setattr(kernel, "EXPECT_DIVISI_MANIFEST_SHA", {"C": "b" * 64, "CL": "c" * 64})
    assert kernel.pin_errors() == []
    monkeypatch.setattr(kernel, "COMMIT", "a" * 39)
    assert kernel.pin_errors()
    monkeypatch.setattr(kernel, "COMMIT", "a" * 40)
    monkeypatch.setattr(kernel, "EXPECT_DIVISI_MANIFEST_SHA", {"C": "b" * 64, "CL": "PLACEHOLDER"})
    monkeypatch.setattr(kernel, "ARM", "CL")
    assert kernel.pin_errors()
    monkeypatch.setattr(kernel, "STATUS", tmp_path / "kernel_status.json")
    with pytest.raises(SystemExit):   # main() aborts on the pins before touching /kaggle
        kernel.main()
    assert "pins not set" in json.loads((tmp_path / "kernel_status.json").read_text(encoding="utf-8"))["aborted"]


def test_real_staging_copies_exactly_referenced(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "strips" / "P").mkdir(parents=True)
    for n in ("a", "b", "unused"):
        (src / "strips" / "P" / f"{n}.png").write_bytes(n.encode())
    rows = [{"file": "strips/P/a.png"}, {"file": "strips/P/b.png"}, {"file": "strips/P/a.png"}]
    (src / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = tmp_path / "out"
    assert stage.stage_real(src, out) == 2
    got = sorted(p.name for p in (out / "strips").rglob("*.png"))
    assert got == ["a.png", "b.png"]
    assert json.loads((out / "dataset-metadata.json").read_text(encoding="utf-8"))["id"] == stage.REAL_ID


pre = _load("a7_pre_gpu", "pre_gpu_check.py")
pre.tp.use_ext_vocab(pre.tp.VOCAB_EXT_A7)


def _fake_build(root: Path, layered: bool, n_train: int = 3, oov: bool = False) -> Path:
    (root / "build" / "manifest").mkdir(parents=True)
    (root / "build" / "corpus").mkdir(parents=True)
    (root / "kernel_status.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    (root / "a7_gates.json").write_text(json.dumps({"ok": True, "gates": []}), encoding="utf-8")
    (root / "halves.json").write_text("{}", encoding="utf-8")
    toks = ["clef.G-L2", "note.quarter-L2"] + (["layer.split"] if layered else []) + (["bogus.tok"] if oov else [])
    rows = [{"split": "train", "font": f, "tokens": toks} for f in ["Bravura"] * n_train + ["Gootville"]]
    (root / "build" / "manifest" / "phase2_manifest.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (root / "build" / "corpus" / "p.plan.json").write_text(
        json.dumps({"split": "train", "divisi": {"class": {"S:3rd": 10, "A:3rd": 5, "T:triad": 4}}}), encoding="utf-8")
    return root


def test_pre_gpu_check_arm(tmp_path: Path) -> None:
    info, errs = pre.check_arm("CL", _fake_build(tmp_path / "cl", layered=True), 3, "Gootville")
    assert errs == [] and info["train_pool_without_holdout"] == 3 and len(info["manifest_sha256"]) == 64
    assert pre.chord_train_counts(tmp_path / "cl") == {"3rd": 15, "triad": 4}
    _, errs = pre.check_arm("C", _fake_build(tmp_path / "c", layered=True), 3, "Gootville")
    assert any("not an arm C build" in e for e in errs)
    _, errs = pre.check_arm("C", _fake_build(tmp_path / "c2", layered=False, oov=True), 4, "Gootville")
    assert any("outside VOCAB_EXT_A7" in e for e in errs) and any("< 4 per epoch" in e for e in errs)


def test_pre_gpu_real_simulation_caps_and_drops_layered_for_c() -> None:
    rows = [{"piece": p, "page": 1, "sys": s, "staff": 0, "train_ok": True, "split": "train", "layered": s == 0}
            for p in ("A", "B") for s in range(3)]
    cl = pre.simulate_real("CL", rows, n_real_epoch=100, n_divisi_epoch=900, cap=8, epochs=4, seed=1)
    assert cl["staff_systems"] == 6 and cl["at_cap_end"] == 6 and cl["views_total"] == 48
    assert cl["realised_share_by_epoch"] == [round(12 / 912, 4)] * 4   # 6 groups x 2 per epoch: the cap binds
    c = pre.simulate_real("C", rows, n_real_epoch=100, n_divisi_epoch=900, cap=8, epochs=4, seed=1)
    assert c["strips"] == 4 and c["layered"] == 0


def test_pin_line_matches_template_once() -> None:
    text = (KDIR / "phase2_divisi_a7_kernel.py").read_text(encoding="utf-8")
    assert len(pre.PIN_LINE.findall(text)) == 1
