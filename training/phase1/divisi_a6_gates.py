"""A6 divisi corpus gates: checks a built divisi corpus against the frozen data mix before any GPU time.

    python training/phase1/divisi_a6_gates.py --build <dir> [--test <dir> ...] --out report.json

`<dir>` is a build_corpus.py `--divisi` output folder (divisi_summary.json) that has been rendered and cut
(manifest/phase2_manifest.jsonl). Exits 1 if any gate fails; every gate's value and target are written to the JSON
and printed as a table (docs/decisions/piya-106-divisi-a6-design.md sections 4 and 5).

Why two sources: mix shares (interval, duration, free/copied, accidental, density, audit counters) are counted by the
generator and only exist in divisi_summary.json; head buckets, the held-out font and member steps need the cut
strips' tokens (manifest). Stem direction is in neither the tokens nor the manifest, so 2nd_up / 2nd_down come from
the summary's per-strip `stems` list, which has one entry per chord column left to right (STEMLESS for whole notes).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SHARE_TOL = 0.03                          # +-3 pp on every section 4 share
CHORD_FREE_TARGET = 0.25
DENSITY_RANGE = (0.20, 0.60)
MEMBER_STEPS = (-5, 13)                   # inclusive, L1 = 0
STEMS_DOWN_MIN = 0.30                     # of stemmed 2nds
FREE_MEMBER_TARGET = 0.60
ACCIDENTAL_COL_MIN = 0.12
CROSSING_MAX = 0.10
LEDGER_LOW, LEDGER_HIGH = -2, 10          # a member at or beyond these steps is on a ledger line
TEST_MIN_IN_FONT = 600
TEST_MIN_HELD_OUT = 300
HELD_OUT_FONT = "Gootville"
UNDERPOWERED_OK = frozenset({"7th"})      # warn, never fail, when short (design section 4)
STEMLESS = "none"                         # build_corpus.STEMLESS
STEM_MISMATCH_MAX = 0.01                  # share of chord strips whose stems list may not line up with the tokens
A5_SHA256 = "78165b43251f67751afc91500e812a3ce7fa06d8980a275ddadd7014d8782824"
A5_DEFAULT_MANIFEST = Path("D:/PiyaNota/datasets/phase2_manifest/phase2_manifest.jsonl")
# Shares of chord columns (dyad weights already include the 0.85 renormalisation, so they sum with triad to 1).
INTERVAL_TARGETS: dict[str, float] = {"2nd": .12, "3rd": .16, "4th": .12, "5th": .12, "6th": .12, "7th": .05,
                                      "8ve": .16, "triad": .15}
DURATION_TARGETS: dict[str, float] = {"whole": .12, "half": .20, "dotted": .15, "quarter": .33, "beamed": .20}
INTERVAL_BY_STEPS: dict[int, str] = {1: "2nd", 2: "3rd", 3: "4th", 4: "5th", 5: "6th", 6: "7th", 7: "8ve"}
TEST_BUCKETS = ("2nd_up", "2nd_down", "3rd", "4th", "5th", "6th", "7th", "8ve", "triad", "ledger")
POSITION = re.compile(r"-([LS])(-?\d+)$")
PASS, FAIL, WARN, MISSING, NOT_RUN = "pass", "fail", "warn", "missing", "not_run"


def step_of(tok: str) -> int:
    """Staff step of a note/chordnote token suffix: L1 = 0, S1 = 1, L2 = 2 (negatives continue downwards)."""
    m = POSITION.search(tok)
    if m is None:
        raise ValueError(f"token has no staff position: {tok}")
    n = int(m.group(2))
    return 2 * (n - 1) if m.group(1) == "L" else 2 * n - 1


def bucket_of(note_tok: str, ext: Sequence[str], stem: str = "") -> list[str]:
    """Head buckets of one chord column: a note token plus the `chordnote-<pos>` tokens that follow it.

    A dyad gives its interval bucket (the 2nd is split by `stem`: "up" / "down", else "2nd_none" for a stemless
    whole note or "2nd_unknown" when the stem is not known); a triad gives "triad" once per chordnote head; each
    member head at or beyond the ledger steps adds "ledger". Why the stem is a parameter: it is not in the tokens.
    """
    base = step_of(note_tok)
    steps = [step_of(t) for t in ext]
    out: list[str] = []
    if len(steps) == 1:
        gap = abs(steps[0] - base)
        name = INTERVAL_BY_STEPS.get(gap, "other")
        if name == "2nd":
            name = {"up": "2nd_up", "down": "2nd_down", STEMLESS: "2nd_none"}.get(stem, "2nd_unknown")
        out.append(name)
    elif len(steps) >= 2:
        out += ["triad"] * len(steps)
    out += ["ledger"] * sum(1 for s in steps if s <= LEDGER_LOW or s >= LEDGER_HIGH)
    return out


def chord_columns(tokens: Sequence[str]) -> list[tuple[str, list[str]]]:
    """(note token, following chordnote tokens) for every chord column, left to right."""
    cols: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(tokens):
        if tokens[i].startswith("note.") and i + 1 < len(tokens) and tokens[i + 1].startswith("chordnote-"):
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("chordnote-"):
                j += 1
            cols.append((tokens[i], list(tokens[i + 1:j])))
            i = j
        else:
            i += 1
    return cols


def mix_report(rows: Iterable[Mapping[str, object]],
               stems: Mapping[str, Sequence[str]] | None = None) -> dict[str, object]:
    """Head buckets per font group and token-level checks over manifest rows.

    Args:
        rows: manifest rows (`tokens`, `font`, `split`, `piece`, `voice`, `system`).
        stems: divisi_summary `stems` (key `<piece>|<voice>|<system>`); without it the 2nd stays "2nd_unknown".
    """
    buckets: dict[str, collections.Counter[str]] = {"in_font": collections.Counter(),
                                                    "held_out": collections.Counter()}
    chord_strips = mismatched = out_of_range = 0
    gootville_train_chord_strips = 0
    for r in rows:
        cols = chord_columns(list(r["tokens"]))  # type: ignore[call-overload]
        if not cols:
            continue
        chord_strips += 1
        font = str(r["font"])
        held_out = font == HELD_OUT_FONT
        if held_out and r.get("split") == "train":
            gootville_train_chord_strips += 1
        strip_stems = (stems or {}).get(f"{r['piece']}|{r['voice']}|{r['system']}")
        aligned = strip_stems is not None and len(strip_stems) == len(cols)
        mismatched += int(stems is not None and not aligned)
        group = buckets["held_out" if held_out else "in_font"]
        for k, (note, ext) in enumerate(cols):
            group.update(bucket_of(note, ext, strip_stems[k] if aligned and strip_stems else ""))
            out_of_range += sum(1 for t in ext if not MEMBER_STEPS[0] <= step_of(t) <= MEMBER_STEPS[1])
    return {"chord_strips": chord_strips, "stem_mismatch_strips": mismatched,
            "member_steps_out_of_range": out_of_range,
            "gootville_train_chord_strips": gootville_train_chord_strips,
            "buckets": {k: dict(v) for k, v in buckets.items()}}


def gate(name: str, value: object, target: str, ok: bool, status: str | None = None) -> dict[str, object]:
    return {"name": name, "value": value, "target": target, "status": status or (PASS if ok else FAIL)}


def share_gate(name: str, count: float, total: float, target: float) -> dict[str, object]:
    v = count / total if total else 0.0
    return gate(name, round(v, 4), f"{target:.2f} +-{SHARE_TOL:.2f}", abs(v - target) <= SHARE_TOL + 1e-9)


def summary_gates(s: Mapping[str, object]) -> list[dict[str, object]]:
    """Section 4 shares and the generator's audit counters, from divisi_summary.json."""
    r: Mapping[str, object] = s["realised"]  # type: ignore[assignment]
    total = int(r["chords_total"])  # type: ignore[call-overload]
    cls: collections.Counter[str] = collections.Counter()
    for k, v in r["class"].items():  # type: ignore[attr-defined]
        cls[k.split(":")[1]] += v
    out = [gate("chords_total", total, "> 0", total > 0)]
    for name, target in INTERVAL_TARGETS.items():
        n = sum(v for k, v in cls.items() if k == name or (name == "2nd" and k.startswith("2nd_")))
        out.append(share_gate(f"interval.{name}", n, total, target))
    for name, target in DURATION_TARGETS.items():
        out.append(share_gate(f"duration.{name}", r["duration"].get(name, 0), total, target))  # type: ignore[attr-defined]
    free, copied = int(r["free"]), int(r["copied"])  # type: ignore[call-overload]
    out.append(share_gate("members.free", free, free + copied, FREE_MEMBER_TARGET))
    stemmed = cls["2nd_up"] + cls["2nd_down"]
    down = cls["2nd_down"] / stemmed if stemmed else 0.0
    out.append(gate("2nd_stems_down", round(down, 4), f">= {STEMS_DOWN_MIN:.2f} of stemmed 2nds", down >= STEMS_DOWN_MIN))
    acc = int(r["accidental_cols"]) / total if total else 0.0  # type: ignore[call-overload]
    out.append(gate("accidental_cols", round(acc, 4), f">= {ACCIDENTAL_COL_MIN:.2f}", acc >= ACCIDENTAL_COL_MIN))
    cross = int(r["crossing"]) / total if total else 0.0  # type: ignore[call-overload]
    out.append(gate("crossing", round(cross, 4), f"<= {CROSSING_MAX:.2f}", cross <= CROSSING_MAX))
    out.append(share_gate("chord_free_strips", int(r["chord_free_strips"]), int(r["strips"]),  # type: ignore[call-overload]
                          CHORD_FREE_TARGET))
    dens = [x for x in s["density_per_strip"] if x > 0]  # type: ignore[attr-defined]
    lo, hi = (min(dens), max(dens)) if dens else (0.0, 0.0)
    out.append(gate("density_range", [round(lo, 3), round(hi, 3)], f"within {list(DENSITY_RANGE)}",
                    bool(dens) and DENSITY_RANGE[0] - 1e-9 <= lo and hi <= DENSITY_RANGE[1] + 1e-9))
    steps = [int(k.split(":")[1]) for k in r["steps"]]  # type: ignore[attr-defined]
    out.append(gate("member_steps_summary", [min(steps), max(steps)] if steps else [], f"within {list(MEMBER_STEPS)}",
                    bool(steps) and MEMBER_STEPS[0] <= min(steps) and max(steps) <= MEMBER_STEPS[1]))
    for key in ("free_new_accidentals", "induced_accidentals"):
        out.append(gate(key, r[key], "== 0", int(r[key]) == 0))  # type: ignore[call-overload]
    missing = s.get("pieces_missing_from_build") or []
    out.append(gate("pieces_missing_from_build", len(missing), "== 0", not missing))  # type: ignore[arg-type]
    return out


