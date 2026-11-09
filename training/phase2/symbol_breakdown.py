"""Per-symbol accuracy against the ground truth, pooled over all test pieces.

Why: the pooled token SER hides which symbol types fail. Each strip's predicted
token sequence is aligned to the Arm 1 label (header included, nothing masked)
with a Levenshtein backtrace; every ground-truth token is then counted as
matched, substituted or deleted, so accuracy is per ground-truth symbol. A strip with no prediction counts every GT token as deleted
(GT-denominated, as in the scorer). Insertions have no ground-truth symbol and are reported by predicted class.
PDF and camera are never pooled. Diagnostic only: hand-authored GT.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

GT_ROOT = Path("D:/PiyaNota/data/piyanota_dataset/10piece_test_set/_a7_gt/labels")
PRED_DIR = Path("D:/PiyaNota/data/c2_real_preds")
COARSE = (
    "note", "chordnote", "rest", "accidental", "clef", "barline", "dot",
    "slur", "metersign", "layer", "fermata", "other",
)


def fine(tok: str) -> str:
    """Token class without the staff-position suffix."""
    head = tok.rsplit("-", 1)[0] if "-" in tok else tok
    if head.startswith("note.beamed"):
        return "note.beamed*"
    if head.startswith("note.") and ".l2" in head:
        return "note.*.l2"
    return head


def coarse(tok: str) -> str:
    head = fine(tok).split(".")[0]
    return head if head in COARSE else "other"


def align(gt: list[str], pr: list[str], subs: dict[int, str] | None = None) -> tuple[list[str], list[str]]:
    """Returns per-GT outcome ('match'|'sub'|'del') and the inserted predicted tokens.

    If ``subs`` is given it is filled with GT index -> predicted token for substitutions.
    """
    n, m = len(gt), len(pr)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = d[i - 1][j - 1] + (gt[i - 1] != pr[j - 1])
            d[i][j] = min(sub, d[i - 1][j] + 1, d[i][j - 1] + 1)
    out = ["del"] * n
    ins: list[str] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (gt[i - 1] != pr[j - 1]):
            out[i - 1] = "match" if gt[i - 1] == pr[j - 1] else "sub"
            if subs is not None and gt[i - 1] != pr[j - 1]:
                subs[i - 1] = pr[j - 1]
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            out[i - 1] = "del"
            i -= 1
        else:
            ins.append(pr[j - 1])
            j -= 1
    return out, ins


def load_gt() -> dict[tuple[str, int, int, int], list[str]]:
    gt = {}
    for f in sorted(GT_ROOT.glob("*/labels.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            g = json.loads(line)
            if g["tokens"] is None:  # strip excluded from Arm 1 (dropped bars)
                continue
            gt[(g["piece"], g["page"], g["sys"], g["staff"])] = g["tokens"]
    return gt


def tally(gt: dict, pred_file: Path) -> tuple[dict, dict, Counter, int, int]:
    strips = json.loads(pred_file.read_text(encoding="utf-8"))["strips"]
    fine_c: dict[str, Counter] = {}
    coarse_c: dict[str, Counter] = {}
    ins_c: Counter = Counter()
    used = 0
    for s in strips:
        k = (s["piece"], s["page"], s["sys"], s["staff"])
        if k not in gt:
            continue
        used += 1
        out, ins = align(gt[k], s["tokens"] or [])
        for tok, o in zip(gt[k], out):
            fine_c.setdefault(fine(tok), Counter())[o] += 1
            coarse_c.setdefault(coarse(tok), Counter())[o] += 1
        ins_c.update(coarse(t) for t in ins)
    return fine_c, coarse_c, ins_c, used, len(gt)


def pct(c: Counter) -> str:
    n = sum(c.values())
    return f"{100 * c['match'] / n:.1f}"


def table(rows: dict, a: dict, b: dict, min_n: int) -> list[str]:
    lines = ["| Symbol | GT count | s1 correct % | s2 correct % | s1 sub / del | s2 sub / del |", "|---|---|---|---|---|---|"]
    for k in sorted(rows, key=lambda k: -sum(a[k].values())):
        n = sum(a[k].values())
        if n < min_n:
            continue
        lines.append(
            f"| {k} | {n} | {pct(a[k])} | {pct(b[k])} | {a[k]['sub']} / {a[k]['del']} | {b[k]['sub']} / {b[k]['del']} |"
        )
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-n", type=int, default=30)
    args = ap.parse_args()
    gt = load_gt()
    md = []
    for src in ("pdf", "camera"):
        res = {s: tally(gt, PRED_DIR / f"{s}_{src}_raw.json") for s in ("s1", "s2")}
        f1, c1, i1, u1, tot = res["s1"]
        f2, c2, i2, u2, _ = res["s2"]
        md.append(f"## {src.upper()} (raw CRNN, Arm 1 labels, header included)\n")
        md.append(f"Strips scored: seed 1 {u1}, seed 2 {u2} of {tot} labelled.\n")
        md.append("### By symbol family\n")
        md += table({k: 1 for k in c1}, c1, {k: c2.get(k, Counter()) or Counter({"match": 0}) for k in c1}, 1)
        tot_n = sum(sum(c.values()) for c in c1.values())
        tot_m = sum(c["match"] for c in c1.values())
        tot_m2 = sum(c["match"] for c in c2.values())
        md.append(f"\nAll symbols: {tot_n} GT tokens, correct {100 * tot_m / tot_n:.1f}% (s1) / {100 * tot_m2 / tot_n:.1f}% (s2).\n")
        md.append(f"Inserted tokens with no GT symbol, by predicted family (s1 / s2): "
                  + ", ".join(f"{k} {i1[k]} / {i2[k]}" for k in sorted(i1, key=lambda k: -i1[k])) + ".\n")
        md.append(f"### By symbol type (GT count at least {args.min_n})\n")
        md += table({k: 1 for k in f1}, f1, {k: f2.get(k, Counter()) or Counter({"match": 0}) for k in f1}, args.min_n)
        md.append("")
    args.out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
