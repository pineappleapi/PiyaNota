"""Gate G2 dev scorer: Stage 3 only, on stored eval_prelim Stage 1/2 strips, one or more CRNN checkpoints (PIYA-106).

Dev data only (eval_prelim pieces): never held-out evidence, never used to pick a checkpoint inside training.

Path per strip, the one the E1c numbers in docs/decisions/piya-106-ser-15-plan.md were measured with:
  greedy decode (stage3_transcription.transcribe_strip) -> header filter over the whole system
  (stage3_transcription.filter_header_hallucinations = E1c, the implemented pipeline rule) -> version (b):
  infer_pitch with the stored ClefKeyNet decision as header override, header tokens substituted
  (stage3_clefkey.substitute_header) -> data/eval_fresh/score_eval.score_strip.
ClefKeyNet does not depend on the CRNN, so its stored decisions (runs/<cond>/<piece>/stage3_seed1.json, field b.info)
are reused rather than recomputed. Later system checks (R1 key continuity, R4 mid-strip changes) are not applied,
as in the E1c measurement; they fired 0 times on dev data.

Two strip sources:
  --strips grey  : D:/PiyaNota/datasets/phase2_dev_strips/grey_live (Stage 1 grey + paper_fill, the source Phase 1
                   trained on). The G2 comparison uses this one.
  --strips binary: the stored runs/<cond>/<piece>/strips (pre-E7 binary), on which E1c was recorded. Use it only to
                   check that this script reproduces the recorded E1c row.

Usage (repo root):
  python training/phase2/eval_dev.py --weights seed1=D:/.../finetuned_font_seed1.pt --weights seed2=... [--strips grey]
Prints one table; full per-piece detail goes to <out>/eval_dev_<strips>_<header>.json.
"""
from __future__ import annotations

import os

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # CPU: deterministic decode, same numbers on every rerun

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Optional

import cv2
import torch

torch.cuda.is_available = lambda: False  # stage modules pick their device from this
REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "data" / "eval_fresh"), str(REPO / "data" / "eval_prelim")]

import score_eval as se  # noqa: E402
import score_prelim as sp  # noqa: E402
import stage3_clefkey as s3b  # noqa: E402
import stage3_transcription as s3  # noqa: E402
from inputs import NOTE_GT_PIECES  # noqa: E402

RUNS = Path("D:/PiyaNota-training/data/eval_prelim/runs")
STRIP_SOURCES = {"grey": Path("D:/PiyaNota/datasets/phase2_dev_strips/grey_live"), "binary": RUNS}
POOLS = {"camera": list(NOTE_GT_PIECES), "digital": ["non_nobis_domine", "gaano_ko_ikaw_kamahal"]}
CLEF_TOKEN = {"G": "clef.G-L2", "G8vb": "clef.G-L2", "F": "clef.F-L4"}
E1B_CLASSES = ("digit", "metersign", "fermata", "multirest")  # step-6 rule, kept only for its parity check
IMG_HEIGHT = 64
# Recorded references (seed range), printed beside the result; see the plan doc section 1 and the step 6 notes.
REFERENCE = {
    ("binary", "e1c"): "camera SER 26.83-28.43%, pitch 85.16% | digital SER 16.30-16.54%, pitch 89.78-90.18%",
    ("grey", "e1b"): "camera SER 15.61-16.17% (step 6, 753/780 errors of 4,823)",
}


def strip_png(source: str, cond: str, piece: str, strip_id: str) -> Path:
    root = STRIP_SOURCES[source]
    return root / cond / piece / "strips" / f"{strip_id}.png" if source == "binary" else \
        root / cond / piece / f"{strip_id}.png"


def header_e1b(toks: list[str], first_system: bool) -> list[str]:
    if first_system:
        return toks
    first_bar = next((i for i, t in enumerate(toks) if t.startswith("barline")), len(toks))
    return [t for i, t in enumerate(toks) if i >= first_bar or not t.startswith(E1B_CLASSES)]


