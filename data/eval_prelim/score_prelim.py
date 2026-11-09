"""Scorer for the preliminary digital-vs-camera evaluation.

Metrics are computed by data/eval_fresh/score_eval.py's own functions (score_strip / headline / boot), so the
definitions are identical to the fresh-photo eval:
  * Token SER: agnostic-token Levenshtein / GT tokens (slurs/ties excluded, <OOV> GT tokens are wildcards).
  * Pitch accuracy (SOW): GT notes whose sounding pitch is matched by an aligned predicted note; notes on
    strips Stage 2 missed count as wrong.
  * Staff detection: GT staves for which Stage 2 delivered a strip with the same (page, system, voice).
    This is NOT mAP50 -- there are no staff bounding-box annotations for these pages.

Writes runs/results.json and RESULTS_tables.md.  Usage (repo root):  python data/eval_prelim/score_prelim.py
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "eval_fresh"))
sys.path.insert(0, str(HERE))

import score_eval as se  # noqa: E402
from inputs import (BSN_EXPECTED_STAVES, BSN_PHOTO_OF_PDF_PAGE, DIGITAL_PIECES, NOTE_GT_PIECES,  # noqa: E402
                    OUT_OF_SCOPE_PAGES)

RUNS = HERE / "runs"
GT_DIR = {"dont_stop_me_now": se.ROOT / "gt" / "dont_stop_me_now" / "strips_v2"}
GT_STATUS = {"non_nobis_domine": "verified by the author",
             "honneur_a_toi": "verified by the author (2026-09-28)",
             "gaano_ko_ikaw_kamahal": "verified by the author (2026-09-28)",
             "handog": "verified by the author (2026-09-28)",
             "dont_stop_me_now": "verified by the author (2026-09-28; strips_v2, pp.1-5)"}
TITLES = {"non_nobis_domine": "Non Nobis Domine", "honneur_a_toi": "Honneur a Toi",
          "gaano_ko_ikaw_kamahal": "Gaano Ko Ikaw Kamahal", "handog": "Handog",
          "dont_stop_me_now": "Don't Stop Me Now (pp. 1-5)", "both_sides_now": "Both Sides Now"}
# (model label, stage3 file, version key). Base = original main-branch pipeline; version (b) = + ClefKeyNet.
MODELS = [("Base CRNN, original pipeline", "base", "a"),
          ("Fine-tuned seed1, no classifier", "seed1", "a"),
          ("Fine-tuned seed2, no classifier", "seed2", "a"),
          ("Fine-tuned seed1 + clef/key classifier", "seed1", "b"),
          ("Fine-tuned seed2 + clef/key classifier", "seed2", "b")]


def load_gt(piece: str) -> tuple[dict[str, dict], list[dict]]:
    """score_eval.load_gt with a per-piece folder; DSMN's Tenor 'clef:G' is read as treble-8vb.

    DSMN's GT header states Tenor pitches are written treble and sound an octave lower (its events already
    store sounding pitch), i.e. the treble-8vb clef class; it just spells the clef 'G'.
    """
    d = GT_DIR.get(piece, se.ROOT / "gt" / piece)
    gt_all = json.loads((d / "gt.json").read_text(encoding="utf-8"))
    src = (d / "gt_source.txt").read_text(encoding="utf-8")
    ck = {f"page{int(m[1]):03d}_sys{int(m[2]):02d}_{m[3]}": (m[4], int(m[5]) * (1 if m[6] == "#" else -1))
          for m in re.finditer(r"^p(\d+)s(\d+) (\w+): clef:(G8|G|F) key:(\d)([#b])", src, re.M)}
    out = set(OUT_OF_SCOPE_PAGES.get(piece, []))
    gt_all = [g for g in gt_all if int(g["strip_id"][4:7]) not in out]
    gt: dict[str, dict] = {}
    for g in gt_all:
        if "excluded" in g:
            continue
        clef, key = ck[g["strip_id"]]
        if piece == "dont_stop_me_now" and g["voice"] == "Tenor" and clef == "G":
            clef = "G8"
        g["clef_class"] = {"G": "G", "G8": "G8vb", "F": "F"}[clef]
        g["key"] = key
        gt[g["strip_id"]] = g
    return gt, gt_all


def score_rows(gt: dict[str, dict], recs: dict[str, dict], version: str) -> list[dict[str, Any]]:
    rows = []
    for sid, g in gt.items():
        r = recs.get(sid)
        if r is None:
            rows.append(se.score_strip(g, None, None, None, None, False))
        elif version == "a":
            rows.append(se.score_strip(g, r["tokens"], r["a"]["events"],
                                       se.a_clef_class(r["a"]["first_clef"], g["voice"]),
                                       se.a_key(r["a"]["opening_key"]), False))
        else:
            b = r["b"]
            rows.append(se.score_strip(g, b["tokens"], b["events"], b["info"]["clef_class"], b["info"]["key"],
                                       b["info"]["review_needed"]))
    return rows


def staff_detection(gt_all: list[dict], st12: dict[str, Any], piece: str) -> dict[str, Any]:
    """In-scope GT staves (excluded ones included: they are real staves) matched by a Stage 2 strip."""
    out = set(OUT_OF_SCOPE_PAGES.get(piece, []))
    got = {s["strip_id"].rsplit("_vidx", 1)[0] for s in st12["strips"] if s["page"] not in out}
    want = [g["strip_id"] for g in gt_all]
    hit = sum(w in got for w in want)
    return dict(gt_staves=len(want), matched=hit, recall=hit / len(want), extra_strips=len(got - set(want)),
                failed_pages=[p["page"] for p in st12["pages"] if p.get("failure") and p["page"] not in out],
                out_of_scope_pages=sorted(out))


def bsn_staff(st12: dict[str, Any], pages: list[int]) -> dict[str, Any]:
    """Both Sides Now: count-based (every system is a full SATB system per the eye-verified GT)."""
    per = {p["page"]: p for p in st12["pages"]}
    got = Counter(s["page"] for s in st12["strips"])
    exp = sum(BSN_EXPECTED_STAVES[p] for p in pages)
    hit = sum(min(got[p], BSN_EXPECTED_STAVES[p]) for p in pages)
    return dict(gt_staves=exp, matched=hit, recall=hit / exp,
                extra_strips=sum(max(0, got[p] - BSN_EXPECTED_STAVES[p]) for p in pages),
                failed_pages=[p for p in pages if per[p].get("failure")])


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    h = se.headline(rows)
    with contextlib.redirect_stdout(io.StringIO()):
        ci = se.boot(rows, ("token_ser", "pitch_acc_sow"))
    keep = ("n_strips", "n_detected", "token_ser", "pitch_acc_sow", "strict_acc", "rhythm_acc", "n_gt_notes",
            "clef_acc", "key_acc", "note_precision", "review_needed_rate")
    return {**{k: h[k] for k in keep}, "ci95": ci,
            "tok_err": sum(r["tok_err"] for r in rows), "n_ref": sum(r["n_ref"] for r in rows),
            "sow_ok": sum(r["sow"][0] for r in rows), "sow_n": sum(r["sow"][1] for r in rows)}


def main() -> None:
    res: dict[str, Any] = {}
    all_rows: dict[tuple[str, str, str], list[dict]] = {}
    for cond in ("camera", "digital"):
        pieces = list(NOTE_GT_PIECES) if cond == "camera" else DIGITAL_PIECES
        for piece in pieces:
            gt, gt_all = load_gt(piece)
            work = RUNS / cond / piece
            st12_ft = json.loads((work / "stage12.json").read_text(encoding="utf-8"))
            st12_base = json.loads((work / "stage12_base.json").read_text(encoding="utf-8"))
            entry: dict[str, Any] = {"gt_status": GT_STATUS[piece],
                                     "staff": {"base": staff_detection(gt_all, st12_base, piece),
                                               "finetuned": staff_detection(gt_all, st12_ft, piece)},
                                     "models": {}}
            for label, crnn, ver in MODELS:
                recs = {r["strip_id"].rsplit("_vidx", 1)[0]: r for r in
                        json.loads((work / f"stage3_{crnn}.json").read_text(encoding="utf-8"))}
                rows = score_rows(gt, recs, ver)
                all_rows[(cond, piece, label)] = rows
                entry["models"][label] = summarise(rows)
            res[f"{cond}/{piece}"] = entry
    # Both Sides Now: staff detection only, on the 7 PDF pages that were photographed (paired), and all 9.
    for cond in ("camera", "digital"):
        work = RUNS / cond / "both_sides_now"
        e: dict[str, Any] = {"gt_status": "staff counts only (eye-verified); no note GT"}
        for pipe, f in (("base", "stage12_base.json"), ("finetuned", "stage12.json")):
            st12 = json.loads((work / f).read_text(encoding="utf-8"))
            e[pipe] = bsn_staff(st12, sorted(BSN_PHOTO_OF_PDF_PAGE))
            if cond == "digital":
                e[pipe + "_all9"] = bsn_staff(st12, sorted(BSN_EXPECTED_STAVES))
        res[f"{cond}/both_sides_now"] = e
    # Pooled (micro) over pieces: all camera pieces; and the paired digital/camera set (NN + DSMN pp.1-5).
    main_set = ["non_nobis_domine", "gaano_ko_ikaw_kamahal"]  # FROZEN in the mask split, verified GT, has PDF
    pools = {"camera_all5": ("camera", list(NOTE_GT_PIECES)),
             "camera_main": ("camera", main_set), "digital_main": ("digital", main_set)}
    res["pooled"] = {name: {label: summarise([r for p in pieces for r in all_rows[(cond, p, label)]])
                            for label, _, _ in MODELS} for name, (cond, pieces) in pools.items()}
    (RUNS / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    write_tables(res)


def pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def write_tables(res: dict[str, Any]) -> None:
    L: list[str] = ["# Preliminary results: digital vs camera (generated by score_prelim.py; do not edit)", "",
                    "SER = agnostic-token SER. Pitch = SOW pitch accuracy (missed strips count as wrong). "
                    "Staff = GT staves delivered by Stage 2 with the right (page, system, voice); not mAP50. "
                    f"Out-of-scope pages (not all-SATB systems) are not scored: {OUT_OF_SCOPE_PAGES}.", ""]
    for key, e in res.items():
        if key == "pooled" or key.endswith("both_sides_now"):
            continue
        cond, piece = key.split("/")
        L += [f"## {TITLES[piece]}, {cond} (GT: {e['gt_status']})", ""]
        for pipe, s in e["staff"].items():
            L.append(f"- Staff detection ({pipe} Stage 1/2): {s['matched']}/{s['gt_staves']} = {pct(s['recall'])}"
                     f"; extra strips {s['extra_strips']}; pages Stage 2 rejected: {s['failed_pages'] or 'none'}")
        L += ["", "| Model | Token SER [95% CI] | Pitch acc [95% CI] | Pitch+duration | Rhythm | Clef acc | "
                  "Key acc | Note precision | Strips |", "|---|---|---|---|---|---|---|---|---|"]
        for label, m in e["models"].items():
            ci = m["ci95"]
            L.append(f"| {label} | {pct(m['token_ser'])} [{pct(ci['token_ser'][0])}, {pct(ci['token_ser'][1])}] | "
                     f"{pct(m['pitch_acc_sow'])} [{pct(ci['pitch_acc_sow'][0])}, {pct(ci['pitch_acc_sow'][1])}] | "
                     f"{pct(m['strict_acc'])} | {pct(m['rhythm_acc'])} | {pct(m['clef_acc'])} | {pct(m['key_acc'])} | "
                     f"{pct(m['note_precision'])} | {m['n_detected']}/{m['n_strips']} |")
        L.append("")
    L += ["## Both Sides Now: staff detection only (7 photographed pages)", ""]
    for cond in ("camera", "digital"):
        e = res[f"{cond}/both_sides_now"]
        for pipe in ("base", "finetuned"):
            s = e[pipe]
            L.append(f"- {cond}, {pipe} Stage 1/2: {s['matched']}/{s['gt_staves']} = {pct(s['recall'])}; "
                     f"extra {s['extra_strips']}; rejected pages {s['failed_pages'] or 'none'}")
    L.append("")
    for name, models in res["pooled"].items():
        L += [f"## Pooled: {name}", "",
              "| Model | Token SER [95% CI] | Pitch acc [95% CI] | Note precision | Notes | Strips |",
              "|---|---|---|---|---|---|"]
        for label, m in models.items():
            ci = m["ci95"]
            L.append(f"| {label} | {pct(m['token_ser'])} [{pct(ci['token_ser'][0])}, {pct(ci['token_ser'][1])}] | "
                     f"{pct(m['pitch_acc_sow'])} [{pct(ci['pitch_acc_sow'][0])}, {pct(ci['pitch_acc_sow'][1])}] | "
                     f"{pct(m['note_precision'])} | {m['n_gt_notes']} | {m['n_detected']}/{m['n_strips']} |")
        L.append("")
    (HERE / "RESULTS_tables.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
