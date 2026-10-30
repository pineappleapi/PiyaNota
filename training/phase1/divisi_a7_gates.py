"""A7 divisi corpus gates (design section 5.4 as amended by A7.1, sections 14.5-14.6), before any GPU time.

    python training/phase1/divisi_a7_gates.py --build <dir> --out report.json [--render-summary <json> ...]

Reuses the A6 gate helpers (`divisi_a6_gates.py`) and swaps the targets that A7 changed: triad share .30 with dyads
renormalised over .70; template triads >= .30 of triads; 2+ ledger members >= .045 (A6 v2's realised exposure, ruling
2); ledger-site crossings <= .05 of chord columns; every dyad bucket's TRAIN count >= .95 of A6 build v2 (3.1, counted
from the per-piece plans, reference `a6v2_train_class_counts.json`). Layer counts (arm CL) and the x-order audit come
from divisi_summary.json and the render summaries. The test buckets are not gated here: A7 is tested on the real
10-piece test set (user 2026-10-30, design 14.3), so that gate is recorded as not run, never as a pass.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import divisi_a6_gates as a6  # noqa: E402

TRIAD_TARGET = 0.30
DYAD_SCALE = (1 - TRIAD_TARGET) / (1 - a6.INTERVAL_TARGETS["triad"])
INTERVAL_TARGETS: dict[str, float] = {k: (TRIAD_TARGET if k == "triad" else v * DYAD_SCALE)
                                      for k, v in a6.INTERVAL_TARGETS.items()}
TEMPLATE_MIN = 0.30                     # of triads (ruling 1)
LEDGER2_FLOOR = 0.045                   # of members (ruling 2)
LEDGER_CROSS_MAX = 0.05                 # of chord columns (ruling 2)
DYAD_KEEP = 0.95                        # of the A6 v2 train count, per dyad bucket (3.1)
A6V2_REFERENCE = Path(__file__).with_name("a6v2_train_class_counts.json")


def a7_summary_gates(s: Mapping[str, object]) -> list[dict[str, object]]:
    r: Mapping[str, object] = s["realised"]  # type: ignore[assignment]
    total = int(r["chords_total"])  # type: ignore[call-overload]
    cls: collections.Counter[str] = collections.Counter()
    for k, v in r["class"].items():  # type: ignore[attr-defined]
        cls[k.split(":")[1]] += v
    out = [a6.gate("chords_total", total, "> 0", total > 0)]
    for name, target in INTERVAL_TARGETS.items():
        n = sum(v for k, v in cls.items() if k == name or k.startswith(f"{name}_"))
        out.append(a6.share_gate(f"interval.{name}", n, total, target))
    for name, target in a6.DURATION_TARGETS.items():
        out.append(a6.share_gate(f"duration.{name}", r["duration"].get(name, 0), total, target))  # type: ignore[attr-defined]
    free, copied = int(r["free"]), int(r["copied"])  # type: ignore[call-overload]
    out.append(a6.share_gate("members.free", free, free + copied, a6.FREE_MEMBER_TARGET))
    stemmed = cls["2nd_up"] + cls["2nd_down"]
    down = cls["2nd_down"] / stemmed if stemmed else 0.0
    out.append(a6.gate("2nd_stems_down", round(down, 4), f">= {a6.STEMS_DOWN_MIN:.2f}", down >= a6.STEMS_DOWN_MIN))
    acc = int(r["accidental_cols"]) / total if total else 0.0  # type: ignore[call-overload]
    out.append(a6.gate("accidental_cols", round(acc, 4), f">= {a6.ACCIDENTAL_COL_MIN:.2f}", acc >= a6.ACCIDENTAL_COL_MIN))
    cross = int(r["crossing"]) / total if total else 0.0  # type: ignore[call-overload]
    out.append(a6.gate("crossing", round(cross, 4), f"<= {a6.CROSSING_MAX:.2f}", cross <= a6.CROSSING_MAX))
    lcross = int(r.get("ledger_crossing", 0)) / total if total else 0.0  # type: ignore[call-overload]
    out.append(a6.gate("ledger_crossing", round(lcross, 4), f"<= {LEDGER_CROSS_MAX:.2f}", lcross <= LEDGER_CROSS_MAX))
    out.append(a6.share_gate("chord_free_strips", int(r["chord_free_strips"]), int(r["strips"]),  # type: ignore[call-overload]
                             a6.CHORD_FREE_TARGET))
    dens = [x for x in s["density_per_strip"] if x > 0]  # type: ignore[attr-defined]
    lo, hi = (min(dens), max(dens)) if dens else (0.0, 0.0)
    out.append(a6.gate("density_range", [round(lo, 3), round(hi, 3)], f"within {list(a6.DENSITY_RANGE)}",
                       bool(dens) and a6.DENSITY_RANGE[0] - 1e-9 <= lo and hi <= a6.DENSITY_RANGE[1] + 1e-9))
    out.append(a6.gate("free_new_accidentals", r["free_new_accidentals"], "== 0",
                       int(r["free_new_accidentals"]) == 0))  # type: ignore[call-overload]
    triads = cls["triad"] + cls["triad_template"]
    tshare = cls["triad_template"] / triads if triads else 0.0
    out.append(a6.gate("template_share", round(tshare, 4), f">= {TEMPLATE_MIN:.2f} of triads", tshare >= TEMPLATE_MIN))
    out.append(a6.gate("template_placement", r.get("template_duration", {}), "report (design .70 long, <= .05 beamed)",
                       True, a6.INFO))
    members = sum(int(r.get(k, 0)) for k in ("free", "copied", "template", "ledger"))  # type: ignore[call-overload]
    l2 = int(r["ledger2_members"]) / members if members else 0.0  # type: ignore[call-overload]
    out.append(a6.gate("ledger2_members", round(l2, 4), f">= {LEDGER2_FLOOR:.3f} of members", l2 >= LEDGER2_FLOOR))
    if "layers" in r:
        out.append(a6.gate("layers", r["layers"], "report (arm CL)", True, a6.INFO))
    missing = s.get("pieces_missing_from_build") or []
    out.append(a6.gate("pieces_missing_from_build", len(missing), "== 0", not missing))  # type: ignore[arg-type]
    return out


def dyad_train_gates(build: Path) -> list[dict[str, object]]:
    """Every dyad bucket's train count against A6 build v2 (exposure kept, design 3.1)."""
    ref = json.loads(A6V2_REFERENCE.read_text(encoding="utf-8"))["class_counts"]
    got: collections.Counter[str] = collections.Counter()
    for f in (build / "corpus").glob("*.plan.json"):
        plan = json.loads(f.read_text(encoding="utf-8"))
        if plan.get("split") == "train":
            for k, v in plan["divisi"]["class"].items():
                got[k.split(":")[1]] += v
    return [a6.gate(f"dyad_train.{b}", f"{got[b]}/{n}", f">= {DYAD_KEEP:.2f} of A6 v2", got[b] >= DYAD_KEEP * n)
            for b, n in sorted(ref.items()) if not b.startswith("triad")]


