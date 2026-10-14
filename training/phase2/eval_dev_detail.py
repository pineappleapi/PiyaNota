"""G2 report addendum: eval_dev.py rows re-aggregated for note precision and per-class recall (PIYA-106).

eval_dev.py keeps only SER, pitch and fermata totals per pool, but G2 rules section 5 also asks for note precision
(pitch_acc_sow cannot see hallucinated notes, the BUG-011 failure) and per-class recall. Both already come out of
score_eval for every row, so this imports eval_dev unchanged and keeps them. token_ser must equal eval_dev.py's
output for the same weights/strips/header; --parity <eval_dev json> asserts it (exit 1 on mismatch).

Usage (repo root):
  python training/phase2/eval_dev_detail.py --weights p2s1=... --weights p2s2=... --out <dir> [--header e1c]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_dev as ed  # noqa: E402  (sets CUDA_VISIBLE_DEVICES before torch is imported)

import torch  # noqa: E402

HEADLINE_KEYS = ("token_ser", "pitch_acc_sow", "note_precision", "note_f1", "note_count_ratio", "rhythm_acc",
                 "strict_acc", "n_gt_notes", "n_strips", "n_detected")
# Section 5 watch classes, matched as token-class prefixes (staff position already stripped by tok_class).
WATCH_PREFIXES = ("note.whole", "rest.half", "fermata", "barline")


def parity_errors(res: dict[str, Any], ref_path: Path) -> list[str]:
    """Compares pool tok_err/n_ref with an eval_dev.py JSON, matching pools by checkpoint path, not label."""
    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    if (ref["strips"], ref["header"]) != (res["strips"], res["header"]):
        return [f"{ref_path}: strips/header {ref['strips']}/{ref['header']} != {res['strips']}/{res['header']}"]
    ref_label = {str(Path(w).resolve()): lbl for lbl, w in ref["weights"].items()}
    errs: list[str] = []
    matched = 0
    for label, w in res["weights"].items():
        rl = ref_label.get(str(Path(w).resolve()))
        if rl is None:
            continue
        for cond in ed.POOLS:
            mine, theirs = res["pools"][f"{label}|{cond}"], ref["pools"][f"{rl}|{cond}"]
            matched += 1
            for k in ("tok_err", "n_ref"):
                if mine[k] != theirs[k]:
                    errs.append(f"{label}|{cond} {k}: {mine[k]} != {theirs[k]} ({ref_path})")
    if matched == 0:
        errs.append(f"{ref_path}: no checkpoint in common, nothing compared")
    return errs


def main() -> int:
    """Runs every checkpoint over both pools and writes eval_dev_detail_<strips>_<header>.json."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weights", action="append", required=True, help="label=path/to/checkpoint.pt (repeatable)")
    ap.add_argument("--strips", choices=sorted(ed.STRIP_SOURCES), default="grey")
    ap.add_argument("--header", choices=("e1c", "e1b", "none"), default="e1c")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--parity", type=Path, action="append", default=[],
                    help="eval_dev.py JSON whose pool tok_err/n_ref must match exactly (repeatable)")
    a = ap.parse_args()
    weights = dict(w.split("=", 1) for w in a.weights)
    res: dict[str, Any] = {"strips": a.strips, "header": a.header, "weights": weights, "pools": {}, "pieces": {}}
    for label, path in weights.items():
        model, _ = ed.s3.load_model(path, torch.device("cpu"))
        model.eval()
        for cond, pieces in ed.POOLS.items():
            pool_rows: list[dict[str, Any]] = []
            for piece in pieces:
                rows = ed.piece_rows(model, cond, piece, a.strips, a.header)
                h = ed.se.headline(rows)
                res["pieces"][f"{label}|{cond}|{piece}"] = {
                    **{k: h[k] for k in HEADLINE_KEYS},
                    "fermata_pred": sum(r.get("fermata_pred", 0) for r in rows)}
                pool_rows += rows
            h = ed.se.headline(pool_rows)
            res["pools"][f"{label}|{cond}"] = {
                **{k: h[k] for k in HEADLINE_KEYS},
                "tok_err": sum(r["tok_err"] for r in pool_rows), "n_ref": sum(r["n_ref"] for r in pool_rows),
                "fermata_pred": sum(r.get("fermata_pred", 0) for r in pool_rows),
                "fermata_gt": sum(r.get("fermata_gt", 0) for r in pool_rows),
                "per_token_class": ed.se.per_token_class(pool_rows)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"eval_dev_detail_{a.strips}_{a.header}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"strips={a.strips} header={a.header}  (dev data, diagnostic)")
    for key, v in res["pools"].items():
        print(f"  {key:<24} SER {ed.pct(v['token_ser'])}  pitch {ed.pct(v['pitch_acc_sow'])}  note prec "
              f"{ed.pct(v['note_precision'])}  F1 {ed.pct(v['note_f1'])}  notes pred/gt {v['note_count_ratio']:.3f}")
        for cls, c in v["per_token_class"].items():
            if cls.startswith(WATCH_PREFIXES):
                print(f"      {cls:<22} n_ref {c['n_ref']:>4}  n_pred {c['n_pred']:>4}  recall {ed.pct(c['recall_exact'])}"
                      f"  precision {ed.pct(c['precision_exact'])}")
    errs = [e for ref in a.parity for e in parity_errors(res, ref)]
    for e in errs:
        print(f"PARITY FAIL: {e}")
    if a.parity and not errs:
        print(f"parity OK against {len(a.parity)} eval_dev JSON(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
