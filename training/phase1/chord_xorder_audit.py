"""Chord head x-order audit (divisi freeze A3, corpus gate).

Chord labels list heads bottom to top; CTC reads left to right. For dyads engraving puts the lower head on the
left in every stem direction, so the two orders agree; clusters of 3+ heads can disagree. This counts the drawn
chords where a higher head sits left of a lower one, so the disagreement is reported, not assumed.

    python training/phase1/chord_xorder_audit.py --renders <render_dir> [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

SVG_NS = "{http://www.w3.org/2000/svg}"
TRANSLATE = re.compile(r"translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)")


def _cls(el: ET.Element) -> str:
    return el.attrib.get("class", "").split(" ")[0]


def _head_xy(note: ET.Element) -> tuple[float, float] | None:
    for g in note.iter(f"{SVG_NS}g"):
        if _cls(g) == "notehead":
            use = g.find(f"{SVG_NS}use")
            m = TRANSLATE.search(use.attrib.get("transform", "")) if use is not None else None
            if m:
                return float(m.group(1)), float(m.group(2))
    return None


def chord_heads(svg_text: str) -> list[tuple[str, list[tuple[float, float]]]]:
    """Every drawn chord as (data-id, head (x, y) in SVG member order)."""
    out = []
    for g in ET.fromstring(svg_text).iter(f"{SVG_NS}g"):
        if _cls(g) == "chord":
            heads = [xy for n in g if _cls(n) == "note" and (xy := _head_xy(n)) is not None]
            out.append((g.attrib.get("data-id", ""), heads))
    return out


def chord_order_mismatches(svg_text: str) -> list[dict[str, object]]:
    """Chords whose heads, sorted bottom to top (SVG y descending), are not in left-to-right x order."""
    bad = []
    for cid, heads in chord_heads(svg_text):
        ordered = sorted(heads, key=lambda h: -h[1])
        if any(b[0] < a[0] for a, b in zip(ordered, ordered[1:])):
            bad.append({"chord_id": cid, "heads": ordered})
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--renders", type=Path, required=True, help="render dir (<font>/<piece>/page_*.svg)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    chords, by_size, bad_by_size, examples = 0, Counter(), Counter(), []
    for svg in sorted(args.renders.rglob("page_*.svg")):
        text = svg.read_text(encoding="utf-8")
        for _, heads in chord_heads(text):
            chords += 1
            by_size[len(heads)] += 1
        for m in chord_order_mismatches(text):
            bad_by_size[len(m["heads"])] += 1
            examples.append({"svg": str(svg.relative_to(args.renders)), **m})
    report = {"chords": chords, "mismatches": sum(bad_by_size.values()),
              "by_size": {str(k): {"chords": by_size[k], "mismatches": bad_by_size[k]} for k in sorted(by_size)},
              "examples": examples[:50]}
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "examples"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
