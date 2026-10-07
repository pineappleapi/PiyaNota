"""Byte digest of a cut_corpus run dir, shared by the local reference and the Kaggle kernel.

Every file under the run dir is hashed except run_info.json / run_chunks.jsonl (host-specific by design). Page
result JSONs are hashed without their timing/memory fields, which legitimately differ between machines.

Usage: python parity_digest.py <run_dir> <out.json>
"""
import hashlib
import json
import sys
from pathlib import Path

VOLATILE = {"seconds", "rss_mb", "peak_rss_mb"}
RUN_LEVEL = {"run_info.json", "run_chunks.jsonl"}


def digest(run: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(run.rglob("*")):
        if not f.is_file() or f.name in RUN_LEVEL:
            continue
        rel = f.relative_to(run).as_posix()
        if f.suffix == ".json" and rel.startswith("pages/"):
            d = {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if k not in VOLATILE}
            out[rel] = hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
        else:
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def compare(a: dict[str, str], b: dict[str, str]) -> dict[str, object]:
    only = sorted(a.keys() ^ b.keys())
    diff = sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
    return {"files_a": len(a), "files_b": len(b), "only_one_side": only, "differing": diff,
            "identical": not only and not diff}


if __name__ == "__main__":
    d = digest(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
    print(len(d), "files digested")
