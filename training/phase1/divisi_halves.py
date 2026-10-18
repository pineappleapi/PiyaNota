"""Tuning / test halves of the A6 validation pieces, split by tune instead of by piece (PIYA-106 A6.1, review round 1).

Why: Bach harmonised one chorale tune many times, so a piece-level crc32 split put two settings of the same tune on
opposite sides (the senior review found two such groups straddling). A test half that shares a melody with the tuning
half is not independent. The unit here is a tune group: pieces whose soprano starts with the same first
MELODY_INTERVALS melodic intervals (a transposition-invariant hash) or that carry the same hymn title are joined, and
the half is a function of the group, so a group is never split.

One function for every consumer (the Kaggle build kernel, `training/phase2/eval_divisi_a6.py` and
`training/phase2/train_phase2.py`); the kernel writes the result to halves.json and the other two read it with
`load_groups`, so no consumer needs music21. Imbalance of the resulting halves is accepted and reported, never re-rolled
(a re-roll after seeing the result would be a choice of test set).

The melody features need music21 and are imported lazily; `tune_groups`, `is_test_half` and the JSON helpers are pure.
"""
from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path
from typing import Mapping, Sequence

DIVISI_SUFFIX = "__divisi"   # build_corpus.DIVISI_SUFFIX; the crc32 hashes the suffixed group key as the old rule did
MELODY_INTERVALS = 12        # soprano intervals hashed; a shorter melody uses all of its intervals
HASH_HEX = 16


def melody_hash(intervals: Sequence[int]) -> str:
    """Transposition-invariant hash of the first MELODY_INTERVALS soprano intervals (semitones)."""
    text = ",".join(str(i) for i in intervals[:MELODY_INTERVALS])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:HASH_HEX]


def tune_groups(pieces: Sequence[str], intervals: Mapping[str, Sequence[int]],
                titles: Mapping[str, str | None] | None = None) -> dict[str, str]:
    """Group key (the smallest piece id of the group) for every piece.

    Args:
        pieces: all piece ids to group (train and val together, so a val tune that also occurs in train is visible).
        intervals: soprano melodic intervals per piece, semitones. A piece with no entry, or an empty melody, is its own
            group: an empty hash would otherwise join every melody-less piece.
        titles: optional hymn title per piece; pieces with the same non-None title are joined.

    Returns:
        piece -> group key.
    """
    parent = {p: p for p in pieces}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    first_with: dict[str, str] = {}
    for p in sorted(pieces):
        melody = intervals.get(p)
        keys = []
        if melody:
            keys.append("melody:" + melody_hash(melody))
        title = (titles or {}).get(p)
        if title:
            keys.append("title:" + title)
        for key in keys:
            if key in first_with:
                union(first_with[key], p)
            else:
                first_with[key] = p
    return {p: find(p) for p in pieces}


def is_test_half(piece: str, groups: Mapping[str, str]) -> bool:
    """True for the test half: odd crc32 of `<group key>__divisi`. Accepts the piece id with or without the suffix.

    Raises:
        KeyError: the piece is not in `groups`. There is no fallback to the piece id, which would silently reintroduce
            the piece-level split this module replaces.
    """
    base = piece.removesuffix(DIVISI_SUFFIX)
    if base not in groups:
        raise KeyError(f"{base} has no tune group (halves.json does not cover it)")
    return zlib.crc32((groups[base] + DIVISI_SUFFIX).encode("utf-8")) % 2 == 1


def bach_sources() -> dict[str, Path]:
    """piece id -> music21 corpus source file, with the id rule of build_corpus.main (`bach_<stem>`)."""
    import music21  # noqa: PLC0415 (heavy; the pure functions above stay importable without it)
    paths = sorted(music21.corpus.getComposer("bach"), key=str)
    return {f"bach_{Path(str(p)).stem}".replace(" ", "_"): Path(str(p)) for p in paths
            if Path(str(p)).suffix in (".mxl", ".xml", ".musicxml", ".krn")}


def source_features(sources: Mapping[str, Path], pieces: Sequence[str]
                    ) -> tuple[dict[str, list[int]], dict[str, str | None]]:
    """(soprano intervals, hymn title) of each piece from its source score, via training/phase1/melody_groups.py.

    Raises:
        KeyError: a piece has no source file (the caller must not guess a melody).
    """
    from music21.corpus import chorales  # noqa: PLC0415
    from melody_groups import hymn_title, soprano_intervals  # noqa: PLC0415 (same folder as this file)
    by_bwv = chorales.ChoraleList().byBWV
    intervals = {p: soprano_intervals(sources[p]) for p in pieces}
    titles = {p: hymn_title(p, by_bwv) for p in pieces}
    return intervals, titles


def halves_report(groups: Mapping[str, str], split_of: Mapping[str, str]) -> dict[str, object]:
    """The halves.json content: groups, the half of every val piece, and which test pieces share a tune with train.

    `test_group_has_train_piece` is the clean-subset switch of the eval: a test-half piece whose group contains a
    Phase 2 train piece shares its melody (or title) with training data.
    """
    members: dict[str, list[str]] = {}
    for piece, key in sorted(groups.items()):
        members.setdefault(key, []).append(piece)
    val = sorted(p for p, s in split_of.items() if s == "val" and p in groups)
    half_of = {p: ("test" if is_test_half(p, groups) else "tuning") for p in val}
    shares = {p: any(split_of.get(q) == "train" for q in members[groups[p]]) for p in val if half_of[p] == "test"}
    return {"rule": f"half = crc32(group key + {DIVISI_SUFFIX!r}) odd -> test; group = pieces sharing a hash of the "
                    f"first {MELODY_INTERVALS} soprano intervals or a hymn title; key = min piece id; no re-roll",
            "group_of": dict(sorted(groups.items())), "groups": members, "half_of": half_of,
            "test_group_has_train_piece": shares,
            "counts": {"groups": len(members), "multi_piece_groups": sum(len(m) > 1 for m in members.values()),
                       "val_test": sum(h == "test" for h in half_of.values()),
                       "val_tuning": sum(h == "tuning" for h in half_of.values()),
                       "test_pieces_sharing_train_tune": sum(shares.values())}}


def load_groups(path: Path) -> dict[str, str]:
    """Piece -> group key from a halves.json written by the build kernel."""
    return dict(json.loads(path.read_text(encoding="utf-8"))["group_of"])


def load_clean_test_pieces(path: Path) -> set[str]:
    """Test-half pieces whose tune group holds no train piece (the clean-subset diagnostic)."""
    shares = json.loads(path.read_text(encoding="utf-8"))["test_group_has_train_piece"]
    return {p for p, shared in shares.items() if not shared}
