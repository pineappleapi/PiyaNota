"""Scorer for the fresh-photo evaluation (metrics fixed in PREREG.md).

Reads runs/<piece>/stage12.json + stage3_<crnn>.json and gt/<piece>/gt.json, writes
runs/scores/<piece>/<crnn>/score.json, confusion CSV/PNG files, and runs/scores/summary.json.

Versions scored: "a" (Stage 3 as-is), "b" (clef/key classifier), "oracle" (GT clef + key through the (b)
path; a diagnostic ceiling, not a pipeline result). Alignment helpers are copied from
data/eval_dsmn/score.py (that module runs main() at import).

Usage (repo root):  python data/eval_fresh/score_eval.py
"""
from __future__ import annotations

import csv
import io
import contextlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import stage3_clefkey as s3b  # noqa: E402
from clef_voice_rules import resolve_clef  # noqa: E402
from clef_key_core import CLEF_CLASSES  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNS = Path(__file__).resolve().parent / "runs"
SCORES = RUNS / "scores"
PIECES = ["non_nobis_domine", "honneur_a_toi", "gaano_ko_ikaw_kamahal", "handog"]
GATED_PIECE = "non_nobis_domine"  # PREREG: the gate is decided on Non Nobis only; other pieces are report-only
CRNNS = ["seed1", "seed2", "baseline"]
VERSIONS = ["a", "b", "oracle"]
GT_STATUS = {"non_nobis_domine": "hand-transcribed, verified by the author",
             "honneur_a_toi": "agent-made, NOT user-verified (diagnostic only)",
             "gaano_ko_ikaw_kamahal": "agent-made, NOT user-verified (diagnostic only)",
             "handog": "agent-made, NOT user-verified (diagnostic only); divisi systems excluded"}
INF = 10 ** 9
BOOT_N = 2000
TOKEN_OOV_SPAN = 2   # an <OOV> GT token may absorb 0..2 predicted tokens at no cost (as in the DSMN scorer)
EVENT_OOV_SPAN = 3
TENOR_RANGE = (48, 69)  # C3-A4 sounding (choral-conductor range check, report-only)
BASS_RANGE = (40, 64)   # E2-E4
CROSS_SYSTEM_JUMP = 10  # semitones between a voice's consecutive system medians that looks like an octave slip
CLEF_ROWS = ["G", "G8vb", "F"]
CLEF_COLS = ["G", "G8vb", "F", "C", "other"]
TICK_NAMES = {1920: "whole", 960: "half", 480: "quarter", 240: "eighth", 120: "sixteenth", 60: "thirty-second",
              3840: "double whole"}


# ---------------------------------------------------------------- alignment (copied from eval_dsmn/score.py)
def align(ref: list[Any], hyp: list[Any], eq: Callable[[Any, Any], bool]) -> tuple[int, list[tuple]]:
    """Levenshtein with wildcard ref items ('W', k) that consume 0..k hyp items at zero cost.

    Returns (cost, ops); ops = (kind, ref_idx, hyp_idx), kinds M/S/D(missed)/I(extra)/W.
    """
    n, m = len(ref), len(hyp)
    C = [[INF] * (m + 1) for _ in range(n + 1)]
    B: list[list[Optional[tuple]]] = [[None] * (m + 1) for _ in range(n + 1)]
    C[0][0] = 0
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best, bp = INF, None
            if j > 0 and C[i][j - 1] + 1 < best:
                best, bp = C[i][j - 1] + 1, ("I", i, j - 1)
            if i > 0:
                r = ref[i - 1]
                if isinstance(r, tuple):
                    for t in range(0, r[1] + 1):
                        if j - t >= 0 and C[i - 1][j - t] < best:
                            best, bp = C[i - 1][j - t], ("W", i - 1, j - t)
                else:
                    if C[i - 1][j] + 1 < best:
                        best, bp = C[i - 1][j] + 1, ("D", i - 1, j)
                    if j > 0:
                        ok = eq(r, hyp[j - 1])
                        c = C[i - 1][j - 1] + (0 if ok else 1)
                        if c < best:
                            best, bp = c, ("M" if ok else "S", i - 1, j - 1)
            C[i][j], B[i][j] = best, bp
    ops: list[tuple] = []
    i, j = n, m
    while (i, j) != (0, 0):
        k, pi, pj = B[i][j]  # type: ignore[misc]
        if k == "I":
            ops.append(("I", None, j - 1))
        elif k in "MS":
            ops.append((k, i - 1, j - 1))
        elif k == "D":
            ops.append(("D", i - 1, None))
        else:
            ops.append(("W", i - 1, (pj, j)))
        i, j = pi, pj
    return C[n][m], ops[::-1]


