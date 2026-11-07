"""One format-1 MIDI for in-app playback: conductor, S/A/T/B on channels 0-3, click on channel 9.

Pure standard library (midiutil is not a backend dependency). Built from the timing ``bars`` that
already drive the app click, so notes and click share one tick grid. Logic follows
``tools/spike_midi/build_combined.py``.
"""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Mapping, Sequence
from typing import Any

LOG = logging.getLogger(__name__)

PPQ = 480
VOICES = ("Soprano", "Alto", "Tenor", "Bass")
CLICK_CHANNEL = 9
CLICK_HI, CLICK_LO = 76, 77  # GM percussion hi/lo wood block
CLICK_TICKS = 60
CLICK_VEL_ACCENT, CLICK_VEL_SOFT = 120, 80
NOTE_VELOCITY = 90
MICROS_PER_MINUTE = 60_000_000
MIDI_MAX_DATA = 127
_BAR_FIELDS = ("startTick", "durTicks", "numerator", "denominator")


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _track(items: list[tuple[int, int, bytes]]) -> bytes:
    """items = (tick, order, raw event). Order 0 sorts before 1 at equal ticks (note-off before note-on)."""
    body, last = bytearray(), 0
    for tick, _, raw in sorted(items, key=lambda x: (x[0], x[1])):
        body += _vlq(tick - last) + raw
        last = tick
    body += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def _name(text: str) -> tuple[int, int, bytes]:
    data = text.encode("ascii")
    return 0, 0, b"\xff\x03" + bytes([len(data)]) + data


def _note(items: list[tuple[int, int, bytes]], ch: int, pitch: int, tick: int, dur: int, vel: int) -> None:
    items.append((tick, 1, bytes([0x90 | ch, pitch, vel])))
    items.append((tick + dur, 0, bytes([0x80 | ch, pitch, 0])))


def _usable(bars: Sequence[Mapping[str, Any]]) -> bool:
    for b in bars:
        if not all(isinstance(b.get(k), int) and not isinstance(b.get(k), bool) for k in _BAR_FIELDS):
            return False
        den = b["denominator"]
        if b["startTick"] < 0 or b["durTicks"] <= 0 or b["numerator"] <= 0 or den <= 0 or den & (den - 1):
            return False
    return True


def _meter(b: Mapping[str, Any]) -> tuple[int, int]:
    """(numerator, denominator) written to MIDI; a pickup is a shortened first measure."""
    num, den = b["numerator"], b["denominator"]
    if b.get("pickup"):
        # shortcut: a pickup that is not a whole number of beats is rounded to one, fine for click alignment.
        num = max(1, round(b["durTicks"] / (PPQ * 4 / den)))
    return num, den


def build_combined_midi(
    events: Mapping[str, Sequence[Mapping[str, Any]]],
    bars: Sequence[Mapping[str, Any]] | None,
    bpm: int | None,
) -> bytes | None:
    """Build the combined file, or None when bars/tempo are missing or unusable.

    Args:
        events: Voice-capitalised Stage 4 events (``Soprano`` ... ``Bass``); rests are skipped.
        bars: Timing ``bars`` (startTick, durTicks, numerator, denominator, optional pickup).
        bpm: Tempo of the render; stored as the base tempo.
    """
    if not bars or not isinstance(bpm, int) or isinstance(bpm, bool) or bpm <= 0 or not _usable(bars):
        return None
    ordered = sorted(bars, key=lambda b: b["startTick"])
    cond: list[tuple[int, int, bytes]] = [
        _name("Conductor"), (0, 0, b"\xff\x51\x03" + round(MICROS_PER_MINUTE / bpm).to_bytes(3, "big"))]
    prev: tuple[int, int] | None = None
    for b in ordered:
        m = _meter(b)
        if m != prev:  # one meta event per change
            prev = m
            cond.append((b["startTick"], 0, bytes([0xFF, 0x58, 4, min(m[0], 255), int(math.log2(m[1])), 24, 8])))
    tracks = [_track(cond)]
    for ch, voice in enumerate(VOICES):
        items = [_name(voice), (0, 0, bytes([0xC0 | ch, 0]))]  # GM program 0, acoustic piano
        for e in events.get(voice, ()):
            pitch = e.get("pitch")
            if e.get("type") == "note" and isinstance(pitch, int) and 0 <= pitch <= MIDI_MAX_DATA:
                _note(items, ch, pitch, int(e["tick_onset"]), max(1, int(e["duration_ticks"])), NOTE_VELOCITY)
        tracks.append(_track(items))
    click = [_name("Click")]
    for b in ordered:
        step = PPQ if b["denominator"] <= 4 else PPQ // 2  # shortcut: no secondary stresses in compound meters
        for t in range(0, b["durTicks"], step):
            accent = t == 0 and not b.get("pickup")
            _note(click, CLICK_CHANNEL, CLICK_HI if accent else CLICK_LO, b["startTick"] + t, CLICK_TICKS,
                  CLICK_VEL_ACCENT if accent else CLICK_VEL_SOFT)
    tracks.append(_track(click))
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ) + b"".join(tracks)
