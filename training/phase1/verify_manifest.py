"""Check a copy of the frozen Phase 1 corpus against its MANIFEST.sha256 (PIYA-106).

The corpus is the only training input for Phase 2, and the Kaggle output it came from is not durable, so every copy
must be byte-identical to the frozen one before it is trusted. Files are hashed in 1 MiB chunks to keep memory flat
on the 29k-file tree (the dev PC ran out of memory on bulk Kaggle downloads; see fetch_output.py).

Usage: python training/phase1/verify_manifest.py <corpus_dir> [--manifest <path>]
The manifest defaults to <corpus_dir>/MANIFEST.sha256; pass --manifest to check a copy against another copy's list.
Exit code 0 only if every listed file is present and matches.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

CHUNK_BYTES = 1 << 20
MANIFEST_NAME = "MANIFEST.sha256"
MAX_LISTED = 10


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK_BYTES), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus_dir", type=Path)
    ap.add_argument("--manifest", type=Path, default=None)
    args = ap.parse_args()
    root: Path = args.corpus_dir
    manifest: Path = args.manifest or root / MANIFEST_NAME

    ok, mismatched, missing = 0, [], []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(" *", 1)
        path = root / rel
        if not path.is_file():
            missing.append(rel)
        elif sha256_file(path) != digest:
            mismatched.append(rel)
        else:
            ok += 1
    print(f"ok {ok} / mismatched {len(mismatched)} / missing {len(missing)}  "
          f"(manifest sha256 {sha256_file(manifest)[:16]})")
    for label, rels in (("MISMATCH", mismatched), ("MISSING", missing)):
        for rel in rels[:MAX_LISTED]:
            print(f"  {label} {rel}")
    return 0 if not mismatched and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
