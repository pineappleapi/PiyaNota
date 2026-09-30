"""Gate G1 for the MEI -> agnostic converter: token agreement with Camera-PrIMuS gold (PIYA-106 Phase 1 step 1).

Agreement = 1 - sum(edit distance) / sum(gold tokens) over every sample that has both an `.mei` and an
`.agnostic`. A sample the converter refuses (ConversionError) scores its full gold length as errors, so the gate
cannot be passed by dropping hard samples. Pass: agreement >= 0.99 (docs/decisions/piya-106-ser-15-plan.md).

CPM is the converter's development set as well as its gate: the rules in `music_to_agnostic` were read off CPM
gold. G1 therefore shows the converter reproduces CPM's labelling engine; it does not show the labels are right
for SATB layouts, which is what the G1b human spot-check of rendered strips is for.

Usage: python training/g1_converter_gate.py --corpus <CameraPrIMuS Corpus dir> [--out report.json]
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from music_to_agnostic import ConversionError, convert_file  # noqa: E402

G1_THRESHOLD = 0.99
TOP_PATTERNS = 40
EXAMPLES_PER_PATTERN = 3


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    total_gold = total_err = exact = n = 0
    refused: collections.Counter[str] = collections.Counter()
    patterns: collections.Counter[str] = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)
    missing_mei: list[str] = []
    for sample in sorted(p for p in args.corpus.iterdir() if p.is_dir()):
        gold_path = next(sample.glob("*.agnostic"), None)
        mei_path = next(sample.glob("*.mei"), None)
        if gold_path is None:
            continue
        if mei_path is None:
            missing_mei.append(sample.name)
            continue
        gold = gold_path.read_text(encoding="utf-8").split()
        n += 1
        total_gold += len(gold)
        try:
            hyp = convert_file(mei_path)
        except ConversionError as exc:
            refused[str(exc)] += 1
            total_err += len(gold)
            continue
        if hyp == gold:
            exact += 1
            continue
        total_err += edit_distance(hyp, gold)
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=hyp, b=gold, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            key = f"{op}: {' '.join(hyp[i1:i2])} -> {' '.join(gold[j1:j2])}"
            patterns[key] += 1
            if len(examples[key]) < EXAMPLES_PER_PATTERN:
                examples[key].append(sample.name)

    agreement = 1 - total_err / total_gold if total_gold else 0.0
    report = {
        "samples": n, "gold_tokens": total_gold, "errors": total_err, "agreement": agreement,
        "exact_samples": exact, "refused": dict(refused), "missing_mei": missing_mei,
        "gate": "PASS" if agreement >= G1_THRESHOLD else "FAIL", "threshold": G1_THRESHOLD,
        "top_patterns": [{"pattern": k, "count": c, "examples": examples[k]}
                         for k, c in patterns.most_common(TOP_PATTERNS)],
    }
    print(f"samples {n}  gold tokens {total_gold}  errors {total_err}  agreement {agreement:.5f}  "
          f"exact {exact}/{n}  refused {sum(refused.values())}  missing mei {len(missing_mei)}  -> {report['gate']}")
    for k, c in refused.most_common():
        print(f"  refused {c:4d}  {k}")
    for row in report["top_patterns"]:
        print(f"  {row['count']:5d}  {row['pattern'][:160]}  e.g. {row['examples'][0]}")
    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
