"""PiyaNota timing export: maps Stage 4 events to page pixels and milliseconds for the app highlight.

Pure python (no torch/cv2) so the backend can import it. Contract: ``build_timing`` never raises;
any inconsistency returns ``{"events": []}`` and logs the reason, because audio must still ship
without a highlight (docs/decisions/piya-106-timing-x-mapping.md).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)

STRIP_HEIGHT_PX = 64          # Stage 2 STRIP_HEIGHT; strip x is in these pixels
DEFAULT_PPQ = 480             # Stage 4 TICKS_PER_QUARTER
STAFF_LINE_GAPS = 4           # a 5-line staff box spans 4 staff spaces
MS_PER_MINUTE = 60000
# Blend a CTC x with the bar interpolation only when they agree within this many staff spaces.
BLEND_MAX_STAFF_SPACES = 1.0
# Stage 1 numbers pages from 1; the app and ``page_sizes`` are 0-based.
PIPELINE_FIRST_PAGE = 1
VOICES = ("Soprano", "Alto", "Tenor", "Bass")

BarlineKey = tuple[int, int, str]   # (page_index, sys_idx, voice) as Stage 2 / Stage 3 number them


@dataclass(frozen=True)
class StripGeometry:
    """Where one Stage 2 strip came from on the cleaned (detection) page.

    Attributes:
        crop_x1, crop_y1, crop_x2, crop_y2: crop box on the detection page.
        kx, ky: native strip source size / detection page size.
        crop_h_src: crop height in strip-source pixels (the strip was shrunk from this to 64).
        staff_y1, staff_y2: the staff box on the detection page.
    """
    page_index: int
    sys_idx: int
    voice: str
    crop_x1: int
    crop_y1: int
    crop_x2: int
    crop_y2: int
    kx: float
    ky: float
    crop_h_src: int
    staff_y1: int
    staff_y2: int


class TimingInconsistent(Exception):
    """Internal: the inputs cannot be placed; caught by build_timing."""


def strip_x_to_page_x(strip_x: float, geo: StripGeometry) -> float:
    """Converts a strip x (64 px high strip) to a cleaned-page x."""
    if not math.isfinite(strip_x):
        raise TimingInconsistent(f"non-finite strip x {strip_x}")
    return geo.crop_x1 + strip_x * (geo.crop_h_src / STRIP_HEIGHT_PX) / geo.kx


def timestamp_ms(tick: int, bpm: int, ppq: int = DEFAULT_PPQ) -> int:
    """Milliseconds of ``tick`` at constant tempo ``bpm`` (the bpm the MIDI is rendered with)."""
    return round(tick / ppq * MS_PER_MINUTE / bpm)


def median_barlines(per_voice: dict[str, list[float]]) -> list[float]:
    """Per-bar barline x as the median over voices, dropping voices whose count is not the mode.

    Args:
        per_voice: {voice: barline page-x list, left to right}.

    Returns:
        Medians (empty when no voice has barlines). Ties for the mode go to the larger count.
    """
    counts: dict[int, int] = {}
    for xs in per_voice.values():
        counts[len(xs)] = counts.get(len(xs), 0) + 1
    if not counts:
        return []
    mode = max(counts, key=lambda n: (counts[n], n))
    kept = [xs for xs in per_voice.values() if len(xs) == mode]
    return [median(col) for col in zip(*kept)]


def _bar_layout(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Flat bar list (pickup = bar 0) from the Stage 4 report."""
    bars: list[dict[str, Any]] = []
    pickup = int(report.get("pickup_ticks", 0))
    for i, sysinfo in enumerate(report["systems"]):
        where = dict(page=sysinfo["page_index"], sys=sysinfo["sys_idx"])
        # Per-bar meters when Stage 4 gives them (a meter can change mid-system); else one per system.
        per_bar = sysinfo.get("bars") or [{"ticks": sysinfo["bar_ticks"], "time_signature": sysinfo["time_signature"]}
                                          ] * int(sysinfo["n_bars"])
        if i == 0 and pickup > 0:
            num, den = (int(v) for v in str(sysinfo["time_signature"]).split("/"))
            bars.append(dict(bar=0, startTick=0, durTicks=pickup, numerator=num, denominator=den, **where))
        start = int(sysinfo["start_tick"])
        for r, b in enumerate(per_bar[:int(sysinfo["n_bars"])]):
            num, den = (int(v) for v in str(b["time_signature"]).split("/"))
            bars.append(dict(bar=int(sysinfo["first_bar"]) + r, startTick=start, durTicks=int(b["ticks"]),
                             numerator=num, denominator=den, **where))
            start += int(b["ticks"])
    return bars


