"""Tests for training/phase2/eval_divisi_a6.py on hand-made token lists (no checkpoints or renders)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase2"))
from eval_divisi_a6 import (auroc, fallback_fired, head_scores, piece_bootstrap_lb, select_epoch,  # noqa: E402
                            wilson_lb)


def test_head_scores_counts_untrained_step_as_hallucination():
    s = head_scores(["note.quarter-L1", "chordnote-L9"], ["note.quarter-L1"])
    assert s["untrained_step"] == 1 and s["plain_extra"] == 1


def test_head_scores_buckets():
    s = head_scores(["note.half-L1", "chordnote-S1"], ["note.half-L1", "chordnote-S1"])
    assert s["bucket"]["2nd_up"] == [1, 1] or s["bucket"]["2nd_down"] == [1, 1]


def test_head_scores_uses_stems_and_misses():
    gt = ["note.quarter-L2", "chordnote-S2", "note.half-L3", "chordnote-L4"]
    pred = ["note.quarter-L2", "note.half-L3", "chordnote-L5"]
    s = head_scores(pred, gt, stems=["down", "up"])
    assert s["bucket"]["2nd_down"] == [0, 1]
    assert s["bucket"]["3rd"] == [0, 1]
    assert s["tp"] == 2 and s["gt_heads"] == 4 and s["fp_chord"] == 1


def test_triad_exact_and_accidental_member():
    gt = ["accidental.sharp-L3", "note.half-L2", "chordnote-L3", "chordnote-L4"]
    s = head_scores(list(gt), gt)
    assert s["triad_exact"] == [1, 1]
    assert s["bucket"]["triad"] == [2, 2]
    assert s["acc_member"] == [1, 1]


def test_head_conf_marks_false_heads():
    s = head_scores(["note.half-L1", "chordnote-L2", "chordnote-L3"], ["note.half-L1", "chordnote-L2"],
                    conf=[.9, .8, .3])
    assert s["head_conf"] == [(.8, True), (.3, False)]


def test_select_epoch_tie_goes_earlier():
    e = [{"min_recall": .9, "P": .96, "canary_ok": True}, {"min_recall": .9, "P": .97, "canary_ok": True}]
    assert select_epoch(e) == 1


def test_select_epoch_skips_low_precision():
    e = [{"min_recall": .95, "P": .94, "canary_ok": True}, {"min_recall": .9, "P": .96, "canary_ok": True}]
    assert select_epoch(e) == 2


def test_select_epoch_skips_canary_breach_and_raises_when_none():
    e = [{"min_recall": .95, "P": .97, "canary_ok": False}, {"min_recall": .5, "P": .97, "canary_ok": True}]
    assert select_epoch(e) == 2
    with pytest.raises(ValueError):
        select_epoch([{"min_recall": .9, "P": .5, "canary_ok": True}])


def test_fallback_needs_both_seeds_below_half():
    assert fallback_fired(.49, .3) and not fallback_fired(.49, .5) and not fallback_fired(.6, .2)


def test_wilson_and_bootstrap_bounds():
    assert 0.8 < wilson_lb(95, 100) < 0.95 and wilson_lb(0, 0) == 0.0
    hits, ns = {"a": 100, "b": 50, "c": 90}, {"a": 100, "b": 100, "c": 100}
    even = piece_bootstrap_lb({"a": 90, "b": 90, "c": 90}, ns, seed=0)
    assert abs(even - .9) < 1e-9
    spread = piece_bootstrap_lb(hits, ns, seed=0)
    assert spread < .8 and spread == piece_bootstrap_lb(hits, ns, seed=0)


def test_auroc():
    assert auroc([(.9, True), (.8, True), (.2, False)]) == 1.0
    assert auroc([(.1, True), (.9, False)]) == 0.0
    assert auroc([(.5, True), (.5, False)]) == 0.5


def test_strip_chordnotes_leaves_pitch_list_unchanged():
    import contextlib
    import io

    import eval_dev_nofermata as nf
    import stage3_transcription as s3

    base = ["clef.G-L2", "note.quarter-L2", "note.quarter-L3"]
    with_chord = ["clef.G-L2", "note.quarter-L2", "chordnote-L4", "note.quarter-L3"]
    stripped, conf = nf.strip_chordnotes(with_chord, [.9, .8, .7, .6])
    assert stripped == base and conf == [.9, .8, .6]

    def pitches(toks):
        with contextlib.redirect_stdout(io.StringIO()):
            return [e["pitch"] for e in s3.infer_pitch(list(toks), voice="Soprano") if e["type"] == "note"]

    assert pitches(stripped) == pitches(base)


def test_mcnemar_exact():
    r = nf_mcnemar([True] * 10, [False] * 10)
    assert (r["ref_only"], r["other_only"]) == (10, 0) and r["p"] < .01
    assert nf_mcnemar([True, False], [True, False])["p"] == 1.0


def nf_mcnemar(a, b):
    import eval_dev_nofermata as nf
    return nf.mcnemar_exact(a, b)


def test_wrong_length_stems_are_unknown_and_counted():
    gt = ["note.quarter-L2", "chordnote-S2"]
    s = head_scores(gt, gt, stems=["up", "down"])
    assert s["stem_mismatch"] == 1 and s["bucket"]["2nd_unknown"] == [1, 1] and "2nd_up" not in s["bucket"]


def test_missing_stem_key_is_unknown_not_2nd_up(monkeypatch):
    import eval_divisi_a6 as ev
    monkeypatch.setattr(ev, "decode_strip", lambda m, p: (["note.quarter-L2", "chordnote-S2"], [.9, .9]))
    row = {"piece": "p", "voice": "Alto", "system": 0, "path": "x.png", "font": "Bravura",
           "tokens": ["note.quarter-L2", "chordnote-S2"]}
    out = ev.evaluate(None, Path("."), [row], {"other|Alto|0": ["up"]})
    assert out["stems_missing_key"] == 1 and out["stems_wrong_length"] == 0
    assert out["total"]["bucket"] == {"2nd_unknown": [1, 1]}


def test_empty_recall_bucket_is_missing_status():
    import eval_divisi_a6 as ev
    tot = ev.merge_scores([head_scores(["note.half-L1"], ["note.half-L1"])])
    g = {x["gate"]: x for x in ev.gate_table({"total": tot, "piece_buckets": {}, "groups": {}, "uninjected": [0, 0]})}
    assert g["recall 3rd"]["status"] == "MISSING"


def test_min_bucket_recall_drops_thin_buckets_and_none_when_all_dropped():
    import eval_divisi_a6 as ev
    b = {"3rd": [190, 200], "4th": [160, 200], "5th": [99, 99], "7th": [0, 0]}
    rec, thin = ev.min_bucket_recall(b, drop_second=False)
    assert rec == .8 and "5th" in thin and "7th" in thin and "2nd_up" in thin and "3rd" not in thin
    _, thin2 = ev.min_bucket_recall(b, drop_second=True)
    assert "2nd_up" not in thin2 and "5th" in thin2
    assert ev.min_bucket_recall({"3rd": [9, 10]}, drop_second=False)[0] is None
    assert ev.min_bucket_recall({"4th": [100, 100]}, drop_second=False, floor=100)[0] == 1.0


def test_select_epoch_ignores_epochs_with_every_bucket_dropped():
    rows = [{"min_recall": None, "P": .97, "canary_ok": True},
            {"min_recall": .5, "P": .97, "canary_ok": True}]
    assert select_epoch(rows) == 2
    with pytest.raises(ValueError):
        select_epoch([{"min_recall": None, "P": .97, "canary_ok": True}])


def test_cluster_stats_share_and_design_effect():
    import eval_divisi_a6 as ev
    s = ev.cluster_stats({"a": 10, "b": 0}, {"a": 10, "b": 10})        # all hits in one piece: rho = 1
    assert s["max_piece_share"] == .5 and s["design_effect"] == pytest.approx(10.0)
    iid = ev.cluster_stats({"a": 5, "b": 5}, {"a": 10, "b": 10})       # same rate: no clustering
    assert iid["design_effect"] == pytest.approx(1.0)
    assert ev.cluster_stats({"a": 1}, {"a": 4})["design_effect"] is None


def test_dedup_columns_counts_a_repeated_head_once():
    import eval_divisi_a6 as ev
    toks = ["clef.G-L2", "note.quarter-L3", "chordnote-L5", "note.quarter-L2"]
    row = {"piece": "p", "voice": "S", "system": 1, "font": "Bravura"}
    seen: set = set()
    a, b = head_scores(toks, toks), head_scores(toks, toks)
    assert ev.dedup_columns(a, row, seen) == 0 and a["bucket"]
    assert ev.dedup_columns(b, row, seen) == 1 and b["bucket"] == {}
    row2 = {**row, "font": "Gootville"}
    c = head_scores(toks, toks)
    assert ev.dedup_columns(c, row2, seen) == 0 and c["bucket"]


def test_ledger2_bucket_a6_4():
    gt = ["note.half-L5", "chordnote-L7", "note.half-L-2", "chordnote-L-1"]   # L7 = step 12, L-1 = step -4
    s = head_scores(list(gt), gt)
    assert s["bucket"]["ledger2"] == [2, 2] and s["bucket"]["ledger"] == [2, 2]


def test_tie_source_buckets_and_tie_fp():
    gt = ["note.half-L2", "chordnote-L3", "slur.start-L2", "slur.start-L3", "barline-L1",
          "slur.end-L2", "slur.end-L3", "note.half-L2", "chordnote-L3",
          "note.half-L4", "barline-L1", "note.half-L4"]            # an untied same-step repeat across the barline
    pred = list(gt[:10]) + ["slur.start-L4"] + gt[10:]              # model ties the repeat
    s = head_scores(pred, gt, ties=["synth", "synth"])
    assert s["bucket"]["tie_synth"] == [2, 2] and "tie_native" not in s["bucket"]
    assert s["tie_fp"] == [1, 1]
    assert "tie_synth" not in head_scores(pred, gt)["bucket"]       # no sources: no tie bucket
    assert head_scores(list(gt), gt)["tie_fp"] == [0, 1]


def test_evaluate_passes_tie_sources(monkeypatch):
    import eval_divisi_a6 as ev
    gt = ["note.quarter-L2", "chordnote-L3"]
    monkeypatch.setattr(ev, "decode_strip", lambda m, p: (list(gt), [.9, .9]))
    row = {"piece": "p", "voice": "Alto", "system": 0, "path": "x.png", "font": "Bravura", "tokens": gt,
           "_ties": {"p|Alto|0": ["native"]}}
    out = ev.evaluate(None, Path("."), [row], {"p|Alto|0": ["up"]})
    assert out["total"]["bucket"]["tie_native"] == [1, 1]
