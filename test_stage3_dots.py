"""Standalone checks for augmentation-dot durations (PIYA-109 AC3: dotted 1.5x, double-dotted 1.75x).

Run: ``python test_stage3_dots.py`` (exit code 1 on any failure). No test framework in this repo.
"""
from __future__ import annotations

import sys

from ground_truth.build_ground_truth import parse_duration
from stage3_transcription import _dotted_ticks, infer_pitch

CLEF = "clef.G-L2"
FAILURES: list[str] = []


def check(name: str, got: object, want: object) -> None:
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def durations(tokens: list[str]) -> list[tuple[str, int, int]]:
    """(type, tick_onset, duration_ticks) per event for a treble-clef Soprano strip."""
    return [(e["type"], e["tick_onset"], e["duration_ticks"]) for e in infer_pitch([CLEF, *tokens])]


def main() -> int:
    # Arithmetic: n dots = base * (2 - 1/2**n), floored.
    check("quarter 0 dots", _dotted_ticks(480, 0), 480)
    check("quarter 1 dot", _dotted_ticks(480, 1), 720)
    check("quarter 2 dots", _dotted_ticks(480, 2), 840)
    check("quarter 3 dots", _dotted_ticks(480, 3), 900)
    check("eighth 2 dots", _dotted_ticks(240, 2), 420)
    check("32nd 2 dots (last exact)", _dotted_ticks(60, 2), 105)
    check("64th 2 dots (52.5 floored)", _dotted_ticks(30, 2), 52)

    # Notes through infer_pitch; the next onset must be the dotted note's end.
    check("single-dotted quarter", durations(["note.quarter-L4", "dot-S4", "note.quarter-L4"]),
          [("note", 0, 720), ("note", 720, 480)])
    check("double-dotted quarter + sixteenth",
          durations(["note.quarter-L4", "dot-S4", "dot-S4", "note.sixteenth-L4"]),
          [("note", 0, 840), ("note", 840, 120)])
    check("double-dotted eighth", durations(["note.eighth-L4", "dot-S4", "dot-S4", "note.quarter-L4"]),
          [("note", 0, 420), ("note", 420, 480)])
    # Dot counts reset on the next event: q. e. is 720 + 360, not a 2-dot eighth.
    check("dots do not carry to the next event",
          durations(["note.quarter-L4", "dot-S4", "note.eighth-L4", "dot-S4", "note.quarter-L4"]),
          [("note", 0, 720), ("note", 720, 360), ("note", 1080, 480)])

    # Rests.
    check("double-dotted quarter rest", durations(["rest.quarter-L3", "dot-S3", "dot-S3", "note.quarter-L4"]),
          [("rest", 0, 840), ("note", 840, 480)])
    check("dotted half rest", durations(["rest.half-L3", "dot-S3", "note.quarter-L4"]),
          [("rest", 0, 1440), ("note", 1440, 480)])

    # A dot never follows a multi-measure rest; a misread one must not stretch it. The multirest sits
    # after a barline because a token straight after the clef is read by the opening key-signature stage.
    check("dot after multirest ignored",
          durations(["note.quarter-L4", "barline-L1", "multirest-L3", "dot-S3", "note.quarter-L4"]),
          [("note", 0, 480), ("rest", 480, 1920), ("note", 2400, 480)])

    # The chord-tail guard (dotting a tail must not move the cursor) cannot be reached through
    # infer_pitch: its chord block never fires (no chord token in Camera-PrIMuS; CLAUDE.md known gap),
    # so consecutive notes are sequential and the dot lands on the second one.
    check("dot after two sequential notes", durations(["note.quarter-L2", "note.quarter-L4", "dot-S4",
                                                       "note.quarter-L3"]),
          [("note", 0, 480), ("note", 480, 720), ("note", 1200, 480)])

    # Ground-truth builder, written independently of Stage 3.
    for text, want in (("q", 480), ("q.", 720), ("q..", 840), ("e..", 420), ("h.", 1440), ("x..", 52)):
        check(f"parse_duration({text!r})", parse_duration(text), want)

    for f in FAILURES:
        print("FAIL", f)
    print(f"{'FAILED' if FAILURES else 'OK'}: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