def norm_tok(t: str) -> str:
    if t.startswith("dot"):
        return "dot"
    if t.startswith("slur") or t.startswith("digit"):
        return t.split("-")[0]
    return t


def tok_class(t: str) -> str:
    """Token class without staff position, e.g. note.quarter, rest.half, accidental.flat, barline, clef.G."""
    return t.rsplit("-", 1)[0] if re.search(r"-[LS]-?\d+$", t) else t


# ---------------------------------------------------------------- symbol names
def dur_name(ticks: int) -> str:
    for base, name in TICK_NAMES.items():
        if ticks == base:
            return name
        if ticks == base * 3 // 2:
            return f"dotted {name}"
        if ticks == base * 7 // 4:
            return f"double-dotted {name}"
    return f"{ticks}-tick"


def ev_kind(e: dict[str, Any]) -> str:
    return e["type"] if "type" in e else e["kind"]


def ev_pitch(e: dict[str, Any]) -> Optional[int]:
    return e.get("pitch")


def ev_dur(e: dict[str, Any]) -> int:
    return int(e["duration_ticks"] if "duration_ticks" in e else e["dur"])


def sym_name(e: dict[str, Any]) -> str:
    return f"{dur_name(ev_dur(e))} {ev_kind(e)}"


def ekey(e: dict[str, Any], mode: str) -> tuple:
    k, p, d = ev_kind(e), ev_pitch(e), ev_dur(e)
    return {"full": (k, p, d), "pitch": (k, p), "dur": (k, d)}[mode]


# ---------------------------------------------------------------- ground truth
def load_gt(piece: str) -> tuple[dict[str, dict], list[dict]]:
    gt_all = json.loads((ROOT / "gt" / piece / "gt.json").read_text(encoding="utf-8"))
    src = (ROOT / "gt" / piece / "gt_source.txt").read_text(encoding="utf-8")
    ck = {f"page{int(m[1]):03d}_sys{int(m[2]):02d}_{m[3]}": (m[4], int(m[5]) * (1 if m[6] == "#" else -1))
          for m in re.finditer(r"^p(\d+)s(\d+) (\w+): clef:(G8|G|F) key:(\d)([#b])", src, re.M)}
    gt = {}
    for g in gt_all:
        if "excluded" in g:
            continue
        clef, key = ck[g["strip_id"]]
        g["clef_class"] = {"G": "G", "G8": "G8vb", "F": "F"}[clef]
        g["key"] = key
        gt[g["strip_id"]] = g
    return gt, gt_all


def a_clef_class(first_clef: Optional[str], voice: str) -> str:
    """Effective clef that Stage 3 (a) plays: first CRNN clef token with the voice-based Tenor lowering."""
    tok = first_clef or {"Bass": "clef.F-L4"}.get(voice, "clef.G-L2")  # CLEF_FALLBACK
    fam = tok.split(".")[1][0]
    if fam == "G":
        return "G8vb" if voice == "Tenor" else "G"
    return {"F": "F", "C": "C"}.get(fam, "other")


