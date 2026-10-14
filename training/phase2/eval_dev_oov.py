"""Counts predicted tokens that GT <OOV> wildcard spans absorb, which token SER never scores (BUG-049/BUG-050).

score_eval.align lets each GT <OOV> token consume 0..TOKEN_OOV_SPAN predicted tokens at zero cost, and
per_token_class only counts aligned tokens, so tokens written inside those spans are invisible to SER and to
token-level precision. This re-runs the same alignment per strip (eval_dev.py imported unchanged) and reports,
per pool, how many predicted note and fermata tokens were scored vs absorbed, plus an all-in note precision whose
denominator includes the absorbed notes.

Usage (repo root):
  python training/phase2/eval_dev_oov.py --weights p2s1=... --weights p2s2=... --out <dir> [--header e1c]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_dev as ed  # noqa: E402  (sets CUDA_VISIBLE_DEVICES before torch is imported)

import torch  # noqa: E402

se = ed.se
_tally: Counter = Counter()
_orig_score_strip = se.score_strip


def _kind(tok: str) -> Optional[str]:
    if tok.startswith("note."):
        return "note"
    if tok.startswith("fermata"):
        return "fermata"
    return None


def _score_and_tally(g: dict[str, Any], sub: Optional[list[str]], *rest: Any) -> dict[str, Any]:
    """Same inputs as score_strip; the alignment is recomputed exactly as score_strip builds it."""
    if sub is not None:
        ref = [("W", se.TOKEN_OOV_SPAN) if t == "<OOV>" else se.norm_tok(t) for t in g["agnostic"]
               if t != "<TIEX>" and not t.startswith("slur")]
        hyp = [se.norm_tok(t) for t in sub if not t.startswith("slur")]
        _, ops = se.align(ref, hyp, lambda a, b: a == b)
        for k, ri, hj in ops:
            if k == "W":
                for j in range(*hj):
                    if (kind := _kind(hyp[j])) is not None:
                        _tally[f"{kind}_in_oov"] += 1
            elif hj is not None and (kind := _kind(hyp[hj])) is not None:
                _tally[f"{kind}_scored"] += 1
                if k == "M" and kind == "note":
                    _tally["note_exact"] += 1
        _tally["gt_oov_tokens"] += sum(t == "<OOV>" for t in g["agnostic"])
    return _orig_score_strip(g, sub, *rest)


se.score_strip = _score_and_tally


def main() -> int:
    """Runs every checkpoint over both pools and writes eval_dev_oov_<strips>_<header>.json."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weights", action="append", required=True, help="label=path/to/checkpoint.pt (repeatable)")
    ap.add_argument("--strips", choices=sorted(ed.STRIP_SOURCES), default="grey")
    ap.add_argument("--header", choices=("e1c", "e1b", "none"), default="e1c")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    weights = dict(w.split("=", 1) for w in a.weights)
    res: dict[str, Any] = {"strips": a.strips, "header": a.header, "weights": weights,
                           "oov_span": se.TOKEN_OOV_SPAN, "pools": {}}
    for label, path in weights.items():
        model, _ = ed.s3.load_model(path, torch.device("cpu"))
        model.eval()
        for cond, pieces in ed.POOLS.items():
            _tally.clear()
            for piece in pieces:
                ed.piece_rows(model, cond, piece, a.strips, a.header)
            t = dict(_tally)
            n_pred_all = t.get("note_scored", 0) + t.get("note_in_oov", 0)
            t["note_precision_aligned"] = t.get("note_exact", 0) / t["note_scored"] if t.get("note_scored") else None
            t["note_precision_all_in"] = t.get("note_exact", 0) / n_pred_all if n_pred_all else None
            res["pools"][f"{label}|{cond}"] = t
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"eval_dev_oov_{a.strips}_{a.header}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    for key, v in res["pools"].items():
        print(f"  {key:<16} GT <OOV> {v.get('gt_oov_tokens', 0):>4}  notes scored/in-OOV {v.get('note_scored', 0)}/"
              f"{v.get('note_in_oov', 0)}  fermatas scored/in-OOV {v.get('fermata_scored', 0)}/"
              f"{v.get('fermata_in_oov', 0)}  note prec aligned {ed.pct(v['note_precision_aligned'])}"
              f"  all-in {ed.pct(v['note_precision_all_in'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
