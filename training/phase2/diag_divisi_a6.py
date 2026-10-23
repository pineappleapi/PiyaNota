"""A6 failure diagnosis (diagnostic only, tuning half): why triad members, ledger members and exact triad sets fail.

Decision rules and definitions are pre-registered in docs/superpowers/plans/2026-10-23-divisi-a6-failure-diagnosis.md
(ml-cv-lead review 2026-10-23); this script applies them verbatim. Nothing here changes a gate or the A6 verdict.
The test half is refused: it must not shape the next hypothesis (freeze doc A6.6).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "training" / "phase1"), str(Path(__file__).resolve().parent)]
from eval_divisi_a6 import (ACCIDENTAL, LEDGER_HIGH, LEDGER_LOW, STRIP_HEIGHT, columns, lcs_pairs,  # noqa: E402
                            shape, step_of)

CTC_STRIDE = 4                    # CRNN width stride at height 64: T = W / 4 (freeze section 3)
TIGHT_GAP = 4.0                   # frames; 3 is the CTC floor for note + 2 distinct chordnotes, +1 frame slack
TIGHT_MIN_SHARE = 0.15            # below this share of valid-gap members, tight = P25 of column gaps instead
TIGHT_FALLBACK_Q = 0.25
ROOM_GAP = 8.0                    # prior test: columns with at least this many frames have room for 3 heads
PRIOR_MAX = 0.5                   # prior test positive if 2+ chordnotes are emitted in under half of roomy columns
RATIO_MIN, RATIO_LB_MIN = 2.0, 1.5
SHARE_MIN_GAP, SHARE_MIN_SECOND = 0.40, 0.30
MH_MIN = 1.5
R2_RATIO_MAX, R2_UB_MAX = 1.5, 2.0
LEDGER_REC_MIN, LEDGER_LB_MIN = 0.85, 0.80
BOOT_B, BOOT_SEED, BOOT_LO, BOOT_HI = 2000, 0, 0.025, 0.975
GAP_BINS = (("<=3", 3.0), ("4", 4.0), ("5-6", 6.0), ("7-9", 9.0), (">=10", float("inf")))
HELD_OUT_FONT = "Gootville"
NOT_BASE = ("chordnote-", ACCIDENTAL, "dot")


def _base_after(tokens: Sequence[str], i: int) -> tuple[int, str]:
    """Index and token of the next base token after `tokens[i]`; (len, "END") at the strip end."""
    j = i + 1
    while j < len(tokens) and tokens[j].startswith(NOT_BASE):
        j += 1
    return (j, tokens[j]) if j < len(tokens) else (len(tokens), "END")


def frame_gaps(pred: Sequence[str], spans: Sequence[tuple[float, float]], strip_height: int,
               strip_width: int) -> dict[int, float]:
    """Predicted note index -> CTC frames from the note to the next base token (spans are input-strip pixels)."""
    scale = STRIP_HEIGHT / strip_height / CTC_STRIDE
    out = {}
    for i, t in enumerate(pred):
        if t.startswith("note."):
            j, _tok = _base_after(pred, i)
            x_next = spans[j][0] if j < len(pred) else strip_width
            out[i] = (x_next - spans[i][0]) * scale
    return out


def ledger_lines(step: int) -> int:
    """Ledger lines a head at `step` sits on or beyond (0 inside the staff)."""
    if step <= LEDGER_LOW:
        return (LEDGER_LOW - step) // 2 + 1
    if step >= LEDGER_HIGH:
        return (step - LEDGER_HIGH) // 2 + 1
    return 0


def triad_breakdown(pred: Sequence[str], gt: Sequence[str], gaps: Mapping[int, float]) -> dict[str, Any]:
    """Per-member triad rows, per-member ledger rows and net heads of one strip (head_scores alignment)."""
    gcols, pcols = columns(gt), columns(pred)
    aligned = dict(lcs_pairs([shape(c[1]) for c in gcols], [shape(c[1]) for c in pcols]))
    members, ledger = [], []
    gained = false = 0
    for pi, (_ti, _note, ext, _acc) in enumerate(pcols):
        if pi not in aligned.values():
            false += len(ext)
    for gi, (ti, note, ext, _acc) in enumerate(gcols):
        g = {step_of(note)} | {step_of(t) for t in ext}
        pi = aligned.get(gi)
        ps = None if pi is None else {step_of(pcols[pi][1])} | {step_of(t) for t in pcols[pi][2]}
        if ps is not None:
            false += len(ps - g)
        if not ext:
            continue
        gap = None
        if pi is not None and pcols[pi][1] == note and _base_after(pred, pcols[pi][0])[1] == _base_after(gt, ti)[1]:
            gap = gaps.get(pcols[pi][0])
        heads = sorted(g)
        has_2nd = any(b - a == 1 for a, b in zip(heads, heads[1:]))
        top = max(step_of(t) for t in ext)
        for t in ext:
            s = step_of(t)
            hit = ps is not None and s in ps
            gained += hit
            if len(ext) >= 2:
                members.append({"gi": gi, "pos": "top" if s == top else "middle", "gap": gap, "has_2nd": has_2nd,
                                "dur": shape(note), "hit": hit,
                                "n_pred_ext": None if pi is None else len(pcols[pi][2])})
            if ledger_lines(s):
                ledger.append({"gi": gi, "lines": ledger_lines(s), "in_triad": len(ext) >= 2, "hit": hit})
    return {"members": members, "ledger": ledger, "net": {"gained": gained, "false": false}}


Group = Callable[[Mapping[str, Any]], "bool | None"]


def _split(members: Sequence[Mapping[str, Any]], in_group: Group) -> tuple[list[int], list[int]]:
    """[misses, n] inside and outside the group; members where in_group is None are left out."""
    a, b = [0, 0], [0, 0]
    for m in members:
        g = in_group(m)
        if g is None:
            continue
        side = a if g else b
        side[0] += not m["hit"]
        side[1] += 1
    return a, b


def ratio(members: Sequence[Mapping[str, Any]], in_group: Group) -> float | None:
    """Miss rate in the group / miss rate outside it; None if either side is empty or the outside never misses."""
    (am, an), (bm, bn) = _split(members, in_group)
    if not an or not bn or not bm:
        return None
    return (am / an) / (bm / bn)


def mh_ratio(members: Sequence[Mapping[str, Any]], in_group: Group) -> float | None:
    """Mantel-Haenszel miss-rate ratio stratified by duration class (tight gaps go with short notes)."""
    num = den = 0.0
    for dur in {m["dur"] for m in members}:
        (am, an), (bm, bn) = _split([m for m in members if m["dur"] == dur], in_group)
        n = an + bn
        if n:
            num += am * bn / n
            den += bm * an / n
    return num / den if den else None


def boot_ci(members: Sequence[Mapping[str, Any]], stat: Callable[[Sequence[Mapping[str, Any]]], float | None],
            b: int = BOOT_B, seed: int = BOOT_SEED) -> tuple[float, float] | None:
    """Piece-level percentile interval of `stat`; resamples where it is undefined are skipped."""
    by_piece: dict[str, list[Mapping[str, Any]]] = {}
    for m in members:
        by_piece.setdefault(m["piece"], []).append(m)
    pieces = sorted(by_piece)
    if not pieces:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(b):
        v = stat([m for _ in pieces for m in by_piece[pieces[rng.randrange(len(pieces))]]])
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return vals[int(BOOT_LO * len(vals))], vals[min(len(vals) - 1, int(BOOT_HI * len(vals)))]


def _miss_share(members: Sequence[Mapping[str, Any]], in_group: Group) -> float:
    """Share of all misses (gap None included in the denominator) that fall in the group."""
    total = sum(not m["hit"] for m in members)
    return sum(not m["hit"] and in_group(m) is True for m in members) / total if total else 0.0


def _rule(members: Sequence[Mapping[str, Any]], in_group: Group, share_min: float) -> dict[str, Any]:
    pt = ratio(members, in_group)
    ci = boot_ci(members, lambda s: ratio(s, in_group))
    share = _miss_share(members, in_group)
    lopo = True
    for p in {m["piece"] for m in members}:
        sub = [m for m in members if m["piece"] != p]
        r = ratio(sub, in_group)
        lopo &= r is not None and r >= RATIO_MIN and _miss_share(sub, in_group) >= share_min
    passed = pt is not None and pt >= RATIO_MIN and ci is not None and ci[0] >= RATIO_LB_MIN and share >= share_min \
        and lopo
    return {"ratio": pt, "ci": ci, "miss_share": share, "lopo": lopo, "mh": mh_ratio(members, in_group),
            "pass": passed}


def verdict(members: Sequence[Mapping[str, Any]], ledger: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Applies the pre-registered Decision Rules; `route` is A7-crop, A7-data or R3."""
    valid = [m for m in members if m["gap"] is not None]
    cut = TIGHT_GAP
    if valid and sum(m["gap"] <= TIGHT_GAP for m in valid) / len(valid) < TIGHT_MIN_SHARE:
        col_gaps = sorted({m.get("col", id(m)): m["gap"] for m in valid}.values())
        cut = col_gaps[int(TIGHT_FALLBACK_Q * len(col_gaps))]

    def tight(m: Mapping[str, Any]) -> bool | None:
        return None if m["gap"] is None else m["gap"] <= cut

    bins: dict[str, list[int]] = {name: [0, 0] for name, _ in GAP_BINS} | {"None": [0, 0]}
    for m in members:
        name = "None" if m["gap"] is None else next(n for n, hi in GAP_BINS if m["gap"] <= hi)
        bins[name][0] += not m["hit"]
        bins[name][1] += 1
    r1a = _rule(members, tight, SHARE_MIN_GAP)
    r1b = _rule(members, lambda m: m["has_2nd"], SHARE_MIN_SECOND)
    r1 = r1a["pass"] or r1b["pass"]
    confounded = r1 and not any(r["pass"] and r["mh"] is not None and r["mh"] >= MH_MIN for r in (r1a, r1b))
    roomy = {m.get("col", id(m)): m["n_pred_ext"] for m in valid if m["gap"] >= ROOM_GAP}
    emit = sum(1 for n in roomy.values() if n is not None and n >= 2) / len(roomy) if roomy else None
    prior = emit is not None and emit < PRIOR_MAX
    spread = all(r["ratio"] is not None and r["ratio"] < R2_RATIO_MAX and r["ci"] is not None
                 and r["ci"][1] < R2_UB_MAX for r in (r1a, r1b))
    r2 = not r1 and spread and prior
    route = "A7-crop" if r1 and not confounded else "A7-data" if r2 else "R3"
    plain = [row for row in ledger if not row["in_triad"]]
    rec = sum(row["hit"] for row in plain) / len(plain) if plain else None
    lb = boot_ci(plain, lambda s: sum(r["hit"] for r in s) / len(s) if s else None) if plain else None
    misses_by_pos = {p: sum(1 for m in members if m.get("pos") == p and not m["hit"]) for p in ("middle", "top")}
    return {"members": len(members), "misses": sum(not m["hit"] for m in members), "tight_cut": cut,
            "gap_bins": bins, "misses_by_pos": misses_by_pos, "r1a": r1a["pass"], "r1b": r1b["pass"],
            "r1a_detail": r1a, "r1b_detail": r1b, "r1_confounded": confounded,
            "prior": {"roomy_columns": len(roomy), "emit_2plus_share": emit, "positive": prior},
            "r2": r2, "route": route,
            "ledger_non_triad": {"n": len(plain), "recall": rec, "ci": lb},
            "ledger_part_of_triad": rec is not None and rec >= LEDGER_REC_MIN and lb is not None
            and lb[0] >= LEDGER_LB_MIN}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--halves", type=Path, required=True)
    ap.add_argument("--half", default="tuning")
    ap.add_argument("--split", default="val")
    ap.add_argument("--ckpt", action="append", required=True, help="label=checkpoint.pt (repeatable)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.half != "tuning":
        print("diag_divisi_a6: tuning half only (the test half must not shape the next hypothesis)", file=sys.stderr)
        return 2
    import cv2  # noqa: PLC0415 (heavy; keeps the pure functions importable without it)
    import torch  # noqa: PLC0415
    import divisi_halves  # noqa: PLC0415
    import stage3_transcription as s3  # noqa: PLC0415
    from divisi_a6_gates import head_key  # noqa: PLC0415
    from eval_divisi_a6 import load_builds, load_cpu_model  # noqa: PLC0415
    rows, _ = load_builds([a.build], a.split, a.half, True, 0, 0, divisi_halves.load_groups(a.halves))
    print(f"{len(rows)} chord strips (tuning half, all fonts)")
    result: dict[str, Any] = {"label": "diagnostic, tuning half", "n_strips": len(rows), "checkpoints": {}}
    cpu = torch.device("cpu")
    for item in a.ckpt:
        label, path = item.split("=", 1)
        model = load_cpu_model(path)
        members: list[dict[str, Any]] = []
        ledger: list[dict[str, Any]] = []
        seen: set[tuple[object, ...]] = set()
        dups = mismatch = gained = false = 0
        for r in rows:
            img = cv2.imread(str(r["_build"] / "out" / r["path"]), cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise FileNotFoundError(r["path"])
            spans: list[tuple[float, float]] = []
            pred = [p[0] for p in s3.transcribe_strip(img, model, cpu, STRIP_HEIGHT, return_confidence=True,
                                                      spans_out=spans)]
            if len(spans) != len(pred):
                mismatch += 1
                gaps: dict[int, float] = {}
            else:
                gaps = frame_gaps(pred, spans, img.shape[0], img.shape[1])
            bd = triad_breakdown(pred, r["tokens"], gaps)
            gained += bd["net"]["gained"]
            false += bd["net"]["false"]
            gcols = columns(r["tokens"])
            keys = {gi: head_key(r, gi, gcols[gi][1], gcols[gi][2]) for gi in {x["gi"] for x in bd["members"]
                                                                              + bd["ledger"]}}
            new = {gi for gi, k in keys.items() if k not in seen}
            dups += len(keys) - len(new)
            seen |= {keys[gi] for gi in new}
            tag = {"piece": r["piece"], "font": r["font"]}
            members += [{**m, **tag, "col": keys[m["gi"]]} for m in bd["members"] if m["gi"] in new]
            ledger += [{**x, **tag} for x in bd["ledger"] if x["gi"] in new]
        ng_m = [m for m in members if m["font"] != HELD_OUT_FONT]
        ng_l = [x for x in ledger if x["font"] != HELD_OUT_FONT]
        entry = {"verdict": verdict(members, ledger), "verdict_no_gootville": verdict(ng_m, ng_l),
                 "counts_no_gootville": {"members": len(ng_m), "triad_columns": len({m["col"] for m in ng_m}),
                                         "ledger": len(ng_l)},
                 "gap_valid_fraction": sum(m["gap"] is not None for m in members) / len(members) if members else None,
                 "span_mismatch": mismatch, "duplicate_columns": dups, "net": {"gained": gained, "false": false},
                 "members": [{k: v for k, v in m.items() if k != "col"} for m in members]}
        result["checkpoints"][label] = entry
        v = entry["verdict"]
        print(f"== {label}: route {v['route']} (no Gootville: {entry['verdict_no_gootville']['route']}); members "
              f"{v['members']} misses {v['misses']}; r1a {v['r1a']} r1b {v['r1b']} confounded {v['r1_confounded']} "
              f"r2 {v['r2']}; ledger part of triad {v['ledger_part_of_triad']}; counts no Gootville "
              f"{entry['counts_no_gootville']}; span mismatch {mismatch}; duplicates {dups}")
    a.out.write_text(json.dumps(result, indent=1, default=list), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
