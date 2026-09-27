"""Renders runs/scores/*/score.json into REPORT_tables.md (numbers only; interpretation lives in REPORT.md).

Usage (repo root):  python data/eval_fresh/make_tables.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
SCORES = HERE / "runs" / "scores"
PIECES = {"non_nobis_domine": "Non Nobis Domine (GT verified by the author)",
          "honneur_a_toi": "Honneur a Toi (GT agent-made, not user-verified: diagnostic only)",
          "gaano_ko_ikaw_kamahal": "Gaano Ko Ikaw Kamahal (GT agent-made, not user-verified: diagnostic only)",
          "handog": "Handog (GT agent-made, not user-verified: diagnostic only; divisi systems excluded)"}
CRNNS = ["seed1", "seed2", "baseline"]
VNAME = {"a": "(a) Stage 3 as-is", "b": "(b) + clef/key classifier", "oracle": "oracle GT clef+key (ceiling)"}


def pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def ci(c: Optional[list[float]]) -> str:
    return "" if not c else f" [{100 * c[0]:.1f}, {100 * c[1]:.1f}]"


def failure_note(msg: str) -> str:
    m = re.search(r"detected (\d+) staff region", msg)
    return f"{m[1]} staves, not divisible by 4" if m else msg.split(":", 1)[0]


def load(piece: str, crnn: str) -> dict[str, Any]:
    return json.loads((SCORES / piece / crnn / "score.json").read_text(encoding="utf-8"))


def headline_table(piece: str, key: str = "headline") -> list[str]:
    out = ["| CRNN | Stage 3 | Token SER [95% CI] | Pitch acc (SOW) [95% CI] | Pitch+duration | Rhythm | Clef acc | Key acc | "
           "Note precision | Note F1 | Silent wrong clef | Silent wrong key | Silent octave | Double octave | review_needed | Strips |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for crnn in CRNNS:
        s = load(piece, crnn)
        for v in ("a", "b", "oracle"):
            h = s[v][key]
            c = s[v]["ci95"] if key == "headline" else {}
            out.append(f"| {crnn} | {VNAME[v]} | {pct(h['token_ser'])}{ci(c.get('token_ser'))} | "
                       f"{pct(h['pitch_acc_sow'])}{ci(c.get('pitch_acc_sow'))} | {pct(h['strict_acc'])} | {pct(h['rhythm_acc'])} | "
                       f"{pct(h['clef_acc'])} | {pct(h['key_acc'])} | {pct(h.get('note_precision'))} | {pct(h.get('note_f1'))} | {h['silent_clef_wrong_staves']} | {h['silent_key_wrong_staves']} | "
                       f"{h['silent_wrong_staves']} | {h['double_octave_staves']} | {pct(h['review_needed_rate'])} | "
                       f"{h['n_detected']}/{h['n_strips']} |")
    return out


def gain_table(piece: str) -> list[str]:
    gated = load(piece, "seed1").get("gated", piece == "non_nobis_domine")
    out = ["| CRNN | (b) - (a) pitch accuracy [paired 95% CI] | " + ("Gate |" if gated else
           "Gate criteria (report only: this piece is NOT gated) |"), "|---|---|---|"]
    for crnn in CRNNS:
        s = load(piece, crnn)
        g = s["gate"]
        fails = [k for k, v in g.items() if k != "pass" and not v]
        out.append(f"| {crnn} | {100 * s['b_minus_a_sow']['point']:+.1f} pts{ci(s['b_minus_a_sow']['ci95'])} | "
                   f"{'PASS' if g['pass'] else 'FAIL: ' + ', '.join(fails)}{' (reference only, not gated)' if crnn == 'baseline' and gated else ''} |")
    return out


def per_symbol_table(piece: str) -> list[str]:
    seeds = {c: load(piece, c) for c in ("seed1", "seed2")}
    cats = list(seeds["seed1"]["b"]["per_symbol"].keys())
    out = ["| GT symbol | n | symbol correct, seed1 / seed2 | symbol + pitch correct (a), seed1 / seed2 | "
           "symbol + pitch correct (b), seed1 / seed2 |", "|---|---|---|---|---|"]
    for c in cats:
        d = {k: seeds[k]["b"]["per_symbol"][c] for k in seeds}
        a = {k: seeds[k]["a"]["per_symbol"][c] for k in seeds}
        n = d["seed1"]["n"]
        out.append(f"| {c} | {n} | {d['seed1']['symbol_correct']}/{n} / {d['seed2']['symbol_correct']}/{n} | "
                   f"{a['seed1']['symbol_and_pitch_correct']}/{n} / {a['seed2']['symbol_and_pitch_correct']}/{n} | "
                   f"{d['seed1']['symbol_and_pitch_correct']}/{n} / {d['seed2']['symbol_and_pitch_correct']}/{n} |")
    return out


def voice_table(piece: str) -> list[str]:
    out = ["| Voice | Pitch acc (a) seed1 / seed2 | Pitch acc (b) seed1 / seed2 | Token SER (b) seed1 / seed2 |", "|---|---|---|---|"]
    s = {c: load(piece, c) for c in ("seed1", "seed2")}
    for v in ("Soprano", "Alto", "Tenor", "Bass"):
        out.append(f"| {v} | {pct(s['seed1']['a']['by_voice'][v]['pitch_acc_sow'])} / {pct(s['seed2']['a']['by_voice'][v]['pitch_acc_sow'])} | "
                   f"{pct(s['seed1']['b']['by_voice'][v]['pitch_acc_sow'])} / {pct(s['seed2']['b']['by_voice'][v]['pitch_acc_sow'])} | "
                   f"{pct(s['seed1']['b']['by_voice'][v]['token_ser'])} / {pct(s['seed2']['b']['by_voice'][v]['token_ser'])} |")
    return out


def token_class_table(piece: str) -> list[str]:
    s = {c: load(piece, c) for c in ("seed1", "seed2")}
    out = ["| Token class (version b) | n (GT) | recall exact, seed1 / seed2 | recall class-only (position ignored) | "
           "precision exact |", "|---|---|---|---|---|"]
    for k, d in s["seed1"]["b"]["per_token_class"].items():
        if d["n_ref"] < 3:
            continue
        e = s["seed2"]["b"]["per_token_class"].get(k, {})
        out.append(f"| {k} | {d['n_ref']} | {pct(d['recall_exact'])} / {pct(e.get('recall_exact'))} | "
                   f"{pct(d['recall_class'])} / {pct(e.get('recall_class'))} | {pct(d['precision_exact'])} / {pct(e.get('precision_exact'))} |")
    return out


def main() -> None:
    md = ["# Fresh-photo evaluation: tables (generated by make_tables.py; do not edit by hand)", "",
          "Pitch accuracy (SOW) = GT notes whose sounding pitch is matched by an aligned predicted note; missed strips count "
          "as wrong. Token SER over PrIMuS agnostic tokens (slurs/ties excluded; OOV GT tokens are wildcards). "
          "\"Silent\" = wrong and not flagged review_needed. CIs: 2000 bootstrap resamples over strips.", ""]
    for piece, title in PIECES.items():
        s = load(piece, "seed1")
        md += [f"## {title}", "", "Stage 2 coverage: " + ", ".join(
            f"p{p}: {c['detected']}/{c['expected_staves']}" + (f" (Stage 2 raised: {failure_note(c['failure'])})" if c["failure"] else "")
            for p, c in s["stage2_coverage"].items()), ""]
        md += ["### Headline (end-to-end, all GT strips)", ""] + headline_table(piece) + [""]
        if any(c["failure"] for c in s["stage2_coverage"].values()):
            md += ["### Detected strips only", ""] + headline_table(piece, "headline_detected_only") + [""]
        md += ["### Gain and pre-registered gate" if piece == "non_nobis_domine" else "### Gain (gate criteria shown for reference; not gated)", ""] + gain_table(piece) + [""]
        md += ["### Per-symbol results (all GT strips; symbol = kind + duration)", ""] + per_symbol_table(piece) + [""]
        md += ["### By voice", ""] + voice_table(piece) + [""]
        md += ["### Per token class (version b)", ""] + token_class_table(piece) + [""]
        md += ["Confusion matrices (CSV + PNG): `runs/scores/" + piece + "/<crnn>/cm_{symbol,clef,key}_{a,b,oracle}.*`", ""]
    (HERE / "REPORT_tables.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