def a_key(opening: Optional[str]) -> Optional[int]:
    if opening is None:
        return None
    if opening == "C major":
        return 0
    return int(opening[:-1]) * (1 if opening[-1] == "#" else -1)


def oracle_decision(g: dict[str, Any]) -> s3b.StripDecision:
    probs = [0.0] * len(CLEF_CLASSES)
    probs[CLEF_CLASSES.index(g["clef_class"])] = 1.0
    return s3b.StripDecision(resolve_clef(g["voice"], probs, 0.3, True), g["key"], "oracle_gt")


# ---------------------------------------------------------------- per-strip scoring
def score_strip(g: dict[str, Any], hyp_toks: Optional[list[str]], hyp_ev: Optional[list[dict]],
                clef_pred: Optional[str], key_pred: Optional[int], review: bool) -> dict[str, Any]:
    """Scores one GT strip against one version's output (None output = strip missed by Stage 2)."""
    ref = [("W", TOKEN_OOV_SPAN) if t == "<OOV>" else norm_tok(t) for t in g["agnostic"]
           if t != "<TIEX>" and not t.startswith("slur")]
    n_ref = sum(1 for r in ref if not isinstance(r, tuple))
    hyp = [norm_tok(t) for t in (hyp_toks or []) if not t.startswith("slur")]
    cost, ops = align(ref, hyp, lambda a, b: a == b)
    tok_cls: dict[str, Counter] = defaultdict(Counter)
    for k, ri, hj in ops:
        if k == "M":
            tok_cls[tok_class(ref[ri])]["c"] += 1
        elif k == "S":
            a, b = tok_class(ref[ri]), tok_class(hyp[hj])
            if a == b:
                tok_cls[a]["s"] += 1  # right symbol class, wrong staff position
            else:
                tok_cls[a]["m"] += 1
                tok_cls[b]["h"] += 1
        elif k == "D":
            tok_cls[tok_class(ref[ri])]["m"] += 1
        elif k == "I":
            tok_cls[tok_class(hyp[hj])]["h"] += 1

    he = [e for e in (hyp_ev or []) if e.get("type") in ("note", "rest")]
    rev = [("W", EVENT_OOV_SPAN) if e["kind"] == "oov" else e for e in g["events"]]
    al = {m: align(rev, he, lambda a, b, m=m: ekey(a, m) == ekey(b, m))[1] for m in ("full", "pitch", "dur")}

    def note_acc(mode: str) -> tuple[int, int]:
        good = tot = 0
        for k, ri, hj in al[mode]:
            if k == "W" or ri is None or rev[ri]["kind"] != "note":
                continue
            tot += 1
            good += k == "M"
        return good, tot

    rhythm = [0, 0]
    sym: dict[str, Counter] = defaultdict(Counter)   # GT category -> sym_ok / sym_pitch_ok / n
    sym_cm: Counter = Counter()                       # (gt category, predicted category) from the rhythm alignment
    for k, ri, hj in al["dur"]:
        if k == "W":
            continue
        if ri is None:
            sym_cm[("extra", sym_name(he[hj]))] += 1
            continue
        name = sym_name(rev[ri])
        sym[name]["n"] += 1
        rhythm[1] += 1
        if k == "M":
            sym[name]["sym_ok"] += 1
            rhythm[0] += 1
        sym_cm[(name, sym_name(he[hj]) if hj is not None else "missed")] += 1
    for k, ri, hj in al["full"]:
        if k == "M" and ri is not None:
            sym[sym_name(rev[ri])]["sym_pitch_ok"] += 1

    offs = [ev_pitch(he[hj]) - rev[ri]["pitch"] for k, ri, hj in al["dur"]
            if k in ("M", "S") and ri is not None and rev[ri]["kind"] == "note" and ev_kind(he[hj]) == "note"
            and ev_pitch(he[hj]) is not None]
    med = float(np.median(offs)) if offs else None
    octave_wrong = med is not None and med != 0 and med % 12 == 0
    pred_pitches = [ev_pitch(e) for e in he if ev_kind(e) == "note" and ev_pitch(e) is not None]
    return dict(strip_id=g["strip_id"], voice=g["voice"], page=g["page"], sys=g["sys"], detected=hyp_toks is not None,
                n_ref=n_ref, tok_err=cost, n_hyp=len(hyp), tok_cls={k: dict(v) for k, v in tok_cls.items()},
                sow=note_acc("pitch"), strict=note_acc("full"), rhythm=tuple(rhythm),
                sym={k: dict(v) for k, v in sym.items()}, sym_cm=[[a, b, n] for (a, b), n in sym_cm.items()],
                n_gt_notes=sum(1 for e in g["events"] if e["kind"] == "note"), n_pred_notes=len(pred_pitches),
                median_offset=med, octave_wrong=bool(octave_wrong), double_octave=bool(octave_wrong and abs(med) >= 24),
                review=bool(review), silent_wrong=bool(octave_wrong and not review),
                clef_gt=g["clef_class"], clef_pred=clef_pred, key_gt=g["key"], key_pred=key_pred,
                pred_median_pitch=float(np.median(pred_pitches)) if pred_pitches else None, n_unc=g["n_uncertain"])


