"""Secondary G2 figure: eval_dev.py with fermata tokens dropped from predictions before scoring (SER only).
Wraps se.score_strip; eval_dev.py is imported unchanged. Without --drop-fermata it is a no-op (parity check).

A6 additions (PIYA-106, docs/decisions/piya-106-divisi-a6-design.md section 6, dev pitch recall):
  --strip-chordnotes  removes `chordnote-*` tokens before pitch inference and token scoring, so dev pitch recall
                      measures only whether plain reading got worse (dev pieces have no divisi chords).
  McNemar             when a --weights label is exactly `v1` (the Phase 2 checkpoint) and others are given, a paired
                      note-level exact McNemar of pitch correctness (the SOW pitch alignment) of each other label vs
                      v1 is printed per pool and written to <out>/mcnemar_<strips>_<header>.json."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
drop = "--drop-fermata" in sys.argv
strip_chord = "--strip-chordnotes" in sys.argv
sys.argv = [x for x in sys.argv if x not in ("--drop-fermata", "--strip-chordnotes")]
REFERENCE_LABEL = "v1"
CHORDNOTE_PREFIX = "chordnote-"

import eval_dev as ed  # noqa: E402


def strip_chordnotes(tokens: Sequence[str],
                     confidences: Optional[Sequence[float]] = None) -> tuple[list[str], Optional[list[float]]]:
    """Tokens (and the parallel confidences) without `chordnote-*`.

    Why: an A6 model may add chordnotes; infer_pitch turns each into an extra note event, which would change the
    note alignment of a plain-reading comparison against v1.
    """
    keep = [i for i, t in enumerate(tokens) if not str(t).startswith(CHORDNOTE_PREFIX)]
    return ([tokens[i] for i in keep],
            None if confidences is None else [confidences[i] for i in keep])


def note_pitch_flags(g: dict[str, Any], ev: Optional[list[dict]]) -> list[bool]:
    """Per GT note, in order: did the SOW pitch alignment match it (the same alignment score_strip counts)."""
    se = ed.se
    he = [e for e in (ev or []) if e.get("type") in ("note", "rest")]
    rev = [("W", se.EVENT_OOV_SPAN) if e["kind"] == "oov" else e for e in g["events"]]
    _, ops = se.align(rev, he, lambda a, b: se.ekey(a, "pitch") == se.ekey(b, "pitch"))
    return [k == "M" for k, ri, _hj in ops if k != "W" and ri is not None and rev[ri]["kind"] == "note"]


def mcnemar_exact(ref: Sequence[bool], other: Sequence[bool]) -> dict[str, Any]:
    """Exact two-sided McNemar on paired booleans: b = ref right/other wrong, c = ref wrong/other right."""
    if len(ref) != len(other):
        raise ValueError(f"paired lists differ in length: {len(ref)} vs {len(other)}")
    b = sum(r and not o for r, o in zip(ref, other))
    c = sum(o and not r for r, o in zip(ref, other))
    n = b + c
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)
    return {"n_notes": len(ref), "ref_only": b, "other_only": c, "p": p}


_orig = ed.se.score_strip
_labels = [w.split("=", 1)[0] for i, w in enumerate(sys.argv) if i and sys.argv[i - 1] == "--weights"]
_state: dict[str, Any] = {"model_idx": -1, "label": None, "cond": None, "piece": None}
_flags: dict[tuple[str, str, str, str], list[bool]] = {}


def _score(g, sub, *rest):
    if drop and sub is not None:
        sub = [x for x in sub if not str(x).startswith("fermata")]
    if strip_chord and sub is not None:
        sub, _ = strip_chordnotes(sub)
    ev = rest[0] if rest else None
    _flags[(_state["label"], _state["cond"], _state["piece"], g["strip_id"])] = note_pitch_flags(g, ev)
    return _orig(g, sub, *rest)


_orig_infer = ed.s3.infer_pitch


def _infer(tokens, *args, **kw):
    if strip_chord:
        tokens, conf = strip_chordnotes(tokens, kw.get("confidences"))
        if conf is not None:
            kw["confidences"] = conf
    return _orig_infer(tokens, *args, **kw)


_orig_load = ed.s3.load_model
_orig_piece_rows = ed.piece_rows


def _load(*a, **kw):
    _state["model_idx"] += 1
    _state["label"] = _labels[_state["model_idx"]]
    return _orig_load(*a, **kw)


def _piece_rows(model, cond, piece, *a, **kw):
    _state["cond"], _state["piece"] = cond, piece
    return _orig_piece_rows(model, cond, piece, *a, **kw)


def report_mcnemar() -> None:
    """Prints and writes the v1 comparison for every other label, per pool (camera / digital)."""
    if REFERENCE_LABEL not in _labels or len(_labels) < 2:
        return
    out: dict[str, Any] = {}
    for label in _labels:
        if label == REFERENCE_LABEL:
            continue
        for cond in ed.POOLS:
            keys = [k for k in _flags if k[0] == REFERENCE_LABEL and k[1] == cond]
            ref = [f for k in keys for f in _flags[k]]
            oth = [f for k in keys for f in _flags[(label, *k[1:])]]
            res = mcnemar_exact(ref, oth)
            out[f"{label}|{cond}"] = res
            print(f"  McNemar {label} vs {REFERENCE_LABEL} [{cond}]: notes {res['n_notes']}, "
                  f"v1-only right {res['ref_only']}, {label}-only right {res['other_only']}, p={res['p']:.4f}")
    argv = sys.argv
    out_dir = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("D:/PiyaNota/datasets/phase2_eval_dev")
    strips = argv[argv.index("--strips") + 1] if "--strips" in argv else "grey"
    header = argv[argv.index("--header") + 1] if "--header" in argv else "e1c"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"mcnemar_{strips}_{header}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


ed.se.score_strip = _score
ed.s3.infer_pitch = _infer
ed.s3.load_model = _load
ed.piece_rows = _piece_rows

if __name__ == "__main__":
    code = ed.main()
    report_mcnemar()
    sys.exit(code)
