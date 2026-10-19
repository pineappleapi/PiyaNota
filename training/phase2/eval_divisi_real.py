"""Scorer for the real camera divisi test set (PIYA-106, plan 2026-10-19 Task 3).

Scores decoded token strips against the user-verified GT of the frozen registry
(`docs/decisions/piya-106-divisi-real-test-set.md`). Head alignment and bucketing are the A6 scorer's
(`eval_divisi_a6.head_scores`), so real-set and synthetic numbers are counted the same way.

Input layout: `gt_dir/<piece>.json` and `pred_dir/<piece>.json`, each `{"strips": [{"page", "staff", "tokens",
"gt_kind" (GT only), "conf" (pred only, optional: one confidence per token)}]}`. Strips are matched by (page, staff).
A GT strip with no prediction is scored as an empty read (every head missed) and counted in `missing_strips`.

python training/phase2/eval_divisi_real.py <registry.json> <pred_dir> <gt_dir> [--out result.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_divisi_a6 import (FAIL, PASS, UNDERPOWERED, UNDERPOWERED_N, _jsonable, columns, head_scores,  # noqa: E402
                            lcs_pairs, merge_scores, shape, step_of, wilson_lb)

GT_KINDS = ("same_stem", "split_same_rhythm", "split_two_rhythm")
# Draft D1 bar (real-test-set doc, user decision pending): chord-member pitch accuracy >= 85%.
D1_DRAFT_RECALL = 0.85
CONFIDENT = 0.90                  # confident-wrong threshold (A3 metrics)
SECOND_STEPS = 1                  # a 2nd is one staff step between the two heads


def second_as_sequence(pred: Sequence[str], gt: Sequence[str]) -> int:
    """GT 2nd dyads read as two successive notes at the same two positions (A3 metric, counted as a miss too)."""
    gcols, pcols = columns(gt), columns(pred)
    aligned = dict(lcs_pairs([shape(c[1]) for c in gcols], [shape(c[1]) for c in pcols]))
    used = set(aligned.values())
    count = 0
    for gi, (_ti, note, ext, _acc) in enumerate(gcols):
        pi = aligned.get(gi)
        if len(ext) != 1 or pi is None or pcols[pi][2] or pi + 1 >= len(pcols) or pi + 1 in used:
            continue
        lo, hi = step_of(note), step_of(ext[0])
        if hi - lo == SECOND_STEPS and step_of(pcols[pi][1]) == lo and step_of(pcols[pi + 1][1]) == hi:
            count += 1
    return count


def _load_strips(path: Path) -> dict[tuple[str, int], Mapping[str, Any]]:
    if not path.exists():
        return {}
    return {(s["page"], int(s["staff"])): s for s in json.loads(path.read_text(encoding="utf-8"))["strips"]}


def _bucket(hit: int, n: int) -> dict[str, Any]:
    recall = hit / n if n else 0.0
    verdict = UNDERPOWERED if n < UNDERPOWERED_N else (PASS if recall >= D1_DRAFT_RECALL else FAIL)
    return {"n": n, "hit": hit, "recall": recall, "wilson95": (wilson_lb(hit, n), 1.0 - wilson_lb(n - hit, n)),
            "verdict": verdict}


def score(registry: Path, pred_dir: Path, gt_dir: Path) -> dict[str, Any]:
    """Scores every registered piece; buckets keyed `<gt_kind>:<interval bucket>`.

    Precision, `second_as_sequence` and `confident_wrong_090` are per GT kind, not per bucket: a wrong extra head
    has no GT interval to be bucketed under.

    Raises:
        ValueError: the registry is not frozen, a piece has no GT file, a GT chord strip has no valid `gt_kind`,
            or a pred `conf` list does not match its tokens.
    """
    reg = json.loads(Path(registry).read_text(encoding="utf-8"))
    if not reg.get("frozen"):
        raise ValueError("registry is not frozen: score only after the user signs off the GT")
    parts: dict[str, list[dict[str, Any]]] = {}
    seq: dict[str, int] = {}
    missing = 0
    plain_extra = plain_cols = 0
    for piece in reg["pieces"]:
        gt_path = Path(gt_dir) / f"{piece['piece']}.json"
        if not gt_path.exists():
            raise ValueError(f"no GT for registered piece {piece['piece']}")
        preds = _load_strips(Path(pred_dir) / f"{piece['piece']}.json")
        for key, g in _load_strips(gt_path).items():
            p = preds.get(key)
            missing += p is None
            ptoks = list(p["tokens"]) if p else []
            conf = p.get("conf") if p else None
            if conf is not None and len(conf) != len(ptoks):
                raise ValueError(f"{piece['piece']} {key}: {len(conf)} confidences for {len(ptoks)} tokens")
            s = head_scores(ptoks, g["tokens"], None, conf)
            plain_extra += s["plain_extra"]
            plain_cols += s["plain_cols"]
            if not s["chord_cols"]:
                continue
            kind = g.get("gt_kind")
            if kind not in GT_KINDS:
                raise ValueError(f"{piece['piece']} {key}: chord strip needs gt_kind in {GT_KINDS}, got {kind!r}")
            parts.setdefault(kind, []).append(s)
            seq[kind] = seq.get(kind, 0) + second_as_sequence(ptoks, g["tokens"])
    buckets: dict[str, dict[str, Any]] = {}
    kinds: dict[str, dict[str, Any]] = {}
    for kind, ps in parts.items():
        t = merge_scores(ps)
        for name, (hit, n) in sorted(t["bucket"].items()):
            buckets[f"{kind}:{name}"] = _bucket(hit, n)
        heads = t["gt_heads"]
        kinds[kind] = {"heads": heads, "recall": t["tp"] / max(1, heads),
                       "precision": t["tp"] / max(1, t["tp"] + t["fp_chord"]),
                       "unaligned_cols": t["unaligned"], "second_as_sequence": seq[kind],
                       "confident_wrong_090": sum(1 for c, ok in t["head_conf"] if c >= CONFIDENT and not ok),
                       "pred_chordnotes": len(t["head_conf"])}
    return {"buckets": buckets, "kinds": kinds, "missing_strips": missing,
            "plain": {"cols": plain_cols, "extra_heads": plain_extra}, "d1_draft_recall": D1_DRAFT_RECALL}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("registry", type=Path)
    ap.add_argument("pred_dir", type=Path)
    ap.add_argument("gt_dir", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    text = json.dumps(_jsonable(score(a.registry, a.pred_dir, a.gt_dir)), indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
