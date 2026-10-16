"""G1b pitch replay: `infer_pitch` on the G1b divisi labels vs Verovio's sounding MIDI (PIYA-106, diagnostic only).

Plan `docs/superpowers/plans/2026-10-16-stage3-divisi-pairing.md` Task 1 Step 3. For every Leipzig strip of a G1b
build (`renders/Leipzig/<piece>/labels.json`), expected = sorted sounding MIDI of the MEI notes of `staff_n` in the
strip's `measures` (Verovio 6.3.0: loadData, renderToMIDI, getMIDIValuesForElement), got = sorted pitches of the
`infer_pitch(tokens, voice)` notes. The labels are synthetic (converter output on Bach chorales with injected
divisi); a match rate here is a check of Stage 3's chord pairing, never accuracy evidence.

Also counts the tied chord members (members with a slur.end before or a slur.start after their onset): Stage 3
per-member ties are deferred (freeze section 1), so these are reported as known-lost.

Usage: python training/phase1/g1b_pitch_replay.py --build <g1b dir> --out <json>
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import stage3_transcription as s3  # noqa: E402

MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
FONT = "Leipzig"
VEROVIO_VERSION = "6.3.0"


def _expected(tk: Any, root: ET.Element, staff_n: str, measures: list[int]) -> list[int]:
    all_measures = list(root.iter(f"{{{MEI_NS}}}measure"))
    pitches: list[int] = []
    for i in measures:
        for staff in all_measures[i].findall(f"{{{MEI_NS}}}staff"):
            if staff.attrib.get("n") != staff_n:
                continue
            for note in staff.iter(f"{{{MEI_NS}}}note"):
                if "grace" in note.attrib:
                    continue
                pitches.append(int(tk.getMIDIValuesForElement(note.attrib[XML_ID])["pitch"]))
    return sorted(pitches)


def _tied_chord_members(tokens: list[str]) -> int:
    """Chord members (base included) that a tie starts or ends on, from the converter's token order."""
    count = 0
    i = 0
    while i < len(tokens):
        if tokens[i].startswith("note.") and i + 1 < len(tokens) and tokens[i + 1].startswith("chordnote-"):
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("chordnote-"):
                j += 1
            members = {s3._position_suffix(tokens[i])} | {s3._position_suffix(t) for t in tokens[i + 1:j]}
            tied: set[str | None] = set()
            k = i - 1
            while k >= 0 and tokens[k].startswith(("accidental.", "slur.end", "fermata.")):
                if tokens[k].startswith("slur.end"):
                    tied.add(s3._position_suffix(tokens[k]))
                k -= 1
            k = j
            while k < len(tokens) and tokens[k].startswith(("dot-", "slur.start")):
                if tokens[k].startswith("slur.start"):
                    tied.add(s3._position_suffix(tokens[k]))
                k += 1
            count += len(tied & members)
            i = j
        else:
            i += 1
    return count


def replay(build: Path) -> dict[str, Any]:
    import verovio
    tk = verovio.toolkit()
    if not tk.getVersion().startswith(VEROVIO_VERSION):
        raise RuntimeError(f"verovio {tk.getVersion()} is not the oracle version {VEROVIO_VERSION}")
    strips = chord_strips = match = chord_match = tied_members = 0
    mismatches: list[dict[str, Any]] = []
    for piece_dir in sorted((build / "renders" / FONT).iterdir()):
        mei_path = build / "corpus" / f"{piece_dir.name}.mei"
        mei = mei_path.read_text(encoding="utf-8")
        if not tk.loadData(mei):
            raise RuntimeError(f"verovio could not load {mei_path}")
        tk.renderToMIDI()
        root = ET.fromstring(mei)
        for row in json.loads((piece_dir / "labels.json").read_text(encoding="utf-8")):
            tokens: list[str] = row["tokens"]
            expected = _expected(tk, root, row["staff_n"], row["measures"])
            with contextlib.redirect_stdout(io.StringIO()):
                events = s3.infer_pitch(tokens, row["voice"])
            got = sorted(e["pitch"] for e in events if e["type"] == "note")
            is_chord = any(t.startswith("chordnote-") for t in tokens)
            strips += 1
            chord_strips += is_chord
            tied_members += _tied_chord_members(tokens)
            if got == expected:
                match += 1
                chord_match += is_chord
            else:
                mismatches.append({"piece": piece_dir.name, "page": row["page"], "system": row["system"],
                                   "voice": row["voice"], "chord": is_chord, "n_expected": len(expected),
                                   "n_got": len(got), "missing": sorted((_ms(expected, got))),
                                   "extra": sorted(_ms(got, expected)), "tokens": tokens})
    return {"strips": strips, "chord_strips": chord_strips, "match": match, "chord_match": chord_match,
            "tied_chord_members": tied_members, "mismatches": mismatches}


def _ms(a: list[int], b: list[int]) -> list[int]:
    """Multiset a - b."""
    rest = list(b)
    out: list[int] = []
    for x in a:
        if x in rest:
            rest.remove(x)
        else:
            out.append(x)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = replay(args.build)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print({k: v for k, v in result.items() if k != "mismatches"}, "mismatches", len(result["mismatches"]))
    for m in result["mismatches"]:
        print(f"  {m['piece']} p{m['page']} s{m['system']} {m['voice']} chord={m['chord']} "
              f"n {m['n_expected']}/{m['n_got']} missing {m['missing']} extra {m['extra']}")


if __name__ == "__main__":
    main()