def render_gates(paths: Sequence[Path]) -> list[dict[str, object]]:
    """Render pass counts and the two-layer x-order audit (ruling 3): no swap may lack an MEI onset."""
    if not paths:
        return [a6.gate("render_audit", "no --render-summary", "-", True, a6.NOT_RUN)]
    audit: collections.Counter[str] = collections.Counter()
    renders = passed = 0
    for p in paths:
        s = json.loads(p.read_text(encoding="utf-8"))
        renders += int(s["renders"])
        passed += int(s["passed"])
        audit.update(s.get("oov", {}).get("layer_order_audit", {}))
    return [a6.gate("renders_passed", f"{passed}/{renders}", "report", True, a6.INFO),
            a6.gate("layer_swaps_without_onset", audit["swaps_no_onset"], "== 0", audit["swaps_no_onset"] == 0),
            a6.gate("layer_order_audit", dict(audit), "report", True, a6.INFO)]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--render-summary", type=Path, nargs="*", default=[])
    ap.add_argument("--a5-manifest", type=Path, default=a6.A5_DEFAULT_MANIFEST)
    args = ap.parse_args(argv)
    summary, why = a6.load_summary(args.build)
    train_rep: dict[str, object] = {}
    if summary is None:
        gates = [a6.gate("divisi_summary", why, "present with realised + stems", False, a6.MISSING)]
    else:
        gates = a7_summary_gates(summary) + dyad_train_gates(args.build)
        m_gates, train_rep = a6.manifest_gates(args.build, summary)
        gates += m_gates
    gates += render_gates(args.render_summary)
    gates.append(a6.gate("test_buckets", "real 10-piece test set (design 14.3)", "scored outside the build", True,
                         a6.NOT_RUN))
    gates.append(a6.a5_gate(args.a5_manifest))
    failed = [str(g["name"]) for g in gates if g["status"] not in (a6.PASS, a6.WARN, a6.NOT_RUN, a6.INFO)]
    args.out.write_text(json.dumps({"ok": not failed, "gates": gates, "train_manifest": train_rep}, indent=1),
                        encoding="utf-8")
    print(a6.format_table(gates))
    print("GATES FAILED: " + ", ".join(failed) if failed else "ALL GATES PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