# ---------------------------------------------------------------- aggregation
def headline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def ratio(a: float, b: float) -> Optional[float]:
        return a / b if b else None
    det = [r for r in rows if r["detected"]]
    out: dict[str, Any] = dict(
        n_strips=len(rows), n_detected=len(det),
        token_ser=ratio(sum(r["tok_err"] for r in rows), sum(r["n_ref"] for r in rows)),
        pitch_acc_sow=ratio(sum(r["sow"][0] for r in rows), sum(r["sow"][1] for r in rows)),
        strict_acc=ratio(sum(r["strict"][0] for r in rows), sum(r["strict"][1] for r in rows)),
        rhythm_acc=ratio(sum(r["rhythm"][0] for r in rows), sum(r["rhythm"][1] for r in rows)),
        n_gt_notes=sum(r["sow"][1] for r in rows),
        clef_acc=ratio(sum(r["clef_pred"] == r["clef_gt"] for r in det), len(det)),
        key_acc=ratio(sum(r["key_pred"] == r["key_gt"] for r in det), len(det)),
        octave_wrong_staves=sum(r["octave_wrong"] for r in det),
        silent_wrong_staves=sum(r["silent_wrong"] for r in det),
        silent_wrong_rate=ratio(sum(r["silent_wrong"] for r in det), len(det)),
        double_octave_staves=sum(r["double_octave"] for r in det),
        silent_clef_wrong_staves=sum(r["clef_pred"] != r["clef_gt"] and not r["review"] for r in det),
        silent_key_wrong_staves=sum(r["key_pred"] != r["key_gt"] and not r["review"] for r in det),
        flagged_and_wrong_staves=sum(r["review"] and (r["clef_pred"] != r["clef_gt"] or r["key_pred"] != r["key_gt"]) for r in det),
        review_needed_rate=ratio(sum(r["review"] for r in det), len(det)),
        note_count_ratio=ratio(sum(r["n_pred_notes"] for r in det), sum(r["n_gt_notes"] for r in det)),
        # Precision side of SOW: pitch-correct aligned notes / all predicted notes, so hallucinated notes
        # (which SOW recall cannot see) are penalised. F1 combines it with SOW recall.
        note_precision=ratio(sum(r["sow"][0] for r in rows), sum(r["n_pred_notes"] for r in det)),
    )
    p, rc = out["note_precision"], out["pitch_acc_sow"]
    out["note_f1"] = 2 * p * rc / (p + rc) if p is not None and rc is not None and p + rc else None
    return out


