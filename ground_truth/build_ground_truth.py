"""Build Stage 3/4-shaped ground-truth event JSON from a hand-authored notation file.

Authoring syntax (one line per page/system/voice)::

    page <P> sys <S> <Voice>: <pickup> | <bar 1> | <bar 2> | ...

* The first segment (before the first ``|``) is measure_index 0 -- the pickup, empty for
  voices that start on a full bar. This mirrors Stage 3, where ``measure_index`` starts at 0
  per strip and increments on every barline token.
* Tokens are whitespace-separated: ``PITCH/DUR`` or ``r/DUR``. ``DUR`` is w h q e s t x
  (whole..64th), with a trailing ``.`` for dotted. ``PITCH`` is letter + optional
  ``b``/``#``/``n`` + octave, e.g. ``C4``, ``Bb3``, ``Bn4``. Un-marked letters get the key
  signature applied (KEY_FLATS), like Stage 3's key-signature state machine.
* Chords: ``F3+F2/w`` (shared tick_onset; shared chord_id, per-strip counter like Stage 3).
* Per-pitch flags: leading ``(`` = slur starts, trailing ``)`` = slur ends, trailing ``~`` =
  tied to the next note of the same pitch. Stage 3 has no tie token, so ties are an extra
  field (``tie_to_next``) and are NOT conflated with slurs.
* Tenor is authored as written; sounding pitch = written - 12 (Stage 3 TENOR_CLEF_REFERENCE).
* ticks are local to the strip (reset per system), as in Stage 3; Stage 4 adds global offsets.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

WHOLE_TICKS = 1920
TIME_SIGNATURE = "4/4"
KEY_FLATS = {"B"}
DUR_TICKS = {"w": 1920, "h": 960, "q": 480, "e": 240, "s": 120, "t": 60, "x": 30}
DUR_NAME = {"w": "whole", "h": "half", "q": "quarter", "e": "eighth",
            "s": "sixteenth", "t": "thirty_second", "x": "sixty_fourth"}
NATURAL_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
LETTER_IDX = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
LETTERS_PER_OCTAVE = 7
# Diatonic number (octave * 7 + letter index) of each clef's bottom staff line.
BOTTOM_LINE_DN = {"treble": 4 * LETTERS_PER_OCTAVE + LETTER_IDX["E"],
                  "bass": 2 * LETTERS_PER_OCTAVE + LETTER_IDX["G"]}
VOICE_CLEF = {"Soprano": "treble", "Alto": "treble", "Tenor": "treble", "Bass": "bass"}
TENOR_SOUNDING_OFFSET = -12
VOICE_ORDER = ["Soprano", "Alto", "Tenor", "Bass"]
LINE_RE = re.compile(r"^page\s+(\d+)\s+sys\s+(\d+)\s+(\w+):\s*(.*)$")
PITCH_RE = re.compile(r"^(\()?([A-G])([b#n]?)(-?\d)(\))?(~)?$")


def parse_pitch(item: str) -> dict[str, Any]:
    """Parse one pitch item such as ``(Bb3~`` into its parts."""
    m = PITCH_RE.match(item)
    if not m:
        raise ValueError(f"bad pitch item {item!r}")
    slur_start, letter, acc, octave, slur_end, tie = m.groups()
    return {"letter": letter, "acc": acc, "octave": int(octave), "slur_start": bool(slur_start),
            "slur_end": bool(slur_end), "tie": bool(tie)}


def written_midi(p: dict[str, Any]) -> int:
    """MIDI number of a written pitch, applying the key signature unless explicit."""
    if p["acc"] == "":
        alt = -1 if p["letter"] in KEY_FLATS else 0
    else:
        alt = {"b": -1, "#": 1, "n": 0}[p["acc"]]
    return 12 * (p["octave"] + 1) + NATURAL_SEMITONE[p["letter"]] + alt


def agnostic_position(p: dict[str, Any], clef: str) -> str:
    """Camera-PrIMuS position suffix (L1 = bottom line, S1 = space above it)."""
    step = p["octave"] * LETTERS_PER_OCTAVE + LETTER_IDX[p["letter"]] - BOTTOM_LINE_DN[clef]
    return f"L{step // 2 + 1}" if step % 2 == 0 else f"S{step // 2 + 1}"


def parse_duration(text: str) -> int:
    """Ticks for ``q``, ``e.`` etc. (dot = x1.5 with int truncation, as Stage 3)."""
    key = text.rstrip(".")
    if key not in DUR_TICKS:
        raise ValueError(f"bad duration {text!r}")
    ticks = DUR_TICKS[key]
    return int(ticks * 1.5) if text.endswith(".") else ticks


def build_strip(piece: str, page: int, sys_idx: int, voice: str, body: str) -> list[dict[str, Any]]:
    """Turn one authored line into Stage 3-shaped events (local ticks, per strip)."""
    clef = VOICE_CLEF[voice]
    events: list[dict[str, Any]] = []
    tick, chord_counter, note_n = 0, 0, 0
    slur_active = False
    for measure_index, bar in enumerate(body.split("|")):
        for tok in bar.split():
            pitches_s, dur_s = tok.split("/")
            ticks = parse_duration(dur_s)
            dname = DUR_NAME[dur_s.rstrip(".")]
            base = {"duration_ticks": ticks, "voice": voice, "page_index": page,
                    "sys_idx": sys_idx, "tick_onset": tick, "measure_index": measure_index,
                    "time_signature": TIME_SIGNATURE}
            if pitches_s == "r":
                events.append({"type": "rest", "pitch": None, "chord_id": None,
                               "symbol": f"rest.{dname}", "slur": None, **base,
                               "note_id": None, "tie_to_next": False})
            else:
                items = [parse_pitch(x) for x in pitches_s.split("+")]
                chord_id = None
                if len(items) > 1:
                    chord_counter += 1
                    chord_id = chord_counter
                for i, p in enumerate(items):
                    note_n += 1
                    midi = written_midi(p) + (TENOR_SOUNDING_OFFSET if voice == "Tenor" else 0)
                    if p["slur_start"]:
                        slur_active, slur = True, "start"
                    elif p["slur_end"]:
                        slur_active, slur = False, "end"
                    else:
                        slur = "middle" if slur_active else None
                    events.append({
                        "type": "note", "pitch": midi, "chord_id": chord_id,
                        "symbol": f"note.{dname}-{agnostic_position(p, clef)}", "slur": slur,
                        **base,
                        "note_id": f"{piece}_p{page:02d}_s{sys_idx:02d}_{voice}_n{note_n:03d}",
                        "tie_to_next": p["tie"],
                        "written_pitch": f"{p['letter']}{p['acc']}{p['octave']}",
                        "chord_tail": i > 0,
                    })
            tick += ticks
    return events


def check_strip(events: list[dict[str, Any]], label: str) -> list[str]:
    """Return bar-duration problems: every non-pickup bar must sum to a whole bar (4/4)."""
    sums: dict[int, int] = {}
    for e in events:
        if e.get("chord_tail"):
            continue  # chord tail notes share their head's time
        sums[e["measure_index"]] = sums.get(e["measure_index"], 0) + e["duration_ticks"]
    return [f"{label} measure {m}: {t} ticks (expected {WHOLE_TICKS})"
            for m, t in sums.items() if m != 0 and t != WHOLE_TICKS]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("piece_dir", type=Path)
    args = ap.parse_args()
    piece = args.piece_dir.name
    per_voice: dict[str, list[dict[str, Any]]] = {v: [] for v in VOICE_ORDER}
    problems: list[str] = []
    for raw in (args.piece_dir / "authoring.txt").read_text(encoding="utf8").splitlines():
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        page, sys_idx, voice, body = int(m[1]), int(m[2]), m[3], m[4]
        evs = build_strip(piece, page, sys_idx, voice, body)
        for e in evs:
            e["source_image"] = f"{piece}_pg{page:02d}.jpg"
        problems += check_strip(evs, f"p{page} s{sys_idx} {voice}")
        per_voice[voice] += evs
    for voice, evs in per_voice.items():
        evs.sort(key=lambda e: (e["page_index"], e["sys_idx"], e["tick_onset"]))
        out = args.piece_dir / f"{voice.lower()}_events.json"
        out.write_text(json.dumps(evs, indent=2), encoding="utf8")
        print(f"{voice}: {len(evs)} events -> {out}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("all bars sum to 1920 ticks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