def _bar_edges(rights: list[float], first_left: float | None, n_bars: int) -> list[tuple[float, float]]:
    """(left, right) page x of each bar of one system.

    Bar j ends at rights[j]. A missing last barline (the CRNN often drops the final one) is
    extrapolated with the mean bar width. The first bar's left edge is the median first-note x,
    because the header width is not known.
    """
    if len(rights) == n_bars - 1 and n_bars >= 2:
        width = (rights[-1] - rights[0]) / (len(rights) - 1) if len(rights) > 1 else rights[0] - (first_left or 0.0)
        rights = rights + [rights[-1] + width]
    if len(rights) != n_bars:
        raise TimingInconsistent(f"{len(rights)} barlines for {n_bars} bars")
    if first_left is None:
        raise TimingInconsistent("no CTC x in the first bar to anchor its left edge")
    edges = list(zip([first_left] + rights[:-1], rights))
    if any(r <= left for left, r in edges):
        raise TimingInconsistent("barlines are not increasing")
    return edges


def build_timing(
    events: dict[str, list[dict[str, Any]]],
    strips: list[StripGeometry],
    barlines: dict[BarlineKey, list[float]],
    page_sizes: list[tuple[int, int]],
    report: dict[str, Any],
    bpm: int,
    ppq: int = DEFAULT_PPQ,
) -> dict[str, Any]:
    """Builds the app timing file ({"events": [...], "bars": [...]}) or {"events": []} on any problem.

    Args:
        events: Stage 4 output {voice: [event]}; note events carry ``ctc_x`` (Stage 3 barlines_out mode).
        strips: Stage 2 geometry, one per strip (``detect_staff_regions(geometry_out=)``).
        barlines: Stage 3 strip-pixel barline x per (page_index, sys_idx, voice) (``barlines_out=``).
        page_sizes: (width, height) of each cleaned page, 0-based page order; bounds x and y.
            Pipeline ``page_index`` values are 1-based; the output ``pageIndex`` is 0-based.
        report: Stage 4 report (``systems``, ``pickup_ticks``).
        bpm: tempo the MIDI was rendered with.
        ppq: ticks per quarter note.

    Returns:
        The timing dict. Never raises: the reason for an empty result is logged.
    """
    try:
        return _build(events, strips, barlines, page_sizes, report, bpm, ppq)
    except (TimingInconsistent, KeyError, ValueError, TypeError, ZeroDivisionError, IndexError) as exc:
        logger.warning("timing export skipped, highlight disabled: %s: %s", type(exc).__name__, exc)
        return {"events": []}


