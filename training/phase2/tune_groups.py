"""Group the Phase 1 Bach chorales by tune for the Phase 2 train/val split (PIYA-106, ml-cv-lead P5 blocker 1).

Why: many chorale tunes are harmonised in several BWVs, so a split by BWV can put the same soprano line on both sides
and inflate the val SER used for checkpoint selection. Pieces are joined (union-find) when their soprano melodies
share the opening or the closing interval sequence; joining on either end errs towards larger groups, which only
makes val more conservative. A tune whose harmonisations differ in both the opening and the closing (ornamented
soprano) can still split; that residual is accepted and recorded in Amendment 4.

The groups are computed once here (music21 Bach corpus, local) and committed as tune_groups.json, so the Kaggle
kernel reproduces the split from the repo bundle without music21's corpus.

Usage: python training/phase2/tune_groups.py <recut_out_dir>
Writes training/phase2/tune_groups.json ({"piece": "group id"}, group id = smallest piece id in the group).
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

from music21 import corpus

# Interval counts compared at each end. Closings are longer because chorales share stock cadences: an 8-interval
# closing chained unrelated tunes into one 42-piece group (2026-10-11), while 12 gives a largest group of 11 pieces.
HEAD_INTERVALS = 8
TAIL_INTERVALS = 12
OUT = Path(__file__).with_name("tune_groups.json")


def soprano_intervals(piece: str) -> list[int]:
    """Semitone intervals of the soprano line, repeated pitches (ties, repeated notes) collapsed."""
    score = corpus.parse("bach/" + piece.removeprefix("bach_"))
    pitches = [n.pitch.midi for n in score.parts[0].recurse().notes if n.isNote]
    collapsed = [p for i, p in enumerate(pitches) if i == 0 or p != pitches[i - 1]]
    return [b - a for a, b in zip(collapsed, collapsed[1:])]


def main() -> int:
    pieces = sorted({p.name for p in (Path(sys.argv[1]) / "pages").glob("*/*") if p.is_dir()})
    parent = {p: p for p in pieces}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_key: dict[tuple[str, tuple[int, ...]], list[str]] = collections.defaultdict(list)
    for piece in pieces:
        iv = soprano_intervals(piece)
        if len(iv) < TAIL_INTERVALS:
            raise SystemExit(f"{piece}: soprano too short to fingerprint ({len(iv)} intervals)")
        by_key[("head", tuple(iv[:HEAD_INTERVALS]))].append(piece)
        by_key[("tail", tuple(iv[-TAIL_INTERVALS:]))].append(piece)
    for members in by_key.values():
        for m in members[1:]:
            ra, rb = find(members[0]), find(m)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups = {p: find(p) for p in pieces}
    OUT.write_text(json.dumps(groups, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sizes = collections.Counter(collections.Counter(groups.values()).values())
    print(f"pieces {len(pieces)}  groups {len(set(groups.values()))}  group sizes {dict(sorted(sizes.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
