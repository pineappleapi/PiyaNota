"""Golden harness for `infer_pitch`: proves a Stage 3 change leaves monophonic output byte-identical (PIYA-106).

Plan `docs/superpowers/plans/2026-10-16-stage3-divisi-pairing.md` Task 1. Inputs (synthetic/dev only, never
accuracy evidence; no piyanota_dataset photos, nothing under phase4_strips):
  (a) every CameraPrIMuS `.agnostic` label (voice Soprano);
  (b) the first 3000 Phase 2 manifest rows sorted by `path` (voice from the `_<Voice>.png` suffix);
  (c) Phase 2 seed-1 greedy decodes (with confidences) of the first 1000 distorted CPM images, decoded once on CPU,
      one strip at a time, and cached so every later dump replays the same tokens.
Variants per input: plain; with confidences (real for (c), 0.9 per token otherwise); with a HeaderOverride from the
ground-truth header, once with next_system_key None and once with key + 1 (if within +-7). Each record holds the
events (json, sort_keys), captured stdout and mid_changes_out (or the raised exception); the dump stores its sha256.

Usage:
  python training/phase2/stage3_golden.py dump --out <json>
  python training/phase2/stage3_golden.py diff <a.json> <b.json>     (exit 1 and the first 20 differing keys)
  python training/phase2/stage3_golden.py show <key>                 (print one record, for debugging a diff)
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import stage3_transcription as s3  # noqa: E402

CPM_DIR = Path("D:/PiyaNota/datasets/CameraPriMus/CameraPrIMuS - Copy/Corpus")
MANIFEST = Path("D:/PiyaNota/datasets/phase2_manifest/phase2_manifest.jsonl")
SEED1 = Path("D:/PiyaNota/music_symbol_detection/phase2_kaggle_models/seed1/phase2_seed1.pt")
CACHE_DIR = Path("C:/Users/paul_/.claude/jobs/3ab43d79/tmp/stage3_golden")
NOISY_CACHE = CACHE_DIR / "noisy_decodes_seed1.json"
N_MANIFEST = 3000
N_NOISY = 1000
GT_CONFIDENCE = 0.9
MAX_KEY = 7
VOICES = ("Soprano", "Alto", "Tenor", "Bass")


def _cpm_samples() -> list[Path]:
    return sorted(CPM_DIR.iterdir())


def _read_agnostic(sample: Path) -> list[str]:
    return (sample / f"{sample.name}.agnostic").read_text(encoding="utf-8").split()


def _noisy_decodes() -> dict[str, list[list[Any]]]:
    """Seed-1 (token, confidence) decodes of the first N_NOISY distorted CPM images, cached on first use."""
    if NOISY_CACHE.exists():
        return json.loads(NOISY_CACHE.read_text(encoding="utf-8"))
    import cv2
    import torch
    torch.set_num_threads(2)
    model, device = s3.load_model(str(SEED1), torch.device("cpu"))
    out: dict[str, list[list[Any]]] = {}
    for sample in _cpm_samples()[:N_NOISY]:
        img = cv2.imread(str(sample / f"{sample.name}_distorted.jpg"), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(f"distorted image missing for {sample.name}")
        scored = s3.transcribe_strip(img, model, device, return_confidence=True)
        out[sample.name] = [[t, float(c)] for t, c in scored]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    NOISY_CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def _gt_header(gt: list[str]) -> Optional[tuple[str, int]]:
    """(first clef token, signed count of the accidentals before the first metersign/note), or None if no clef."""
    clef = next((t for t in gt if t.startswith("clef.")), None)
    if clef is None:
        return None
    key = 0
    for t in gt:
        if t.startswith(("metersign", "note.")):
            break
        if t.startswith("accidental.sharp"):
            key += 1
        elif t.startswith("accidental.flat"):
            key -= 1
    return clef, key


def _inputs() -> Iterator[tuple[str, list[str], str, list[float], list[str]]]:
    """(id, tokens, voice, confidences, ground-truth tokens for the header) per input."""
    samples = _cpm_samples()
    for sample in samples:
        toks = _read_agnostic(sample)
        yield f"cpm/{sample.name}", toks, "Soprano", [GT_CONFIDENCE] * len(toks), toks
    rows = [json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda r: r["path"])
    for r in rows[:N_MANIFEST]:
        voice = r["path"].rsplit("_", 1)[1].removesuffix(".png")
        if voice not in VOICES:
            raise ValueError(f"no voice suffix in {r['path']}")
        toks = r["tokens"]
        yield f"p2/{r['path']}", toks, voice, [GT_CONFIDENCE] * len(toks), toks
    noisy = _noisy_decodes()
    for sample in samples[:N_NOISY]:
        scored = noisy[sample.name]
        yield (f"noisy/{sample.name}", [t for t, _ in scored], "Soprano", [c for _, c in scored],
               _read_agnostic(sample))


def _run(tokens: list[str], voice: str, **kw: Any) -> dict[str, Any]:
    mids: list[dict[str, Any]] = []
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            events = s3.infer_pitch(list(tokens), voice=voice, page_index=1, sys_idx=1, mid_changes_out=mids, **kw)
        result: Any = events
    except Exception as exc:  # recorded, not swallowed: a crash must also stay identical
        result = {"exception": repr(exc)}
    return {"events": result, "stdout": buf.getvalue(), "mid_changes_out": mids}


def records() -> Iterator[tuple[str, dict[str, Any]]]:
    for rid, toks, voice, confs, gt in _inputs():
        yield f"{rid}|plain", _run(toks, voice)
        yield f"{rid}|conf", _run(toks, voice, confidences=confs)
        header = _gt_header(gt)
        if header is None:
            continue
        clef, key = header
        if clef not in s3.CLEF_REFERENCE:
            continue
        ho = s3.HeaderOverride(clef, key, 0)
        yield f"{rid}|override", _run(toks, voice, confidences=confs, header_override=ho, next_system_key=None)
        if abs(key + 1) <= MAX_KEY:
            yield f"{rid}|override_next", _run(toks, voice, confidences=confs, header_override=ho,
                                               next_system_key=key + 1)


def _digest(rec: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True).encode("utf-8")).hexdigest()


def dump(out: Path) -> None:
    golden = {k: _digest(rec) for k, rec in records()}
    body = json.dumps(golden, sort_keys=True, indent=0).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    sets: dict[str, int] = {}
    for k in golden:
        sets[k.split("/", 1)[0]] = sets.get(k.split("/", 1)[0], 0) + 1
    print(f"keys {len(golden)} {sets} sha256 {hashlib.sha256(body).hexdigest()}")


def diff(a: Path, b: Path) -> int:
    ga = json.loads(a.read_text(encoding="utf-8"))
    gb = json.loads(b.read_text(encoding="utf-8"))
    bad = sorted(k for k in set(ga) | set(gb) if ga.get(k) != gb.get(k))
    if not bad:
        print(f"identical ({len(ga)} keys)")
        return 0
    print(f"{len(bad)} differing keys; first 20:")
    for k in bad[:20]:
        print(" ", k)
    return 1


def show(key: str) -> None:
    for k, rec in records():
        if k == key:
            print(json.dumps(rec, sort_keys=True, indent=1))
            return
    raise KeyError(key)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("diff")
    f.add_argument("a", type=Path)
    f.add_argument("b", type=Path)
    s = sub.add_parser("show")
    s.add_argument("key")
    args = ap.parse_args()
    if args.cmd == "dump":
        dump(args.out)
    elif args.cmd == "diff":
        sys.exit(diff(args.a, args.b))
    else:
        show(args.key)


if __name__ == "__main__":
    main()
