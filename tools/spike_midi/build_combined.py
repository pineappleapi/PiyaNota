"""Spike B: combined format-1 MIDI (conductor + S/A/T/B ch0-3 + click ch9) from events + timing bars."""
from __future__ import annotations
import math
from typing import Any
from midiutil import MIDIFile

PPQ = 480
VOICES = ("Soprano", "Alto", "Tenor", "Bass")
CLICK_HI, CLICK_LO, CLICK_TICKS = 76, 77, 60  # hi/lo wood block, GM percussion


def meter_for_bar(b: dict[str, Any]) -> tuple[int, int]:
    """(num, den) written to MIDI. Pickup = shortened first measure: num scaled to its length."""
    num, den = b["numerator"], b["denominator"]
    if b.get("pickup"):
        num = max(1, round(b["durTicks"] / (PPQ * 4 / den)))  # shortcut: non-integer pickups round
    return num, den


def click_ticks(bars: list[dict[str, Any]]) -> list[tuple[int, bool]]:
    """(tick, accent). Quarter grid in each bar; accent only on bar start; pickup never accents."""
    out = []
    for b in bars:
        step = PPQ if b["denominator"] <= 4 else PPQ // 2  # shortcut: no secondary stresses (item 8)
        t = 0
        while t < b["durTicks"]:
            out.append((b["startTick"] + t, t == 0 and not b.get("pickup")))
            t += step
    return out


def build_combined(events: dict[str, list[dict[str, Any]]], bars: list[dict[str, Any]], bpm: int, path: str) -> None:
    mf = MIDIFile(numTracks=5, ticks_per_quarternote=PPQ, adjust_origin=False, file_format=1)
    mf.addTempo(0, 0, bpm)  # midiutil routes tempo/timesig into its own leading conductor track
    prev = None
    for b in sorted(bars, key=lambda x: x["startTick"]):
        m = meter_for_bar(b)
        if m != prev:  # one meta event per change
            mf.addTimeSignature(0, b["startTick"] / PPQ, m[0], int(math.log2(m[1])), 24)
            prev = m
    for i, v in enumerate(VOICES):
        mf.addTrackName(i, 0, v)
        mf.addProgramChange(i, i, 0, 0)
        for e in events[v]:
            if e["type"] == "note" and e["pitch"] is not None:
                mf.addNote(i, i, e["pitch"], e["tick_onset"] / PPQ, e["duration_ticks"] / PPQ, 90)
    mf.addTrackName(4, 0, "Click")
    for t, acc in click_ticks(bars):
        mf.addNote(4, 9, CLICK_HI if acc else CLICK_LO, t / PPQ, CLICK_TICKS / PPQ, 120 if acc else 80)
    with open(path, "wb") as f:
        mf.writeFile(f)


def synthetic() -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """3/4 with 1-beat pickup (bar 0), 4 bars 3/4, 2 bars 4/4. Event/bar shapes follow timing_export."""
    layout = [(0, 480, 3, 4, True)] + [(n, 1440, 3, 4, False) for n in range(1, 5)] + [(n, 1920, 4, 4, False) for n in (5, 6)]
    bars, t = [], 0
    for n, d, num, den, pk in layout:
        bars.append(dict(bar=n, startTick=t, durTicks=d, numerator=num, denominator=den, pickup=pk))
        t += d
    base = {"Soprano": 72, "Alto": 67, "Tenor": 60, "Bass": 48}
    ev: dict[str, list[dict[str, Any]]] = {}
    for v, p0 in base.items():
        ev[v], k = [], 0
        for b in bars:
            tt = b["startTick"]
            while tt < b["startTick"] + b["durTicks"]:
                d = min(480 if (k % 5) else 240, b["startTick"] + b["durTicks"] - tt)  # mixes 8ths, never crosses bar
                rest = (k % 7 == 3)
                ev[v].append(dict(type="rest" if rest else "note", pitch=None if rest else p0 + [0, 2, 4, 5, 7, 5, 4][k % 7],
                                  duration_ticks=d, tick_onset=tt, voice=v, global_bar=b["bar"],
                                  time_signature=f'{b["numerator"]}/{b["denominator"]}'))
                tt += d; k += 1
    return ev, bars
