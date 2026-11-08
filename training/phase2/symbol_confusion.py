"""Confusion matrix of GT symbol type vs predicted symbol type, pooled over test pieces.

Why: symbol_breakdown.py says how often a symbol is wrong; this says what it is mistaken for.
Uses the same Levenshtein alignment. Type = token without the staff-position suffix, so a
note read at the wrong staff position is reported as 'same type, wrong position' and not as
a type confusion. Deletions are the '(deleted)' column; insertions the '(inserted)' row.
Writes a ranked markdown table and a full CSV matrix per source and seed. Diagnostic only.
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from symbol_breakdown import PRED_DIR, align, load_gt

DELETED = "(deleted)"
INSERTED = "(inserted)"
WRONG_POS = "same type, wrong position"


def head(tok: str) -> str:
    return tok.rsplit("-", 1)[0] if "-" in tok else tok


def confusions(gt: dict, pred_file: Path) -> Counter:
    """Counter of (gt_type, pred_type_or_marker)."""
    c: Counter = Counter()
    for s in json.loads(pred_file.read_text(encoding="utf-8"))["strips"]:
        k = (s["piece"], s["page"], s["sys"], s["staff"])
        if k not in gt:
            continue
        g, p = gt[k], s["tokens"] or []
        subs: dict[int, str] = {}
        out, ins = align(g, p, subs)
        for i, (tok, o) in enumerate(zip(g, out)):
            t = head(tok)
            if o == "match":
                c[(t, t)] += 1
            elif o == "del":
                c[(t, DELETED)] += 1
            else:
                pt = head(subs[i])
                c[(t, WRONG_POS if pt == t else pt)] += 1
        for t in ins:
            c[(INSERTED, head(t))] += 1
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True, help="markdown output")
    ap.add_argument("--csv-dir", type=Path, required=True)
    ap.add_argument("--min-count", type=int, default=5)
    args = ap.parse_args()
    gt = load_gt()
    args.csv_dir.mkdir(parents=True, exist_ok=True)
    md: list[str] = []
    for src in ("pdf", "camera"):
        res = {s: confusions(gt, PRED_DIR / f"{s}_{src}_raw.json") for s in ("s1", "s2")}
        for seed, c in res.items():
            types = sorted({a for a, _ in c} | {b for _, b in c})
            with (args.csv_dir / f"confusion_{src}_{seed}.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["gt \\ predicted", *types])
                for a in types:
                    w.writerow([a, *[c.get((a, b), 0) for b in types]])
        errs = {k for c in res.values() for k, n in c.items() if k[0] != k[1] and n >= args.min_count}
        md.append(f"## {src.upper()}: what each ground-truth symbol is mistaken for\n")
        md.append(f"Pairs with at least {args.min_count} occurrences in either seed, most frequent first (seed 1 order). "
                  "Rows are GT type, columns the model's reading; '(deleted)' = model omitted it.\n")
        md.append("| GT symbol | Model read | s1 | s2 | GT total |")
        md.append("|---|---|---|---|---|")
        tot = Counter()
        for (a, _), n in res["s1"].items():
            tot[a] += n
        for a, b in sorted(errs, key=lambda k: -res["s1"].get(k, 0)):
            md.append(f"| {a} | {b} | {res['s1'].get((a, b), 0)} | {res['s2'].get((a, b), 0)} | {tot[a]} |")
        md.append("")
    args.out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
