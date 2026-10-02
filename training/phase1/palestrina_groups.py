"""Source groups for the Palestrina renders, so the validation split keeps every mass on one side (PIYA-106).

Why (plan Step 6 amendment 3, coordinator 2026-10-01): pieces that share a mass/motet source must not straddle
train and validation, because movements of one mass share its cantus firmus / model motet and its idiom. The
music21 Palestrina corpus names each file `<Movement>_<NN>[_<section>].krn`, where NN is the number of the mass the
movement comes from (Kyrie_06_c, Gloria_06_a, Sanctus_06_b and Benedictus_06 are one mass). So the group key is that
number; a file without one (e.g. Kyrie_b) is its own group, because nothing ties it to a mass.

Output has the same `piece_group` shape as `melody_groups.py`, so `cut_corpus.py manifest --groups` takes either.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

DEFAULT_RENDERS = Path("D:/PiyaNota-training/data/phase1_renders/renders")
PREFIX = "palestrina_"
MASS_NUMBER_RE = re.compile(r"_(\d{2})(?:_|$)")


def group_of(piece: str) -> str:
    m = MASS_NUMBER_RE.search(piece[len(PREFIX):] if piece.startswith(PREFIX) else piece)
    return f"palestrina_mass_{m.group(1)}" if m else piece


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--renders", type=Path, default=DEFAULT_RENDERS)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    pieces = sorted({d.name for d in a.renders.glob(f"*/{PREFIX}*") if d.is_dir()})
    piece_group = {p: group_of(p) for p in pieces}
    sizes = Counter(Counter(piece_group.values()).values())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"rule": "mass number from the music21 file name", "piece_group": piece_group,
                                 "group_size_hist": dict(sorted(sizes.items()))}, indent=1), encoding="utf-8")
    print(f"{len(pieces)} pieces -> {len(set(piece_group.values()))} groups; sizes {dict(sorted(sizes.items()))}")


if __name__ == "__main__":
    main()
