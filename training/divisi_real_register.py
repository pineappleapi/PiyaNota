"""Register the real camera divisi test set (PIYA-106, plan 2026-10-19 Task 2; protocol in
docs/decisions/piya-106-divisi-real-test-set.md).

The set is TEST-only. Registration pins every photo by sha256 before any checkpoint is scored on it, so a page
cannot be retaken, swapped or dropped after a result is seen. A piece that is in the Phase 2 training manifest is
refused, because scoring a model on pieces it trained on says nothing about real-world divisi.

meta CSV columns: piece,publisher,page,gt_kinds  (one row per photo; gt_kinds `;`-separated, from GT_KINDS)

Usage: python training/divisi_real_register.py --photos <dir> --meta <csv> --manifest <phase2_manifest.jsonl>
       --out data/eval_divisi_real/registry.json [--freeze]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

GT_KINDS = ("same_stem", "split_same_rhythm", "split_two_rhythm")
DIVISI_SUFFIX = "__divisi"


def _norm(piece: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", piece.lower())


def load_training_pieces(manifest: Path) -> set[str]:
    """Piece ids in a Phase 2 manifest, with the `__divisi` copy folded onto its source piece."""
    pieces: set[str] = set()
    with manifest.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                pieces.add(str(json.loads(line)["piece"]).removesuffix(DIVISI_SUFFIX))
    return pieces


def register(photo_dir: Path, meta_csv: Path, training_pieces: set[str], registry_path: Path,
             freeze: bool = False) -> dict[str, object]:
    """Build the registry from `meta_csv`, write it to `registry_path` and return it.

    Raises:
        ValueError: a training piece, a missing or unknown gt_kind, a missing photo, or any difference from a
            registry at `registry_path` that is already frozen.
    """
    training = {_norm(p) for p in training_pieces}
    pieces: dict[str, dict[str, object]] = {}
    with meta_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            name = row["piece"].strip()
            if _norm(name) in training:
                raise ValueError(f"{name}: piece is in the training manifest")
            kinds = [k.strip() for k in row["gt_kinds"].split(";") if k.strip()]
            if not kinds or any(k not in GT_KINDS for k in kinds):
                raise ValueError(f"{name} {row['page']}: gt_kinds {row['gt_kinds']!r} must be from {GT_KINDS}")
            photo = photo_dir / row["page"]
            if not photo.is_file():
                raise ValueError(f"{name}: photo {row['page']} not found in {photo_dir}")
            entry = pieces.setdefault(name, {"piece": name, "publisher": row["publisher"].strip(), "pages": [],
                                             "gt_kinds": [], "sha256": {}})
            entry["pages"].append(row["page"])  # type: ignore[attr-defined]
            entry["sha256"][row["page"]] = hashlib.sha256(photo.read_bytes()).hexdigest()  # type: ignore[index]
            entry["gt_kinds"] = sorted(set(entry["gt_kinds"]) | set(kinds))  # type: ignore[arg-type]
    body = sorted(pieces.values(), key=lambda e: str(e["piece"]))
    if registry_path.is_file():
        old = json.loads(registry_path.read_text(encoding="utf-8"))
        if old["frozen"]:
            if old["pieces"] != body:
                raise ValueError(f"{registry_path} is frozen; the photos or metadata changed")
            return old
    registry: dict[str, object] = {"frozen": freeze, "pieces": body}
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=1), encoding="utf-8")
    return registry


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--photos", type=Path, required=True)
    ap.add_argument("--meta", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--freeze", action="store_true", help="only after the user signs off the GT")
    args = ap.parse_args()
    reg = register(args.photos, args.meta, load_training_pieces(args.manifest), args.out, args.freeze)
    pieces: list[dict[str, object]] = reg["pieces"]  # type: ignore[assignment]
    print(f"{len(pieces)} pieces, {sum(len(p['pages']) for p in pieces)} pages, frozen={reg['frozen']}")  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
