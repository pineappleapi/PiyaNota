"""Combined playback MIDI builder: structure, channels, click, pickup, unusable input (pure, no DB)."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from backend.midi_combined import PPQ, VOICES, build_combined_midi


def _bars(layout: list[tuple[int, int, int, bool]], den: int = 4) -> list[dict[str, Any]]:
    """layout = (bar, durTicks, numerator, pickup)."""
    out, t = [], 0
    for n, d, num, pk in layout:
        out.append(dict(bar=n, startTick=t, durTicks=d, numerator=num, denominator=den, pickup=pk))
        t += d
    return out


def _events(bars: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    base = {"Soprano": 72, "Alto": 67, "Tenor": 60, "Bass": 48}
    ev: dict[str, list[dict[str, Any]]] = {}
    for v, p in base.items():
        ev[v] = [dict(type="note", pitch=p, tick_onset=b["startTick"], duration_ticks=PPQ) for b in bars]
        ev[v].append(dict(type="rest", pitch=None, tick_onset=0, duration_ticks=PPQ))
    return ev


def _vlq(data: bytes, i: int) -> tuple[int, int]:
    n = 0
    while True:
        b = data[i]
        i += 1
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            return n, i


def _parse(blob: bytes) -> tuple[tuple[int, int, int], list[list[tuple[int, bytes]]]]:
    assert blob[:4] == b"MThd"
    fmt, ntrk, ppq = struct.unpack(">HHH", blob[8:14])
    i, tracks = 14, []
    for _ in range(ntrk):
        assert blob[i:i + 4] == b"MTrk"
        (n,) = struct.unpack(">I", blob[i + 4:i + 8])
        body, j, tick, evs, status = blob[i + 8:i + 8 + n], 0, 0, [], 0
        while j < len(body):
            d, j = _vlq(body, j)
            tick += d
            if body[j] == 0xFF:
                ln = body[j + 2]
                evs.append((tick, bytes(body[j:j + 3 + ln])))
                j += 3 + ln
                continue
            status = body[j]
            size = 2 if status & 0xF0 in (0x80, 0x90) else 1
            evs.append((tick, bytes(body[j:j + 1 + size])))
            j += 1 + size
        tracks.append(evs)
        i += 8 + n
    return (fmt, ntrk, ppq), tracks


def _ons(track: list[tuple[int, bytes]], ch: int) -> list[tuple[int, int, int]]:
    return [(t, e[1], e[2]) for t, e in track if e[0] == 0x90 | ch and e[2] > 0]


def test_four_four_with_pickup() -> None:
    bars = _bars([(0, PPQ, 4, True), (1, 4 * PPQ, 4, False), (2, 4 * PPQ, 4, False)])
    blob = build_combined_midi(_events(bars), bars, 90)
    assert blob is not None
    head, tracks = _parse(blob)
    assert head == (1, 6, PPQ)  # conductor + 4 voices + click
    timesigs = [(t, e) for t, e in tracks[0] if e[:2] == b"\xff\x58"]
    assert [(t, e[3], e[4]) for t, e in timesigs] == [(0, 1, 2), (PPQ, 4, 2)]  # pickup = 1/4 first measure
    assert any(e == b"\xff\x51\x03" + (666667).to_bytes(3, "big") for _, e in tracks[0])
    for ch in range(4):
        assert len(_ons(tracks[1 + ch], ch)) == 3  # rest skipped, one note per bar
    clicks = _ons(tracks[5], 9)
    assert len(clicks) == 1 + 4 + 4
    assert [t for t, _, _ in clicks][:3] == [0, PPQ, 2 * PPQ]
    assert [v for _, _, v in clicks if v == 120] == [120, 120]  # downbeats of bars 1 and 2 only
    assert clicks[0][2] == 80  # pickup does not accent
    assert {n for _, n, _ in clicks} == {76, 77}


def test_three_four_meter_event() -> None:
    bars = _bars([(1, 3 * PPQ, 3, False), (2, 3 * PPQ, 3, False)])
    blob = build_combined_midi(_events(bars), bars, 120)
    assert blob is not None
    _, tracks = _parse(blob)
    assert [(t, e[3], e[4]) for t, e in tracks[0] if e[:2] == b"\xff\x58"] == [(0, 3, 2)]  # no repeat event
    assert len(_ons(tracks[5], 9)) == 6


@pytest.mark.parametrize("bars", [None, [], [dict(startTick=0, durTicks=0, numerator=4, denominator=4)],
                                  [dict(startTick=0, durTicks=480, numerator=4, denominator=3)],
                                  [dict(startTick=0, durTicks=480, numerator=4)]])
def test_unusable_bars_give_none(bars: Any) -> None:
    assert build_combined_midi(_events(_bars([(1, 1920, 4, False)])), bars, 90) is None


def test_missing_tempo_gives_none() -> None:
    bars = _bars([(1, 4 * PPQ, 4, False)])
    assert build_combined_midi(_events(bars), bars, None) is None
    assert VOICES == ("Soprano", "Alto", "Tenor", "Bass")


def test_negative_onset_is_dropped_not_hung() -> None:
    bars = _bars([(1, 4 * PPQ, 4, False)])
    ev = _events(bars)
    ev["Soprano"].append(dict(type="note", pitch=70, tick_onset=-5, duration_ticks=PPQ))
    blob = build_combined_midi(ev, bars, 100)
    assert blob is not None
    _, tracks = _parse(blob)
    assert all(p != 70 for _, p, _ in _ons(tracks[1], 0))


def test_failed_voice_is_silent() -> None:
    bars = _bars([(1, 4 * PPQ, 4, False)])
    blob = build_combined_midi(_events(bars), bars, 100, ["tenor"])
    assert blob is not None
    _, tracks = _parse(blob)
    assert _ons(tracks[3], 2) == [] and _ons(tracks[1], 0) != []