def piece_rows(model: s3.CRNN, cond: str, piece: str, source: str, header: str) -> list[dict[str, Any]]:
    """score_strip rows for every GT strip of one piece (a strip Stage 2 missed scores as missed)."""
    gt, _ = sp.load_gt(piece)
    recs_l = json.loads((RUNS / cond / piece / "stage3_seed1.json").read_text(encoding="utf-8"))
    sys_key: dict[tuple[int, int], int] = {}
    for r in recs_l:
        sys_key.setdefault((r["page"], r["system"]), r["b"]["info"]["key"])
    order = sorted(sys_key)
    next_key = {a: sys_key[b] for a, b in zip(order, order[1:]) if b in ((a[0], a[1] + 1), (a[0] + 1, 1))}

    raw: dict[str, list[str]] = {}
    for r in recs_l:
        png = strip_png(source, cond, piece, r["strip_id"])
        if png.exists():
            img = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
            with contextlib.redirect_stdout(io.StringIO()):
                raw[r["strip_id"]] = s3.transcribe_strip(img, model, torch.device("cpu"), IMG_HEIGHT)
    first = min(sys_key)
    toks: dict[str, list[str]] = {}
    if header == "e1c":
        systems: dict[tuple[int, int], dict[str, tuple[str, list[str]]]] = {}
        for r in recs_l:
            if r["strip_id"] in raw:
                systems.setdefault((r["page"], r["system"]), {})[r["strip_id"]] = (r["voice"], raw[r["strip_id"]])
        running: dict[str, tuple] = {}
        for key in sorted(systems):
            keep, _, running = s3.filter_header_hallucinations(systems[key], running, key == first)
            for sid, idx in keep.items():
                toks[sid] = [raw[sid][i] for i in idx]
    else:
        for r in recs_l:
            if r["strip_id"] in raw:
                is_first = (r["page"], r["system"]) == first
                toks[r["strip_id"]] = header_e1b(raw[r["strip_id"]], is_first) if header == "e1b" else raw[r["strip_id"]]

    recs = {r["strip_id"].rsplit("_vidx", 1)[0]: r for r in recs_l}
    rows: list[dict[str, Any]] = []
    for sid, g in gt.items():
        r = recs.get(sid)
        if r is None or r["strip_id"] not in toks:
            rows.append(se.score_strip(g, None, None, None, None, False))
            continue
        info = r["b"]["info"]
        clef = CLEF_TOKEN[info["clef_class"]]
        t = toks[r["strip_id"]]
        ones = [1.0] * len(t)
        with contextlib.redirect_stdout(io.StringIO()):
            ev = s3.infer_pitch(list(t), voice=r["voice"], page_index=r["page"], sys_idx=r["system"],
                                confidences=ones, header_override=s3.HeaderOverride(clef, info["key"],
                                                                                    info["octave_shift"]),
                                next_system_key=next_key.get((r["page"], r["system"])))
            sub, _, _ = s3b.substitute_header(t, ones, clef, info["key"])
        row = se.score_strip(g, sub, ev, None, None, False)
        # Bach training strips are fermata-dense and LCS recall cannot see insertions, so the pools report predicted
        # vs GT fermata totals (ml-cv-lead P5, 2026-10-11).
        row["fermata_pred"] = sum(x.startswith("fermata") for x in sub)
        row["fermata_gt"] = sum(str(x).startswith("fermata") for x in g["agnostic"])
        rows.append(row)
    return rows


def pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{100 * x:.2f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weights", action="append", required=True, help="label=path/to/checkpoint.pt (repeatable)")
    ap.add_argument("--strips", choices=sorted(STRIP_SOURCES), default="grey")
    ap.add_argument("--header", choices=("e1c", "e1b", "none"), default="e1c")
    ap.add_argument("--out", type=Path, default=Path("D:/PiyaNota/datasets/phase2_eval_dev"))
    a = ap.parse_args()
    weights = dict(w.split("=", 1) for w in a.weights)
    res: dict[str, Any] = {"strips": a.strips, "header": a.header, "weights": weights, "pools": {}, "pieces": {}}
    for label, path in weights.items():
        model, _ = s3.load_model(path, torch.device("cpu"))
        model.eval()
        for cond, pieces in POOLS.items():
            pool_rows: list[dict[str, Any]] = []
            for piece in pieces:
                rows = piece_rows(model, cond, piece, a.strips, a.header)
                h = se.headline(rows)
                res["pieces"][f"{label}|{cond}|{piece}"] = {k: h[k] for k in ("token_ser", "pitch_acc_sow",
                                                                              "n_strips", "n_detected")}
                pool_rows += rows
            h = se.headline(pool_rows)
            res["pools"][f"{label}|{cond}"] = {"token_ser": h["token_ser"], "pitch_acc_sow": h["pitch_acc_sow"],
                                               "tok_err": sum(r["tok_err"] for r in pool_rows),
                                               "n_ref": sum(r["n_ref"] for r in pool_rows),
                                               "n_strips": h["n_strips"], "n_detected": h["n_detected"],
                                               "fermata_pred": sum(r.get("fermata_pred", 0) for r in pool_rows),
                                               "fermata_gt": sum(r.get("fermata_gt", 0) for r in pool_rows)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"eval_dev_{a.strips}_{a.header}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"strips={a.strips} header={a.header}  (dev data, diagnostic; G2 = >=3 pp SER drop, both seeds)")
    for key, v in res["pools"].items():
        print(f"  {key:<24} SER {pct(v['token_ser'])} ({v['tok_err']}/{v['n_ref']})  pitch {pct(v['pitch_acc_sow'])}"
              f"  strips {v['n_detected']}/{v['n_strips']}  fermata pred/gt {v['fermata_pred']}/{v['fermata_gt']}")
    if (a.strips, a.header) in REFERENCE:
        print(f"  recorded reference: {REFERENCE[(a.strips, a.header)]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
