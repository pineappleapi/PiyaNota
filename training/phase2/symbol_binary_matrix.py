"""One-vs-rest 2x2 confusion (TP/FN/FP/TN) per symbol type, from symbol_confusion.py output.

For symbol X: positive = "this GT token is X". TP = GT X read as type X (staff position
ignored, counted in the separate wrong-position column). FN = GT X omitted or read as another
type. FP = another GT token read as X, plus X tokens the model inserted. TN = every other GT
token not read as X. TN ignores insertions of other types, so TP+FN+FP+TN is not exactly N.
Diagnostic only: hand-authored GT.
"""
import argparse
from pathlib import Path

from symbol_confusion import DELETED, INSERTED, WRONG_POS, confusions
from symbol_breakdown import PRED_DIR, load_gt

MIN_N = 30


def merge(t: str) -> str:
    return "note.*.l2" if t.startswith("note.") and ".l2" in t else t


def counts(c: dict) -> dict:
    m: dict = {}
    for (a, b), n in c.items():
        key = (merge(a), merge(b) if b not in (DELETED, WRONG_POS) else b)
        m[key] = m.get(key, 0) + n
    n_gt = sum(n for (a, _), n in m.items() if a != INSERTED)
    out = {}
    for x in {a for a, _ in m if a != INSERTED}:
        row = sum(n for (a, _), n in m.items() if a == x)
        if row < MIN_N:
            continue
        tp = m.get((x, x), 0) + m.get((x, WRONG_POS), 0)
        fp_sub = sum(n for (a, b), n in m.items() if b == x and a not in (x, INSERTED))
        fp = fp_sub + m.get((INSERTED, x), 0)
        out[x] = dict(gt=row, tp=tp, fn=row - tp, fp=fp, tn=n_gt - row - fp_sub, wp=m.get((x, WRONG_POS), 0))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    gt = load_gt()
    md: list[str] = []
    for src in ("pdf", "camera"):
        r = {s: counts(confusions(gt, PRED_DIR / f"{s}_{src}_raw.json")) for s in ("s1", "s2")}
        md += [f"## {src.upper()}", "",
               "| Symbol | GT | s1 TP | s1 FN | s1 FP | s1 TN | s2 TP | s2 FN | s2 FP | s2 TN | wrong pos. s1 / s2 (inside TP) |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        for x in sorted(r["s1"], key=lambda k: -r["s1"][k]["gt"]):
            a, b = r["s1"][x], r["s2"][x]
            md.append(f"| {x} | {a['gt']} | {a['tp']} | {a['fn']} | {a['fp']} | {a['tn']} | "
                      f"{b['tp']} | {b['fn']} | {b['fp']} | {b['tn']} | {a['wp']} / {b['wp']} |")
        md.append("")
    args.out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
