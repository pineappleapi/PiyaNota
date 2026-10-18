"""Tests for training/phase1/divisi_a6_gates.py on hand-made rows (no renders needed)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase1"))
import divisi_a6_gates as g  # noqa: E402


def row(font, tokens, split="train", piece="p__divisi", voice="Alto", system=0):
    return {"font": font, "tokens": tokens, "split": split, "piece": piece, "voice": voice, "system": system}


def by_name(gates):
    return {x["name"]: x for x in gates}


def test_bucket_third_and_ledger():
    assert g.bucket_of("note.quarter-L1", ["chordnote-L2"]) == ["3rd"]
    assert g.bucket_of("note.quarter-L1", ["chordnote-L3"]) == ["5th"]
    assert g.bucket_of("note.quarter-L1", ["chordnote-L0"]) == ["3rd", "ledger"]   # member at step -2
    assert "ledger" in g.bucket_of("note.quarter-L3", ["chordnote-L6"])   # step 10
    assert g.bucket_of("note.half-L2", ["chordnote-L3", "chordnote-L4"]) == ["triad", "triad"]


def test_second_uses_stem():
    assert g.bucket_of("note.quarter-L2", ["chordnote-S2"], "up") == ["2nd_up"]
    assert g.bucket_of("note.quarter-L2", ["chordnote-S2"], "down") == ["2nd_down"]
    assert g.bucket_of("note.whole-L2", ["chordnote-S2"], "none") == ["2nd_none"]
    assert g.bucket_of("note.quarter-L2", ["chordnote-S2"]) == ["2nd_unknown"]


def test_step_of():
    assert [g.step_of(t) for t in ("x-L1", "x-S1", "x-L2", "x-S0", "x-L0", "x-L5")] == [0, 1, 2, -1, -2, 8]


def test_mix_report_stems_and_gootville():
    rows = [row("Bravura", ["clef.G-L2", "note.quarter-L2", "chordnote-S2", "note.half-L3", "chordnote-L4"]),
            row("Gootville", ["note.quarter-L2", "chordnote-S2", "note.half-L3", "chordnote-L4"])]
    stems = {"p__divisi|Alto|0": ["down", "up"]}
    rep = g.mix_report(rows, stems)
    assert rep["buckets"]["in_font"] == {"2nd_down": 1, "3rd": 1}
    assert rep["buckets"]["held_out"] == {"2nd_down": 1, "3rd": 1}
    assert rep["gootville_train_chord_strips"] == 1
    assert rep["stem_mismatch_strips"] == 0
    bad = g.mix_report(rows, {"p__divisi|Alto|0": ["down"]})
    assert bad["stem_mismatch_strips"] == 2


def test_out_of_range_member():
    rep = g.mix_report([row("Bravura", ["note.quarter-L1", "chordnote-L8"])])   # step 14
    assert rep["member_steps_out_of_range"] == 1


def test_share_gate():
    assert g.share_gate("x", 16, 100, 0.12)["status"] == g.FAIL
    assert g.share_gate("x", 14, 100, 0.12)["status"] == g.PASS


def good_summary():
    cls = {"Alto:2nd_up": 7, "Alto:2nd_down": 3, "Alto:2nd_none": 2, "Alto:3rd": 16, "Alto:4th": 12, "Alto:5th": 12,
           "Alto:6th": 12, "Alto:7th": 5, "Alto:8ve": 16, "Alto:triad": 15}
    return {"pieces_missing_from_build": [], "density_per_strip": [0.0, 0.3, 0.5],
            "realised": {"class": cls, "duration": {"whole": 12, "half": 20, "dotted": 15, "quarter": 33, "beamed": 20},
                         "chords_total": 100, "free": 60, "copied": 40, "accidental_cols": 13, "crossing": 5,
                         "chord_free_strips": 1, "strips": 4, "steps": {"Alto:-5": 1, "Alto:13": 1},
                         "free_new_accidentals": 0, "induced_accidentals": 0}}


def test_summary_gates_pass_and_fail():
    s = good_summary()
    assert all(x["status"] == g.PASS for x in g.summary_gates(s)), g.format_table(g.summary_gates(s))
    s["realised"]["class"]["Alto:3rd"] = 22
    s["realised"]["induced_accidentals"] = 1
    s["realised"]["steps"]["Alto:14"] = 1
    bad = {n for n, x in by_name(g.summary_gates(s)).items() if x["status"] != g.PASS}
    assert {"interval.3rd", "induced_accidentals", "member_steps_summary"} <= bad


def test_stems_down_gate():
    s = good_summary()
    s["realised"]["class"]["Alto:2nd_down"] = 1
    assert by_name(g.summary_gates(s))["2nd_stems_down"]["status"] == g.FAIL


def test_density_gate():
    s = good_summary()
    s["density_per_strip"] = [0.1, 0.5]
    assert by_name(g.summary_gates(s))["density_range"]["status"] == g.FAIL


def test_a5_missing_and_wrong(tmp_path):
    assert g.a5_gate(tmp_path / "nope.jsonl")["status"] == g.MISSING
    p = tmp_path / "m.jsonl"
    p.write_text("x", encoding="utf-8")
    assert g.a5_gate(p)["status"] == g.FAIL


def test_manifest_gates_missing_fails(tmp_path):
    gates, _ = g.manifest_gates(tmp_path, {"stems": {}})
    assert {x["status"] for x in gates} == {g.MISSING}


def make_test_dir(root, name, n_in, n_out):
    d = root / name
    (d / "manifest").mkdir(parents=True)
    rows, stems = [], {}
    for i in range(n_in + n_out):
        font = "Bravura" if i < n_in else "Gootville"
        rows.append(row(font, ["note.quarter-L1", "chordnote-L2"], split="val", system=i))
        stems[f"p__divisi|Alto|{i}"] = ["up"]
    (d / "manifest" / "phase2_manifest.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (d / "divisi_summary.json").write_text(json.dumps({"stems": stems}), encoding="utf-8")
    return d


def test_test_render_buckets(tmp_path):
    d = make_test_dir(tmp_path, "t1", 600, 299)
    gates = by_name(g.test_gates([d])[0])
    assert gates["test.3rd.in_font"]["status"] == g.PASS
    assert gates["test.3rd.held_out"]["status"] == g.FAIL       # 299 < 300
    assert gates["test.7th.in_font"]["status"] == g.WARN         # absent bucket: warn, not fail
    assert gates["test.8ve.in_font"]["status"] == g.FAIL
    assert g.test_gates([])[0][0]["status"] == g.NOT_RUN
