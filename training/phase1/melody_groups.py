"""Melody groups for the Bach chorales, so the Phase 1 validation split holds out whole tunes (PIYA-106).

Why: Bach harmonised the same chorale tune many times (often in different keys), and the music21 corpus also
holds near-duplicates of one harmonisation under different BWV numbers. A split by piece alone would put the same
soprano line (and often near-identical lower voices) on both sides, so a validation score would partly measure
memorised tunes. Amendment 3 (docs/decisions/piya-106-ser-15-plan.md) requires the synthetic validation split to
be by piece/melody, not by strip.

Method: the soprano of each source score as a transposition-free interval sequence (rests ignored, repeated
pitches merged, so ornamental repeats and key do not matter); pieces whose sequences match with a
difflib ratio >= SIMILARITY_THRESHOLD, whose quarter-beat soprano matches (BEAT_SIMILARITY_THRESHOLD), or whose
openings match (OPENING_RULES), are joined
(union-find), and so are pieces whose hymn title (music21
ChoraleList, by BWV) is identical. The threshold is chosen from the observed ratio distribution, which the script
prints, not tuned on any model result.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import music21
from music21.corpus import chorales

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_corpus import _satb_order  # noqa: E402

SIMILARITY_THRESHOLD = 0.75   # difflib ratio on soprano interval sequences; see the printed histogram
# The ratio histogram has no clean gap: pairs thin out from 0.65 and plateau from 0.75. At 0.70, pairs of
# different tunes in 0.70-0.75 chain 45 pieces into one group, so 0.75 is the ratio cut.
# A whole-sequence ratio misses harmonisations whose soprano differs in length (written-out repeats, an extra
# pickup, ornaments): e.g. BWV 78.7 and 352 open identically but score 0.645. So pieces whose openings match are
# joined too, with rules strict enough not to chain common stepwise openings (12 intervals with 2 mismatches
# chained 75-99 pieces): (length, max mismatches, max shift for a missing/extra pickup interval).
OPENING_RULES: tuple[tuple[int, int, int], ...] = ((12, 0, 2), (16, 1, 2))
# Ornamented harmonisations of one tune (passing eighths in one, plain quarters in the other) differ in their
# full interval sequence; sampling the soprano on quarter beats removes most passing notes (e.g. BWV 393/394,
# 245.11/44.7, 144.6/92.9 join only this way). 0.75 keeps the largest group at 14; 0.65 chains 49 pieces.
BEAT_SIMILARITY_THRESHOLD = 0.75
BEAT_TOL = 1e-6
HIST_BINS = 20
BWV_RE = re.compile(r"bwv(\d+)")


def soprano_intervals(source: Path) -> list[int]:
    score = music21.converter.parse(str(source))
    parts = _satb_order(score)  # type: ignore[arg-type]
    if parts is None:
        raise ValueError(f"{source}: not SATB")
    midi: list[int] = []
    for n in parts[0].recurse().notes:
        if isinstance(n, music21.note.Note):
            if not midi or midi[-1] != n.pitch.midi:
                midi.append(n.pitch.midi)
    return [b - a for a, b in zip(midi, midi[1:])]


def soprano_beat_intervals(source: Path) -> list[int]:
    """Intervals between the soprano pitches that start on a quarter beat (repeats merged)."""
    score = music21.converter.parse(str(source))
    parts = _satb_order(score)  # type: ignore[arg-type]
    if parts is None:
        raise ValueError(f"{source}: not SATB")
    midi: list[int] = []
    for n in parts[0].flatten().notes:
        off = float(n.offset)
        if isinstance(n, music21.note.Note) and abs(off - round(off)) < BEAT_TOL:
            if not midi or midi[-1] != n.pitch.midi:
                midi.append(n.pitch.midi)
    return [b - a for a, b in zip(midi, midi[1:])]


def openings_match(a: list[int], b: list[int]) -> bool:
    for n, max_mismatch, max_shift in OPENING_RULES:
        for x, y in ((a, b), (b, a)):
            if len(x) < n:
                continue
            for k in range(max_shift + 1):
                seg = y[k:k + n]
                if len(seg) == n and sum(u != v for u, v in zip(x[:n], seg)) <= max_mismatch:
                    return True
    return False


def hymn_title(piece_id: str, by_bwv: dict[int, dict[str, object]]) -> str | None:
    m = BWV_RE.search(piece_id)
    if m is None:
        return None
    entry = by_bwv.get(int(m.group(1)))
    # Only standalone chorales (BWV 250-438) have one title per BWV; cantata BWVs hold several chorales, so a
    # cantata number alone would wrongly merge different tunes.
    if entry is None or "." in piece_id.split("bwv", 1)[1]:
        return None
    return str(entry["title"]).strip().lower()


class UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=Path("D:/PiyaNota-training/data/phase1_renders/corpus"))
    ap.add_argument("--prefix", default="bach_")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    plans = sorted(a.corpus.glob(f"{a.prefix}*.plan.json"))
    seqs: dict[str, list[int]] = {}
    beats: dict[str, list[int]] = {}
    for p in plans:
        plan = json.loads(p.read_text(encoding="utf-8"))
        seqs[plan["piece_id"]] = soprano_intervals(Path(plan["source"]))
        beats[plan["piece_id"]] = soprano_beat_intervals(Path(plan["source"]))
    ids = sorted(seqs)
    by_bwv = chorales.ChoraleList().byBWV
    uf = UnionFind(ids)
    hist: Counter[int] = Counter()
    joined: list[tuple[str, str, float]] = []
    for i, x in enumerate(ids):
        sm = difflib.SequenceMatcher(autojunk=False)
        sm.set_seq2(seqs[x])
        for y in ids[i + 1:]:
            sm.set_seq1(seqs[y])
            r = sm.ratio()
            hist[min(HIST_BINS - 1, int(r * HIST_BINS))] += 1
            rb = difflib.SequenceMatcher(None, beats[x], beats[y], autojunk=False).ratio()
            if r >= SIMILARITY_THRESHOLD or rb >= BEAT_SIMILARITY_THRESHOLD or openings_match(seqs[x], seqs[y]):
                uf.union(x, y)
                joined.append((x, y, round(r, 3)))
    titles: dict[str, list[str]] = {}
    for x in ids:
        t = hymn_title(x, by_bwv)
        if t is not None:
            titles.setdefault(t, []).append(x)
    for members in titles.values():
        for y in members[1:]:
            uf.union(members[0], y)
    groups: dict[str, list[str]] = {}
    for x in ids:
        groups.setdefault(uf.find(x), []).append(x)
    piece_group = {x: uf.find(x) for x in ids}
    sizes = Counter(len(v) for v in groups.values())
    print("ratio histogram (bin lower edge: pairs):")
    for b in range(HIST_BINS):
        print(f"  {b / HIST_BINS:.2f}: {hist[b]}")
    print(f"pieces {len(ids)} groups {len(groups)} size distribution {sorted(sizes.items())}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"threshold": SIMILARITY_THRESHOLD, "piece_group": piece_group,
                                 "groups": groups, "joined_pairs": joined,
                                 "ratio_histogram": {f"{b / HIST_BINS:.2f}": hist[b] for b in range(HIST_BINS)}},
                                indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
