"""Re-label and re-check existing Phase 1 renders without re-rendering them (PIYA-106).

Why: the converter and the SVG check can tighten after renders exist (2026-10-01: whole-bar rests drawn as breve
rests, the rest-kind check and the CRNN vocabulary guard). Verovio output depends only on the MEI and options, so a
render whose labels are unchanged is re-checked from its saved SVGs; only a render whose labels would change, or
whose SVG ids no longer match the MEI (the MEI was rebuilt after rendering; Verovio ids are random), is rendered
again with its recorded font and scale. Every render gets fresh labels.json/check.json/meta.json (current converter
sha256 and vocabulary guard fields). A render that now fails the check moves to quarantine/, as in render_corpus.

Usage: python training/phase1/recheck_renders.py --out D:/PiyaNota-training/data/phase1_renders --composers bach
"""

from __future__ import annotations

import argparse
import collections
import gc
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_corpus import check_render, labels_for, oov_summary, provenance, render_one  # noqa: E402

PAGE_RE = re.compile(r"page_(\d+)\.svg$")


def _labels_changed(old_rows: list[dict[str, object]], new: list[list[list[str]]]) -> bool:
    """True when any (system, staff) label differs, or the system counts differ."""
    old: dict[tuple[int, int], list[str]] = {
        (int(r["system"]), int(r["staff_n"])): list(r["tokens"]) for r in old_rows}  # type: ignore[arg-type]
    fresh = {(g, s + 1): toks for s, per_sys in enumerate(new) for g, toks in enumerate(per_sys)}
    return old != fresh


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--composers", default="bach,palestrina")
    parser.add_argument("--summary-name", default="recheck_summary.json")
    args = parser.parse_args()
    prov = provenance()
    corpus = args.out / "corpus"
    composers = set(args.composers.split(","))
    results: list[dict[str, object]] = []
    actions: collections.Counter[str] = collections.Counter()
    patterns: collections.Counter[str] = collections.Counter()
    t0 = time.time()
    dirs = sorted(d for d in (args.out / "renders").glob("*/*") if d.name.split("_", 1)[0] in composers)
    for i, ok_dir in enumerate(dirs):
        font, piece = ok_dir.parent.name, ok_dir.name
        plan = json.loads((corpus / f"{piece}.plan.json").read_text(encoding="utf-8"))
        mei_path = corpus / f"{piece}.mei"
        meta = json.loads((ok_dir / "meta.json").read_text(encoding="utf-8"))
        options: dict[str, object] = meta["options"]
        old_rows = json.loads((ok_dir / "labels.json").read_text(encoding="utf-8"))
        action = "rechecked"
        if _labels_changed(old_rows, labels_for(mei_path)):
            action = "rerendered_labels_changed"
        else:
            svg_paths = sorted(ok_dir.glob("page_*.svg"), key=lambda q: int(PAGE_RE.search(q.name).group(1)))  # type: ignore[union-attr]
            try:
                res = check_render(mei_path, plan, options, [q.read_text(encoding="utf-8") for q in svg_paths],
                                   ok_dir, prov)
            except (KeyError, ValueError) as exc:   # SVG ids from an earlier build of the MEI
                action = f"rerendered_stale_ids ({type(exc).__name__})"
        if action != "rechecked":
            for q in ok_dir.iterdir():
                q.unlink()
            res = render_one(mei_path, plan, str(options["font"]), int(options["scale"]), ok_dir,  # type: ignore[arg-type]
                             prov)
        actions[action.split(" ")[0]] += 1
        if not res["pass"]:
            bad_dir = args.out / "quarantine" / font / piece
            bad_dir.parent.mkdir(parents=True, exist_ok=True)
            if bad_dir.exists():
                shutil.move(str(bad_dir), str(bad_dir) + f".old{int(time.time())}")
            shutil.move(str(ok_dir), str(bad_dir))
            for f in res["failures"]:
                for d in f["diff"]:
                    patterns[d.split(":")[0]] += 1
        results.append({"piece_id": piece, "composer": piece.split("_", 1)[0], "font": font,
                        "scale": options["scale"], "action": action, "pass": res["pass"],
                        "n_failures": len(res["failures"]), "strips": res["strips"],
                        "oov_strips": res["oov_strips"], "oov_token_counts": res["oov_token_counts"]})
        del res
        gc.collect()
        if i % 50 == 0:
            print(f"{i}/{len(dirs)} {time.time() - t0:.0f}s {dict(actions)}", flush=True)
    summary = {**prov, "renders": len(results), "passed": sum(1 for r in results if r["pass"]),
               "actions": dict(actions), "failure_fields": dict(patterns), "oov": oov_summary(results),
               "results": results}
    (args.out / args.summary_name).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=1))


if __name__ == "__main__":
    main()
