"""build_timing bar-position fields (docs/decisions/backend-bar-step-timing.md)."""

from __future__ import annotations

from typing import Any

from timing_export import StripGeometry, build_timing

VOICES = ("Soprano", "Alto", "Tenor")
PICKUP, BAR = 480, 1920
SYS1_START = PICKUP + 2 * BAR  # system 0 holds pickup + bars 1, 2
# Page 1 (pipeline numbering), identity geometry: strip x == page x.
RIGHTS = {0: [200.0, 500.0, 800.0], 1: [450.0, 800.0]}
FIRST_NOTE = {0: 100.0, 1: 60.0}
TOP = {0: 100, 1: 400}
REPORT: dict[str, Any] = {"pickup_ticks": PICKUP, "systems": [
    {"page_index": 1, "sys_idx": 0, "time_signature": "4/4", "n_bars": 2, "first_bar": 1,
     "start_tick": PICKUP, "bar_ticks": BAR},
    {"page_index": 1, "sys_idx": 1, "time_signature": "4/4", "n_bars": 2, "first_bar": 3,
     "start_tick": SYS1_START, "bar_ticks": BAR}]}


def _inputs(drop_last: bool = False, off_by_two: bool = False) -> dict[str, Any]:
    strips, barlines = [], {}
    events: dict[str, list[dict[str, Any]]] = {}
    for v in VOICES:
        events[v] = []
        for s in (0, 1):
            strips.append(StripGeometry(1, s, v, 0, TOP[s], 1000, TOP[s] + 80, 1.0, 1.0, 64, TOP[s], TOP[s] + 80))
            rights = RIGHTS[s][:-1] if drop_last else RIGHTS[s]
            barlines[(1, s, v)] = rights[:1] if off_by_two and s == 0 else rights
            first_bar = 0 if s == 0 else 3
            tick = 0 if s == 0 else SYS1_START
            events[v].append({"type": "note", "page_index": 1, "sys_idx": s, "global_bar": first_bar,
                              "tick_onset": tick, "ctc_x": FIRST_NOTE[s]})
    return dict(events=events, strips=strips, barlines=barlines, page_sizes=[(1000, 1000)],
                report=REPORT, bpm=120)


def test_bar_fields_order_and_zero_based_page() -> None:
    bars = build_timing(**_inputs())["bars"]
    assert [b["bar"] for b in bars] == [0, 1, 2, 3, 4]
    assert [b["startTick"] for b in bars] == sorted(b["startTick"] for b in bars)
    for b in bars:
        assert {"pageIndex", "systemIndex", "x", "systemTopY", "systemBottomY", "pickup"} <= b.keys()
        assert b["pageIndex"] == 0
    assert [b["systemIndex"] for b in bars] == [0, 0, 0, 1, 1]


def test_pickup_entry() -> None:
    bars = build_timing(**_inputs())["bars"]
    assert (bars[0]["bar"], bars[0]["pickup"], bars[0]["startTick"]) == (0, True, 0)
    assert bars[1]["startTick"] == PICKUP
    assert [b["pickup"] for b in bars[1:]] == [False] * 4


def test_x_is_previous_barline_or_first_note() -> None:
    bars = build_timing(**_inputs())["bars"]
    assert [b["x"] for b in bars] == [100.0, 200.0, 500.0, 60.0, 450.0]


def test_second_system_band() -> None:
    bars = build_timing(**_inputs())["bars"]
    assert (bars[3]["systemTopY"], bars[3]["systemBottomY"]) == (400.0, 480.0)
    assert bars[0]["systemTopY"] == 100.0 and bars[0]["systemTopY"] != bars[3]["systemTopY"]


def test_missing_last_barline_still_gives_all_bars() -> None:
    assert len(build_timing(**_inputs(drop_last=True))["bars"]) == 5


def test_inconsistent_barline_count_returns_empty_events_only() -> None:
    assert build_timing(**_inputs(off_by_two=True)) == {"events": []}


def test_existing_keys_unchanged() -> None:
    timing = build_timing(**_inputs())
    assert {"bar", "startTick", "durTicks", "startMs", "durMs", "numerator", "denominator"} <= timing["bars"][1].keys()
    assert timing["bars"][1]["startMs"] == 500 and timing["bars"][1]["durMs"] == 2000  # 120 bpm: 480 ticks = 500 ms
    ev = timing["events"][0]
    assert set(ev) == {"timestampMs", "pageIndex", "x", "y", "voice", "tick", "bar", "systemIndex",
                       "systemTopY", "systemBottomY"}
    assert (ev["timestampMs"], ev["pageIndex"], ev["bar"], ev["systemIndex"], ev["x"]) == (0, 0, 0, 0, 100.0)