def read_rows(path: Path) -> list[dict[str, object]] | None:
    if not path.is_file():
        return None
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def a5_gate(path: Path) -> dict[str, object]:
    """A5 equality: the Phase 2 manifest (which pins every Phase 1 strip) is byte-identical. Missing = fail."""
    if not path.is_file():
        return gate("a5_equality", str(path), A5_SHA256[:8] + "...", False, MISSING)
    got = sha256_of(path)
    return gate("a5_equality", got[:8] + "...", A5_SHA256[:8] + "...", got == A5_SHA256)


def manifest_gates(build: Path, summary: Mapping[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows = read_rows(build / "manifest" / "phase2_manifest.jsonl")
    names = ("gootville_chord_strips_in_train", "member_steps_tokens", "stem_alignment")
    if rows is None:
        return [gate(n, "manifest/phase2_manifest.jsonl not found", "-", False, MISSING) for n in names], {}
    rep = mix_report(rows, summary["stems"])  # type: ignore[arg-type]
    n_strips = int(rep["chord_strips"])  # type: ignore[call-overload]
    mism = int(rep["stem_mismatch_strips"])  # type: ignore[call-overload]
    return [
        gate(names[0], rep["gootville_train_chord_strips"], "== 0", rep["gootville_train_chord_strips"] == 0),
        gate(names[1], rep["member_steps_out_of_range"], "== 0", rep["member_steps_out_of_range"] == 0),
        gate(names[2], f"{mism}/{n_strips}", f"<= {STEM_MISMATCH_MAX:.0%} of chord strips",
             n_strips > 0 and mism <= STEM_MISMATCH_MAX * n_strips),
    ], rep


def test_gates(dirs: Sequence[Path]) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Heads per bucket over all test renders (every font and injection seed); never used for training."""
    if not dirs:
        return [gate("test_buckets", "no --test dirs", "-", True, NOT_RUN)], {}
    total: dict[str, collections.Counter[str]] = {"in_font": collections.Counter(), "held_out": collections.Counter()}
    out: list[dict[str, object]] = []
    for d in dirs:
        rows = read_rows(d / "manifest" / "phase2_manifest.jsonl")
        summ = d / "divisi_summary.json"
        if rows is None or not summ.is_file():
            out.append(gate(f"test_render:{d.name}", "manifest or divisi_summary.json not found", "-", False, MISSING))
            continue
        rep = mix_report(rows, json.loads(summ.read_text(encoding="utf-8"))["stems"])
        for k in total:
            total[k].update(rep["buckets"][k])  # type: ignore[index]
    for b in TEST_BUCKETS:
        for grp, need in (("in_font", TEST_MIN_IN_FONT), ("held_out", TEST_MIN_HELD_OUT)):
            n = total[grp][b]
            ok = n >= need
            status = PASS if ok else (WARN if b in UNDERPOWERED_OK else FAIL)
            out.append(gate(f"test.{b}.{grp}", n, f">= {need}" + (" (warn: underpowered)" if b in UNDERPOWERED_OK else ""),
                            ok, status))
    return out, {k: dict(v) for k, v in total.items()}


def format_table(gates: Sequence[Mapping[str, object]]) -> str:
    w = max(len(str(g["name"])) for g in gates)
    return "\n".join(f"{str(g['status']).upper():8} {str(g['name']):{w}}  {str(g['value']):>22}  target {g['target']}"
                     for g in gates)


def load_summary(build: Path) -> tuple[dict[str, object] | None, str]:
    """divisi_summary.json, or (None, reason) when it is absent or has no `realised` / `stems`."""
    path = build / "divisi_summary.json"
    if not path.is_file():
        return None, f"{path} not found"
    summary = json.loads(path.read_text(encoding="utf-8"))
    if "stems" not in summary or "realised" not in summary:
        return None, "divisi_summary.json lacks `realised` or `stems`"
    return summary, ""


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--test", type=Path, nargs="*", default=[], help="test-render build folders (3 seeds)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--a5-manifest", type=Path, default=A5_DEFAULT_MANIFEST,
                    help="Phase 2 manifest whose sha256 must be the A5 value; missing fails the gate")
    ap.add_argument("--allow-no-test", action="store_true",
                    help="run without test renders: the test-bucket gates are then NOT checked and the run says so")
    args = ap.parse_args(argv)
    summary, why = load_summary(args.build)
    train_rep: dict[str, object] = {}
    if summary is None:
        gates = [gate("divisi_summary", why, "present with realised + stems", False, MISSING)]
    else:
        gates = summary_gates(summary)
        m_gates, train_rep = manifest_gates(args.build, summary)
        gates += m_gates
    t_gates, test_rep = test_gates(args.test)
    if not args.test and not args.allow_no_test:
        t_gates = [gate("test_buckets", "no --test dirs", "test renders required (--allow-no-test to skip)", False)]
    gates += t_gates + [a5_gate(args.a5_manifest)]
    not_run = any(x["status"] == NOT_RUN for x in gates)
    failed = [str(x["name"]) for x in gates if x["status"] not in (PASS, WARN, NOT_RUN)]
    ok = not failed and not not_run
    args.out.write_text(json.dumps({"ok": ok, "test_buckets_checked": not not_run, "gates": gates,
                                    "train_manifest": train_rep, "test_buckets": test_rep}, indent=1),
                        encoding="utf-8")
    print(format_table(gates))
    if failed:
        print("GATES FAILED: " + ", ".join(failed))
    elif not_run:
        print("TEST BUCKETS NOT CHECKED (--allow-no-test); other gates pass")
    else:
        print("ALL GATES PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
