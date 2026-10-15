"""Phase 2 strip manifest: one row per cut Phase 1 strip, with a piece-level train/val split (PIYA-106).

Why piece-level: the 5 fonts of a piece share every label, so a strip-level or page-level split would put the same
music on both sides and the val SER would measure recall of seen labels, not reading (ml-cv-lead condition 1,
2026-10-08). The split is a pure function of the piece id (sha256), so it needs no stored state and the Kaggle kernel
reproduces it bit-for-bit from the attached re-cut output; it then asserts the manifest sha256 printed here.

Stratum edges (line_mult, interline tertiles) come from the train rows only and are used to report val SER per
stratum (ml-cv-lead condition 3: report, do not reweight).

Usage: python training/phase2/build_manifest.py <recut_out_dir> <dest_dir>
  <recut_out_dir> is the folder holding pages/ and strips/ (e.g. D:/PiyaNota/datasets/phase1_recut_full/out).
Writes <dest_dir>/phase2_manifest.jsonl and <dest_dir>/phase2_manifest_summary.json.
"""
from __future__ import annotations

import ast
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

VAL_FRACTION = 0.10
HASH_SPAN = 16 ** 8                     # first 8 hex digits of sha256(piece) as a uniform draw in [0, 1)
POSITION_SUFFIX = re.compile(r"-[LS]-?\d+$")
# Classes ml-cv-lead asked to track at G2 (final-system loss and OOV gaps, 2026-10-08). The vocabulary has no
# separate final-barline token, so "final_barline" is the last barline of a strip on the piece's final system.
WATCH_CLASSES = ("note.whole", "rest.half", "fermata.above")
FORBIDDEN_CLASS = "accidental.double_sharp"   # quarantined as OOV in Phase 1; must not reach training
STRATUM_KEYS = ("line_mult", "interline_px")
TERTILES = (1 / 3, 2 / 3)
# Piece -> tune group (tune_groups.py). The split hashes the group, so harmonisations of one melody stay on one side
# (ml-cv-lead P5 blocker 1, 2026-10-11).
TUNE_GROUPS = Path(__file__).with_name("tune_groups.json")
DIVISI_SUFFIX = "__divisi"              # training/phase1/build_corpus.py DIVISI_SUFFIX


def token_class(tok: str) -> str:
    return POSITION_SUFFIX.sub("", tok)


def is_val_group(group: str) -> bool:
    return int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16) / HASH_SPAN < VAL_FRACTION


def load_tune_groups() -> dict[str, str]:
    return json.loads(TUNE_GROUPS.read_text(encoding="utf-8"))


def quantiles(values: list[float], qs: tuple[float, ...]) -> list[float]:
    """Linear-interpolated quantiles without numpy, so the Kaggle and local results match exactly."""
    v = sorted(values)
    out = []
    for q in qs:
        pos = q * (len(v) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(v) - 1)
        out.append(v[lo] + (v[hi] - v[lo]) * (pos - lo))
    return out


def stratum(value: float | None, edges: list[float]) -> int | None:
    if value is None:
        return None
    return sum(value > e for e in edges)


def build(out_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    last_system: dict[tuple[str, str], int] = collections.defaultdict(lambda: -1)
    groups = load_tune_groups()
    for pj in sorted((out_dir / "pages").rglob("*.json")):
        font, piece = pj.parent.parent.name, pj.parent.name
        group_key = piece.removesuffix(DIVISI_SUFFIX)   # a divisi copy inherits its source piece's tune group
        if group_key not in groups:
            raise SystemExit(f"{piece} has no tune group: rerun training/phase2/tune_groups.py")
        page = json.loads(pj.read_text(encoding="utf-8"))
        params = page.get("params") if isinstance(page.get("params"), dict) else {}
        for s in page.get("strips") or []:
            last_system[(font, piece)] = max(last_system[(font, piece)], int(s["system"]))
            if s.get("status") != "cut":
                continue
            toks = s["tokens"]
            rows.append({
                "path": s["path"], "tokens": ast.literal_eval(toks) if isinstance(toks, str) else list(toks),
                "font": font, "piece": piece, "page": int(s["page"]), "system": int(s["system"]),
                "voice": s["voice"], "off_paper_left": s.get("off_paper_left_frac"),
                "off_paper_right": s.get("off_paper_right_frac"),
                "line_mult": params.get("line_mult"), "interline_px": params.get("interline_px"),
                "tune": groups[group_key], "split": "val" if is_val_group(groups[group_key]) else "train",
            })
    for r in rows:
        r["final_system"] = r["system"] == last_system[(str(r["font"]), str(r["piece"]))]
    edges = {k: quantiles([float(r[k]) for r in rows if r["split"] == "train" and r[k] is not None], TERTILES)
             for k in STRATUM_KEYS}
    for r in rows:
        for k in STRATUM_KEYS:
            r[f"{k}_tertile"] = stratum(r[k], edges[k])  # type: ignore[arg-type]
    rows.sort(key=lambda r: str(r["path"]))
    return rows, {"edges": edges}


def summarise(rows: list[dict[str, object]], edges: dict[str, object]) -> dict[str, object]:
    by_split: dict[str, dict[str, object]] = {}
    for split in ("train", "val"):
        sub = [r for r in rows if r["split"] == split]
        classes: collections.Counter[str] = collections.Counter()
        final_bar = 0
        for r in sub:
            toks = [token_class(t) for t in r["tokens"]]  # type: ignore[union-attr]
            classes.update(t for t in toks if t in WATCH_CLASSES or t == FORBIDDEN_CLASS)
            final_bar += int(bool(r["final_system"]) and "barline" in toks)
        by_split[split] = {
            "strips": len(sub), "pieces": len({r["piece"] for r in sub}), "tunes": len({r["tune"] for r in sub}),
            "fonts": dict(collections.Counter(str(r["font"]) for r in sub)),
            "line_mult_tertile": dict(collections.Counter(str(r["line_mult_tertile"]) for r in sub)),
            "interline_tertile": dict(collections.Counter(str(r["interline_px_tertile"]) for r in sub)),
            "watch_classes": {**{c: classes[c] for c in WATCH_CLASSES}, "final_barline": final_bar},
            FORBIDDEN_CLASS: classes[FORBIDDEN_CLASS],
        }
    shared = {r["piece"] for r in rows if r["split"] == "train"} & {r["piece"] for r in rows if r["split"] == "val"}
    shared_tunes = {r["tune"] for r in rows if r["split"] == "train"} & {r["tune"] for r in rows if r["split"] == "val"}
    return {"rows": len(rows), "pieces_in_both_splits": len(shared), "tunes_in_both_splits": len(shared_tunes),
            "edges": edges, "splits": by_split}


def main() -> int:
    out_dir, dest = Path(sys.argv[1]), Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)
    rows, meta = build(out_dir)
    body = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")
    (dest / "phase2_manifest.jsonl").write_bytes(body)
    summary = summarise(rows, meta["edges"])  # type: ignore[arg-type]
    summary["manifest_sha256"] = hashlib.sha256(body).hexdigest()
    (dest / "phase2_manifest_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    bad = summary["pieces_in_both_splits"] or summary["tunes_in_both_splits"] or any(s[FORBIDDEN_CLASS] for s in summary["splits"].values())  # type: ignore[union-attr]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