def _build(events: dict[str, list[dict[str, Any]]], strips: list[StripGeometry],
           barlines: dict[BarlineKey, list[float]], page_sizes: list[tuple[int, int]],
           report: dict[str, Any], bpm: int, ppq: int) -> dict[str, Any]:
    if bpm <= 0 or ppq <= 0:
        raise TimingInconsistent(f"bad bpm/ppq {bpm}/{ppq}")
    geo = {(g.page_index, g.sys_idx, g.voice): g for g in strips}
    bars = _bar_layout(report)
    if not bars:
        raise TimingInconsistent("no bars in the Stage 4 report")
    by_system: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for b in bars:
        by_system.setdefault((b["page"], b["sys"]), []).append(b)

    out_events: list[dict[str, Any]] = []
    out_bars: list[dict[str, Any]] = []
    for (page, sysi), sys_bars in by_system.items():
        voice_geo = {v: geo[(page, sysi, v)] for v in VOICES if (page, sysi, v) in geo}
        if not voice_geo:
            raise TimingInconsistent(f"no strip geometry for page {page} system {sysi}")
        out_page = page - PIPELINE_FIRST_PAGE
        if not 0 <= out_page < len(page_sizes):
            raise TimingInconsistent(f"page {page} has no size")
        per_voice = {v: [strip_x_to_page_x(x, voice_geo[v]) for x in barlines.get((page, sysi, v), [])]
                     for v in voice_geo}
        sys_events = [(v, e) for v, evs in events.items() for e in evs
                      if e.get("type") == "note" and e["page_index"] == page and e["sys_idx"] == sysi]
        # Left edge of bar 1 per voice: the note at the bar's first tick, else that voice's leftmost note.
        first_xs = []
        for v in voice_geo:
            in_bar = [e for vv, e in sys_events if vv == v and e.get("global_bar") == sys_bars[0]["bar"]
                      and "ctc_x" in e]
            at_start = [e for e in in_bar if int(e["tick_onset"]) == sys_bars[0]["startTick"]]
            if in_bar:
                first_xs.append(min(strip_x_to_page_x(e["ctc_x"], voice_geo[v]) for e in (at_start or in_bar)))
        edges = _bar_edges(median_barlines(per_voice), median(first_xs) if first_xs else None, len(sys_bars))
        top = min(g.staff_y1 for g in voice_geo.values())
        bottom = max(g.staff_y2 for g in voice_geo.values())
        space = min(g.staff_y2 - g.staff_y1 for g in voice_geo.values()) / STAFF_LINE_GAPS
        page_w, page_h = page_sizes[out_page]
        # Bar x: for bar j > 0 of a system it is the median barline of bar j-1 (measured). For a system's
        # first bar (and the pickup in system 0) it is the median first-note x: the header width is not
        # known, so that line may sit slightly right of the true barline and is NOT a measured barline.
        for b, (left, _right) in zip(sys_bars, edges):
            out_bars.append({
                "bar": b["bar"], "startTick": b["startTick"], "durTicks": b["durTicks"],
                "startMs": timestamp_ms(b["startTick"], bpm, ppq), "durMs": timestamp_ms(b["durTicks"], bpm, ppq),
                "numerator": b["numerator"], "denominator": b["denominator"],
                "pageIndex": out_page, "systemIndex": sysi,
                "x": round(min(max(left, 0.0), float(page_w)), 1),
                "systemTopY": float(top), "systemBottomY": float(bottom),
                "pickup": b["bar"] == 0 and int(report.get("pickup_ticks", 0)) > 0})
        for voice, e in sys_events:
            g = voice_geo.get(voice)
            if g is None:
                raise TimingInconsistent(f"no geometry for {voice} p{page} s{sysi}")
            tick = int(e["tick_onset"])
            idx = next((k for k, b in enumerate(sys_bars)
                        if b["startTick"] <= tick < b["startTick"] + b["durTicks"]), None)
            if idx is None:
                raise TimingInconsistent(f"tick {tick} outside system bars (p{page} s{sysi} {voice})")
            bar, (left, right) = sys_bars[idx], edges[idx]
            x = left + (tick - bar["startTick"]) / bar["durTicks"] * (right - left)
            if "ctc_x" in e:
                ctc = strip_x_to_page_x(e["ctc_x"], g)
                if abs(ctc - x) <= BLEND_MAX_STAFF_SPACES * space:
                    x = 0.5 * (x + ctc)
            out_events.append({
                "timestampMs": timestamp_ms(tick, bpm, ppq), "pageIndex": out_page,
                "x": round(min(max(x, 0.0), float(page_w)), 1),
                "y": round(min(max((g.staff_y1 + g.staff_y2) / 2, 0.0), float(page_h)), 1),
                "voice": voice, "tick": tick, "bar": bar["bar"], "systemIndex": sysi,
                "systemTopY": float(top), "systemBottomY": float(bottom)})
    out_events.sort(key=lambda ev: (ev["timestampMs"], ev["pageIndex"], ev["x"]))
    out_bars.sort(key=lambda b: (b["startTick"], b["pageIndex"]))
    return {"events": out_events, "bars": out_bars}
