"""A7 offline eval: per-epoch tuning-half stop checks and epoch selection (design piya-106-divisi-a7-design.md 6, 14.8).

    python training/phase2/eval_divisi_a7.py --build <arm build>/build --halves <arm build>/halves.json \
        --metrics <run>/metrics.json --ckpt e1=<run>/epoch1.pt ... --ckpt e8=<run>/epoch8.pt --out a7_c_s1_tune.json

Scoring is eval_divisi_a6 (LCS column alignment, head buckets, A6 selection rule), on the tuning half with Gootville
excluded. Added here, from the same decode (`a7_extras`):
* triad_2plus: GT triad columns whose aligned predicted column has 2+ chordnotes; an unaligned column counts as 0.
  Stop check >= .85 (point estimate; Wilson LB reported).
* dyad_2plus: GT dyad columns emitting 2+ chordnotes (anti-gaming guard <= .02).
* middle / top: triad member recall by height (inner heads / highest head).
* tie_token: GT columns followed by a tie (`slur.start`) whose aligned column is also followed by one.
* layer_split (arm CL): bars paired by index when GT and prediction have the same bar count; a strip with a different
  count scores its GT layer bars as misses and its predicted ones as false firings. Stop check P and R >= .85.
  shortcut: index pairing undercounts when a barline is misread; upgrade to LCS bar alignment if misaligned strips
  are common (reported as `bars_misaligned_strips`).
Canary status comes from the run's metrics.json (`status` == "OK" per epoch). The test half and the real 10-piece
set are not scored here (the PREREG freezes first, design 14.7).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_divisi_a6 as a6  # noqa: E402

STOP_TRIAD_2PLUS = 0.85
STOP_DYAD_2PLUS_MAX = 0.02
STOP_LAYER = 0.85
UNDERTRAINED_RISE = 0.03          # per epoch over epochs 6-8 (ml-cv-lead): a miss is then read as undertrained
TIE = "slur.start"
LAYER = "layer.split"
BARLINE = "barline"
EPOCH_LABEL = re.compile(r"\D*(\d+)$")


def _following(tokens: Sequence[str], cols: Sequence[tuple[int, str, list[str], set[int]]], k: int) -> Sequence[str]:
    end = cols[k + 1][0] if k + 1 < len(cols) else len(tokens)
    return tokens[cols[k][0] + 1:end]


def _bars(tokens: Sequence[str]) -> list[bool]:
    """One flag per bar: does it carry `layer.split`."""
    out, cur = [], False
    for t in tokens:
        if t.startswith(BARLINE):
            out.append(cur)
            cur = False
        elif t == LAYER:
            cur = True
    return out + [cur]


def a7_extras(pred: Sequence[str], gt: Sequence[str]) -> dict[str, Any]:
    gcols, pcols = a6.columns(gt), a6.columns(pred)
    aligned = dict(a6.lcs_pairs([a6.shape(c[1]) for c in gcols], [a6.shape(c[1]) for c in pcols]))
    out: dict[str, Any] = {k: [0, 0] for k in ("triad_2plus", "dyad_2plus", "middle", "top", "tie_token")}
    for gi, (_i, note, ext, _acc) in enumerate(gcols):
        pi = aligned.get(gi)
        if ext:
            n_pred = len(pcols[pi][2]) if pi is not None else 0
            key = "triad_2plus" if len(ext) >= 2 else "dyad_2plus"
            out[key][0] += int(n_pred >= 2)
            out[key][1] += 1
        if len(ext) >= 2:
            heads = sorted({a6.step_of(note)} | {a6.step_of(t) for t in ext})
            ps = set() if pi is None else {a6.step_of(pcols[pi][1])} | {a6.step_of(t) for t in pcols[pi][2]}
            for name, members in (("middle", heads[1:-1]), ("top", heads[-1:])):
                out[name][0] += sum(s in ps for s in members)
                out[name][1] += len(members)
        if any(t.startswith(TIE) for t in _following(gt, gcols, gi)):
            out["tie_token"][1] += 1
            out["tie_token"][0] += int(pi is not None and any(t.startswith(TIE) for t in _following(pred, pcols, pi)))
    gb, pb = _bars(gt), _bars(pred)
    if len(gb) == len(pb):
        tp = sum(g and p for g, p in zip(gb, pb))
        out["layer_tp"], out["layer_fp_single"] = tp, sum(p and not g for g, p in zip(gb, pb))
        out["bars_misaligned_strips"] = 0
    else:
        out["layer_tp"], out["layer_fp_single"], out["bars_misaligned_strips"] = 0, sum(pb), int(any(gb) or any(pb))
    out["layer_gt"], out["layer_pred"], out["single_bars"] = sum(gb), sum(pb), sum(not g for g in gb)
    return out


def ratio(pair: Sequence[int]) -> float | None:
    return pair[0] / pair[1] if pair[1] else None


def stop_checks(t: dict[str, Any], arm: str) -> dict[str, Any]:
    tri, dy = t["triad_2plus"], t["dyad_2plus"]
    out: dict[str, Any] = {
        "triad_2plus": ratio(tri), "triad_2plus_wilson_lb": a6.wilson_lb(*tri) if tri[1] else None, "triad_n": tri[1],
        "dyad_2plus": ratio(dy), "dyad_n": dy[1], "middle_recall": ratio(t["middle"]), "top_recall": ratio(t["top"]),
        "ledger_recall": ratio(t["bucket"].get("ledger", [0, 0])), "tie_token_recall": ratio(t["tie_token"]),
        "tie_token_n": t["tie_token"][1]}
    out["chords_pass"] = bool(tri[1] and out["triad_2plus"] >= STOP_TRIAD_2PLUS
                              and (out["dyad_2plus"] or 0.0) <= STOP_DYAD_2PLUS_MAX)
    if arm == "CL":
        p = t["layer_tp"] / t["layer_pred"] if t["layer_pred"] else None
        r = t["layer_tp"] / t["layer_gt"] if t["layer_gt"] else None
        out.update(layer_precision=p, layer_recall=r, layer_gt_bars=t["layer_gt"],
                   layer_false_on_single=t["layer_fp_single"] / t["single_bars"] if t["single_bars"] else None,
                   bars_misaligned_strips=t["bars_misaligned_strips"],
                   layers_pass=p is not None and r is not None and p >= STOP_LAYER and r >= STOP_LAYER)
    return out


def load_a7_model(path: str) -> Any:
    import torch  # noqa: PLC0415
    import stage3_transcription as s3  # noqa: PLC0415
    model, _ = s3.load_model(path, torch.device("cpu"))
    if model.fc.weight.shape[0] != len(s3.VOCAB_EXT_A7):
        raise ValueError(f"{path}: head size {model.fc.weight.shape[0]} != A7 vocabulary {len(s3.VOCAB_EXT_A7)}")
    return model.eval()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", type=Path, required=True, help="the arm's build/ folder (manifest/, out/, summary)")
    ap.add_argument("--halves", type=Path, required=True)
    ap.add_argument("--metrics", type=Path, required=True, help="the run's metrics.json (canary status per epoch)")
    ap.add_argument("--ckpt", action="append", required=True, help="eN=checkpoint.pt, one per epoch")
    ap.add_argument("--limit", type=int, default=0, help="fixed-seed subsample of strips (0 = all; smoke only)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    has_layers = any(LAYER in json.loads(x)["tokens"] for x in
                     (a.build / "manifest" / "phase2_manifest.jsonl").read_text(encoding="utf-8").splitlines() if x)
    arm = "CL" if has_layers else "C"
    canary = {int(e["epoch"]): e["status"] == "OK" for e in json.loads(a.metrics.read_text(encoding="utf-8"))}
    rows, _ = a6.load_builds([a.build], "val", "tuning", False, a.limit, 0, a6.divisi_halves.load_groups(a.halves),
                             [a6.HELD_OUT_FONT])
    print(f"arm {arm}: {len(rows)} tuning-half strips (Gootville excluded)")
    per_epoch: list[dict[str, Any]] = []
    for item in a.ckpt:
        label, path = item.split("=", 1)
        epoch = int(EPOCH_LABEL.fullmatch(label).group(1))  # type: ignore[union-attr]
        ev = a6.evaluate(load_a7_model(path), a.build, rows, None, a7_extras)
        t = ev["total"]
        rec, prec = a6.head_pr(t)
        min_rec, thin = a6.min_bucket_recall(t["bucket"], drop_second=False)
        e = {"label": label, "epoch": epoch, "P": prec, "head_recall": rec, "canary_ok": canary.get(epoch, False),
             "min_recall": min_rec, "underpowered_buckets": thin, "buckets": t["bucket"], **stop_checks(t, arm)}
        per_epoch.append(e)
        print(f"{label}: P {prec:.4f} R {rec:.4f} min {min_rec} triad2+ {e['triad_2plus']} dyad2+ {e['dyad_2plus']} "
              + (f"layer P/R {e['layer_precision']}/{e['layer_recall']}" if arm == "CL" else ""), flush=True)
    per_epoch.sort(key=lambda e: e["epoch"])
    try:
        sel: dict[str, Any] = per_epoch[a6.select_epoch(per_epoch) - 1]
    except ValueError as exc:
        sel = {"label": None, "error": str(exc)}
    tail = [e["triad_2plus"] for e in per_epoch if e["epoch"] >= 6 and e["triad_2plus"] is not None]
    rises = [b - x for x, b in zip(tail, tail[1:])]
    result = {"arm": arm, "n_strips": len(rows), "per_epoch": per_epoch, "selected": sel.get("label"),
              "selection_error": sel.get("error"),
              "stop_check": {k: sel.get(k) for k in ("chords_pass", "layers_pass", "triad_2plus", "dyad_2plus",
                                                      "layer_precision", "layer_recall") if k in sel},
              "undertrained_reading": bool(rises) and all(r > UNDERTRAINED_RISE for r in rises)}
    a.out.write_text(json.dumps(a6._jsonable(result), indent=1), encoding="utf-8")
    print(f"selected {result['selected']}; stop check {result['stop_check']}; undertrained {result['undertrained_reading']}")
    passed = sel.get("chords_pass") and (arm == "C" or sel.get("layers_pass"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
