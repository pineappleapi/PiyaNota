"""A6 feasibility count: are there enough chord-capable whole notes for duration weighting alone? (PIYA-106)

Why this exists: the divisi corpus rebuild (docs/decisions/piya-106-divisi-a6-design.md section 4) wants at least 12%
of chord columns on whole notes at a planned chord share of 40% of chord-capable notes. If the train-split Bach pieces
hold too few whole notes, Task 3 must enable `merge_to_whole` instead of relying on weighting. Counts use the same
chord-capable rule as `inject_divisi` (not tied, grace or tuplet) on the same normalised parts.

Usage: python -I training/phase1/divisi_a6_feasibility.py --manifest <phase2_manifest.jsonl>
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import music21

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_corpus import DIVISI_SUFFIX, VOICES, _normalise_clefs, _satb_order  # noqa: E402

DURATION_CLASSES: tuple[str, ...] = ("whole", "half", "dotted", "quarter", "beamed", "other")
BEAMED_TYPES: frozenset[str] = frozenset({"eighth", "16th", "32nd", "64th", "128th"})
WHOLE_SHARE_TARGET = 0.12     # design section 4: whole-note chord columns as a share of all chord columns
PLANNED_CHORD_SHARE = 0.4     # design section 4: chords as a share of chord-capable notes
COMPOSER = "bach"
SOURCE_SUFFIXES: tuple[str, ...] = (".mxl", ".xml", ".musicxml", ".krn")
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "docs" / "decisions" / "piya-106-divisi-a6-feasibility.json"


def duration_class(dur: music21.duration.Duration) -> str:
    """Class of a note's written duration; any dot makes it `dotted` whatever the base value."""
    if dur.dots > 0:
        return "dotted"
    if dur.type in BEAMED_TYPES:
        return "beamed"
    return dur.type if dur.type in ("whole", "half", "quarter") else "other"


def is_chord_capable(n: music21.note.Note) -> bool:
    """Same exclusions as `inject_divisi`: it never chords tied, grace or tuplet notes."""
    return not (n.duration.isGrace or n.duration.tuplets or n.tie is not None)


def train_bach_pieces(manifest: Path) -> set[str]:
    """Base piece ids (divisi suffix stripped) of the train split; a piece in both splits is an error."""
    split_of: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if split_of.setdefault(row["piece"], row["split"]) != row["split"]:
            raise SystemExit(f"{row['piece']} is in both splits of {manifest}")
    return {p.removesuffix(DIVISI_SUFFIX) for p, s in split_of.items() if s == "train" and p.startswith(COMPOSER + "_")}


def count_piece(path: Path) -> dict[str, collections.Counter[str]] | None:
    """Counts by voice and class for one source piece, or None when it is not four-part SATB."""
    score = music21.converter.parse(str(path))
    parts = _satb_order(score) if isinstance(score, music21.stream.Score) else None
    if parts is None:
        return None
    _normalise_clefs(parts)
    out: dict[str, collections.Counter[str]] = {v: collections.Counter() for v in VOICES}
    for voice, part in zip(VOICES, parts):
        for n in part.recurse().getElementsByClass(music21.note.Note):
            if is_chord_capable(n):
                out[voice][duration_class(n.duration)] += 1
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    wanted = train_bach_pieces(args.manifest)
    by_voice: dict[str, collections.Counter[str]] = {v: collections.Counter() for v in VOICES}
    found: set[str] = set()
    for p in sorted(music21.corpus.getComposer(COMPOSER), key=str):
        path = Path(str(p))
        piece_id = f"{COMPOSER}_{path.stem}".replace(" ", "_")
        if path.suffix not in SOURCE_SUFFIXES or piece_id not in wanted:
            continue
        counts = count_piece(path)
        if counts is None:
            continue
        found.add(piece_id)
        for voice, c in counts.items():
            by_voice[voice].update(c)
    by_class = {c: sum(by_voice[v][c] for v in VOICES) for c in DURATION_CLASSES}
    total = sum(by_class.values())
    threshold = WHOLE_SHARE_TARGET * PLANNED_CHORD_SHARE * total
    result = {
        "manifest": str(args.manifest), "pieces_in_manifest": len(wanted), "pieces_counted": len(found),
        "missing_pieces": sorted(wanted - found), "total_chord_capable": total, "by_class": by_class,
        "by_voice": {v: dict(by_voice[v]) for v in VOICES},
        "whole_share_target": WHOLE_SHARE_TARGET, "planned_chord_share": PLANNED_CHORD_SHARE,
        "whole_count_threshold": threshold, "merge_to_whole_needed": by_class["whole"] < threshold,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "missing_pieces"}, indent=2))
    print(f"missing pieces: {len(result['missing_pieces'])}")


if __name__ == "__main__":
    main()