def boot(rows: list[dict[str, Any]], keys: tuple[str, ...] = ("token_ser", "pitch_acc_sow", "strict_acc")) -> dict:
    rng = random.Random(0)
    vals: dict[str, list[float]] = {k: [] for k in keys}
    for _ in range(BOOT_N):
        h = headline([rows[rng.randrange(len(rows))] for _ in rows])
        for k in keys:
            if h[k] is not None:
                vals[k].append(h[k])
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in vals.items() if v}


def paired_boot(ra: list[dict], rb: list[dict]) -> dict[str, Any]:
    """Bootstrap CI of (b) - (a) SOW pitch accuracy, resampling strips jointly."""
    rng = random.Random(0)
    d = []
    for _ in range(BOOT_N):
        idx = [rng.randrange(len(ra)) for _ in ra]
        a, b = headline([ra[i] for i in idx]), headline([rb[i] for i in idx])
        if a["pitch_acc_sow"] is not None and b["pitch_acc_sow"] is not None:
            d.append(b["pitch_acc_sow"] - a["pitch_acc_sow"])
    return {"ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]}


def per_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    tot: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        for k, v in r["sym"].items():
            tot[k].update(v)
    return {k: {"n": v["n"], "symbol_correct": v["sym_ok"], "symbol_and_pitch_correct": v["sym_pitch_ok"]}
            for k, v in sorted(tot.items(), key=lambda kv: -kv[1]["n"])}


def per_token_class(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tot: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        for k, v in r["tok_cls"].items():
            tot[k].update(v)
    out = {}
    for k, d in sorted(tot.items(), key=lambda kv: -(kv[1]["c"] + kv[1]["m"] + kv[1]["s"])):
        n_ref, n_hyp = d["c"] + d["m"] + d["s"], d["c"] + d["h"] + d["s"]
        out[k] = dict(n_ref=n_ref, n_pred=n_hyp, exact=d["c"], class_ok_position_wrong=d["s"],
                      recall_exact=d["c"] / n_ref if n_ref else None,
                      recall_class=(d["c"] + d["s"]) / n_ref if n_ref else None,
                      precision_exact=d["c"] / n_hyp if n_hyp else None)
    return out


def by(rows: list[dict[str, Any]], keyf: Callable[[dict], str]) -> dict[str, Any]:
    g: dict[str, list] = defaultdict(list)
    for r in rows:
        g[keyf(r)].append(r)
    return {k: headline(v) for k, v in sorted(g.items())}


def diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Choral-conductor report-only checks: range and cross-system octave consistency."""
    rng_out = []
    for r in rows:
        lim = {"Tenor": TENOR_RANGE, "Bass": BASS_RANGE}.get(r["voice"])
        if lim and r["pred_median_pitch"] is not None and not lim[0] <= r["pred_median_pitch"] <= lim[1]:
            rng_out.append(dict(strip=r["strip_id"], median=r["pred_median_pitch"], octave_wrong=r["octave_wrong"]))
    jumps = []
    for v in ("Soprano", "Alto", "Tenor", "Bass"):
        seq = sorted((r for r in rows if r["voice"] == v and r["pred_median_pitch"] is not None),
                     key=lambda r: (r["page"], r["sys"]))
        for p, q in zip(seq, seq[1:]):
            if abs(q["pred_median_pitch"] - p["pred_median_pitch"]) >= CROSS_SYSTEM_JUMP:
                jumps.append(dict(voice=v, from_=p["strip_id"], to=q["strip_id"],
                                  jump=q["pred_median_pitch"] - p["pred_median_pitch"],
                                  octave_wrong=[p["octave_wrong"], q["octave_wrong"]]))
    ow = [r for r in rows if r["octave_wrong"]]
    return dict(range_suspect=rng_out, cross_system_jumps=jumps,
                octave_wrong_caught_by_range=sum(1 for r in ow if any(x["strip"] == r["strip_id"] for x in rng_out)),
                octave_wrong_total=len(ow), tie_unresolved="not computed: Stage 4 is not part of this run")


def confusion(rows: list[dict[str, Any]], row_key: str, col_key: str, rows_order: list, cols_order: list) -> list[list]:
    cm = Counter((r[row_key], r[col_key]) for r in rows if r["detected"])
    cols = cols_order + sorted({c for _, c in cm} - set(cols_order), key=str)
    return [[""] + [str(c) for c in cols]] + [[str(rr)] + [cm[(rr, c)] for c in cols] for rr in rows_order]


def sym_confusion(rows: list[dict[str, Any]]) -> list[list]:
    cm: Counter = Counter()
    for r in rows:
        for a, b, n in r["sym_cm"]:
            cm[(a, b)] += n
        if not r["detected"]:
            pass
    gts = sorted({a for a, _ in cm if a != "extra"}, key=lambda s: -sum(v for (a, _), v in cm.items() if a == s))
    preds = [p for p in gts] + sorted({b for _, b in cm} - set(gts) - {"missed"}) + ["missed"]
    return [[""] + preds] + [[g] + [cm[(g, p)] for p in preds] for g in gts + ["extra"]]


def write_cm(path: Path, table: list[list], title: str) -> None:
    with open(path.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(table)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    data = np.array([row[1:] for row in table[1:]], dtype=float)
    h, w = data.shape
    fig, ax = plt.subplots(figsize=(max(4, 0.55 * w + 2.5), max(3, 0.45 * h + 2)))
    ax.imshow(np.log1p(data), cmap="Blues")
    for i in range(h):
        for j in range(w):
            if data[i, j]:
                ax.text(j, i, int(data[i, j]), ha="center", va="center", fontsize=7,
                        color="white" if data[i, j] > data.max() / 2 else "black")
    ax.set_xticks(range(w), table[0][1:], rotation=60, ha="right", fontsize=7)
    ax.set_yticks(range(h), [row[0] for row in table[1:]], fontsize=7)
    ax.set_xlabel("predicted")
    ax.set_ylabel("ground truth")
    ax.set_title(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path.with_suffix(".png"), dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------- main
def score_piece_crnn(piece: str, crnn: str, gt: dict[str, dict], gt_all: list[dict],
                     st12: dict[str, Any]) -> dict[str, Any]:
    recs = {r["strip_id"].rsplit("_vidx", 1)[0]: r for r in
            json.loads((RUNS / piece / f"stage3_{crnn}.json").read_text(encoding="utf-8"))}
    out_dir = SCORES / piece / crnn
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: dict[str, list[dict]] = {v: [] for v in VERSIONS}
    for sid, g in gt.items():
        r = recs.get(sid)
        if r is None:
            for v in VERSIONS:
                rows[v].append(score_strip(g, None, None, None, None, False))
            continue
        rows["a"].append(score_strip(g, r["tokens"], r["a"]["events"], a_clef_class(r["a"]["first_clef"], g["voice"]),
                                     a_key(r["a"]["opening_key"]), False))
        b = r["b"]
        rows["b"].append(score_strip(g, b["tokens"], b["events"], b["info"]["clef_class"], b["info"]["key"],
                                     b["info"]["review_needed"]))
        with contextlib.redirect_stdout(io.StringIO()):
            ev_o, tok_o, info_o = s3b.infer_pitch_b(r["tokens"], r["confs"], g["voice"], g["page"], g["sys"],
                                                    oracle_decision(g))
        rows["oracle"].append(score_strip(g, tok_o, ev_o, info_o["clef_class"], info_o["key"], False))
    res: dict[str, Any] = {"piece": piece, "crnn": crnn, "gt_status": GT_STATUS[piece],
                           "extra_strips_not_in_gt": sorted(set(recs) - set(gt)),
                           "repro_failures": sum(not r["repro_ok"] for r in recs.values())}
    exp = Counter(g["page"] for g in gt_all)
    got = Counter(r["page"] for r in st12["strips"])
    res["stage2_coverage"] = {str(p["page"]): dict(expected_staves=exp[p["page"]], detected=got[p["page"]],
                                                   failure=p.get("failure")) for p in st12["pages"]}
    for v in VERSIONS:
        rr = rows[v]
        det = [r for r in rr if r["detected"]]
        res[v] = dict(headline=headline(rr), ci95=boot(rr), headline_detected_only=headline(det),
                      headline_no_uncertain=headline([r for r in rr if r["n_unc"] == 0]),
                      by_voice=by(rr, lambda r: r["voice"]), by_page=by(rr, lambda r: str(r["page"])),
                      per_symbol=per_symbol(rr), per_token_class=per_token_class(rr), diagnostics=diagnostics(det),
                      strips=[{k: x for k, x in r.items() if k not in ("tok_cls", "sym", "sym_cm")} for r in rr])
        tag = {"a": "(a) Stage 3 as-is", "b": "(b) clef/key classifier", "oracle": "oracle GT clef+key"}[v]
        write_cm(out_dir / f"cm_symbol_{v}", sym_confusion(rr), f"{piece} {crnn} {tag}: symbol (duration) confusion")
        write_cm(out_dir / f"cm_clef_{v}", confusion(rr, "clef_gt", "clef_pred", CLEF_ROWS, CLEF_COLS),
                 f"{piece} {crnn} {tag}: clef")
        keys = sorted({g["key"] for g in gt.values()})
        write_cm(out_dir / f"cm_key_{v}", confusion(rr, "key_gt", "key_pred", keys, keys), f"{piece} {crnn} {tag}: key")
    res["b_minus_a_sow"] = dict(point=(res["b"]["headline"]["pitch_acc_sow"] or 0) - (res["a"]["headline"]["pitch_acc_sow"] or 0),
                                **paired_boot(rows["a"], rows["b"]))
    ha, hb = res["a"]["headline"], res["b"]["headline"]
    res["gate"] = dict(silent_wrong_b_le_a=hb["silent_wrong_rate"] <= ha["silent_wrong_rate"],
                       zero_double_octave_b=hb["double_octave_staves"] == 0,
                       sow_gain_ge_20pts=res["b_minus_a_sow"]["point"] >= 0.20,
                       review_le_25pct=hb["review_needed_rate"] <= 0.25)
    res["gate"]["pass"] = all(res["gate"].values())
    res["gated"] = piece == GATED_PIECE
    (out_dir / "score.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def main() -> None:
    summary: dict[str, Any] = {}
    for piece in PIECES:
        gt, gt_all = load_gt(piece)
        st12 = json.loads((RUNS / piece / "stage12.json").read_text(encoding="utf-8"))
        for crnn in CRNNS:
            if not (RUNS / piece / f"stage3_{crnn}.json").exists():
                continue
            res = score_piece_crnn(piece, crnn, gt, gt_all, st12)
            summary[f"{piece}/{crnn}"] = {v: {**res[v]["headline"], "ci95": res[v]["ci95"]} for v in VERSIONS}
            summary[f"{piece}/{crnn}"]["gate"] = res["gate"]
            summary[f"{piece}/{crnn}"]["b_minus_a_sow"] = res["b_minus_a_sow"]
            summary[f"{piece}/{crnn}"]["stage2_coverage"] = res["stage2_coverage"]
            h = {v: res[v]["headline"] for v in VERSIONS}
            print(f"{piece:18s} {crnn:8s} " + " | ".join(
                f"{v}: SER {h[v]['token_ser']:.3f} SOW {h[v]['pitch_acc_sow']:.3f} clef {h[v]['clef_acc'] or 0:.2f} "
                f"key {h[v]['key_acc'] or 0:.2f} silent {h[v]['silent_wrong_staves']} rev {h[v]['review_needed_rate'] or 0:.2f}"
                for v in VERSIONS) + f" | gate {res['gate']['pass']}")
    (SCORES / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
