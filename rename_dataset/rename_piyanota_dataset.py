"""Rename the PiyaNota evaluation photos to ``<piece>_pg<NN>[_<variant>].jpg``.

Dry-run by default; pass ``--apply`` to rename. Also writes
``dataset_manifest.csv`` next to the images so the original ``IMG_xxxx`` name
stays recoverable and per-piece split / ground-truth columns exist for
evaluation.

Usage:
    python rename_dataset/rename_piyanota_dataset.py                # preview only
    python rename_dataset/rename_piyanota_dataset.py --apply        # rename + write manifest
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

DEFAULT_DATASET_DIR = Path("data/piyanota_dataset")
DEFAULT_MAP_PATH = Path("rename_dataset/piyanota_dataset_rename_map.csv")
MANIFEST_NAME = "dataset_manifest.csv"
SOURCE_SUFFIXES = (".JPG", ".jpg", ".jpeg", ".JPEG")
TARGET_SUFFIX = ".jpg"
PAGE_DIGITS = 2  # zero-pad so lexical sort matches page order (pg10 after pg02)
MANIFEST_FIELDS = [
    "filename",
    "original_name",
    "piece",
    "page",
    "variant",
    "split",
    "capture_notes",
    "ground_truth",
]


def find_source(dataset_dir: Path, stem: str) -> Path:
    """Locates the on-disk file for a stem, tolerating extension case.

    Args:
        dataset_dir: Folder containing the photos.
        stem: File name without extension.

    Returns:
        The existing file path.

    Raises:
        FileNotFoundError: If no file with a known image suffix exists.
    """
    for suffix in SOURCE_SUFFIXES:
        candidate = dataset_dir / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No image found for stem '{stem}' in {dataset_dir}")


def build_plan(dataset_dir: Path, map_path: Path) -> list[tuple[Path, Path, dict[str, str]]]:
    """Reads the map CSV and resolves every rename before touching disk.

    Args:
        dataset_dir: Folder containing the photos.
        map_path: CSV with columns original_stem, piece, page, variant.

    Returns:
        List of (source path, target path, manifest row).

    Raises:
        FileNotFoundError: If a mapped source file is missing.
        ValueError: If two sources map to the same target, or a target already
            exists and is not itself one of the sources being renamed.
    """
    plan: list[tuple[Path, Path, dict[str, str]]] = []
    with map_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            source = find_source(dataset_dir, row["original_stem"])
            variant = f"_{row['variant']}" if row["variant"] else ""
            page = int(row["page"])
            target_name = f"{row['piece']}_pg{page:0{PAGE_DIGITS}d}{variant}{TARGET_SUFFIX}"
            plan.append((
                source,
                dataset_dir / target_name,
                {
                    "filename": target_name,
                    "original_name": source.name,
                    "piece": row["piece"],
                    "page": str(page),
                    "variant": row["variant"],
                    "split": "",
                    "capture_notes": "",
                    "ground_truth": "",
                },
            ))

    targets = [target for _, target, _ in plan]
    if len(set(targets)) != len(targets):
        duplicates = sorted({t.name for t in targets if targets.count(t) > 1})
        raise ValueError(f"Duplicate target names in map: {duplicates}")

    sources = {source for source, _, _ in plan}
    clobbers = [t.name for t in targets if t.exists() and t not in sources]
    if clobbers:
        raise ValueError(f"Targets already exist and are not being renamed: {clobbers}")

    unmapped = sorted(
        p.name for p in dataset_dir.iterdir()
        if p.suffix in SOURCE_SUFFIXES and p not in sources
    )
    if unmapped:
        raise ValueError(f"Images in folder with no map entry: {unmapped}")
    return plan


def apply_plan(plan: list[tuple[Path, Path, dict[str, str]]], dataset_dir: Path) -> None:
    """Renames files via temporary names, then writes the manifest.

    Two-phase because a target can equal another entry's source on a
    case-insensitive filesystem (Windows), which would overwrite silently.
    """
    staged: list[tuple[Path, Path]] = []
    for index, (source, target, _) in enumerate(plan):
        temp = dataset_dir / f".renaming_{index:04d}.tmp"
        source.rename(temp)
        staged.append((temp, target))
    for temp, target in staged:
        temp.rename(target)

    manifest_path = dataset_dir / MANIFEST_NAME
    rows = sorted((row for _, _, row in plan), key=lambda r: r["filename"])
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP_PATH)
    parser.add_argument("--apply", action="store_true", help="Actually rename (default: dry run)")
    args = parser.parse_args()

    plan = build_plan(args.dataset, args.map)
    for source, target, _ in plan:
        print(f"{source.name:36s} -> {target.name}")
    pieces = {row["piece"] for _, _, row in plan}
    print(f"\n{len(plan)} files, {len(pieces)} pieces")

    if not args.apply:
        print("Dry run only. Re-run with --apply to rename and write the manifest.")
        return 0
    apply_plan(plan, args.dataset)
    print(f"Renamed. Manifest written to {args.dataset / MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
