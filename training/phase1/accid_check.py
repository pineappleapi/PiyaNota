"""Accidental-glyph counting for the divisi label check (PIYA-106 A7, ml-cv-lead change 5).

Why: the notehead check cannot see a lost, doubled or misplaced accidental (e.g. one accidental repeated across the
parts merged onto a staff). Vector PDFs carry every accidental, including key-signature glyphs, as a font glyph, so the
count per staff and per bar must equal the label's `accidental.*` tokens. The header (key signature) is counted on
BOTH sides, in bar 1 / the first bar of the strip, so no header-boundary guess is needed.

Pure counting lives here (no PyMuPDF import at module level in the logic) so tests can run without a PDF.
"""
from __future__ import annotations

# Accidental glyphs by font, read from SMuFL (Leland) and from contact sheets / glyph listings of the PDFs:
# Maestro (For Good): U+03B1 flat, U+00B5 natural; its sharp glyph never occurs in the labelled pieces (not found, so
# a sharp there would be missed and show as a mismatch). TTkStava (Moonriver): '#' is a FLAT, '.' a natural.
ACCIDENTAL_GLYPHS: dict[str, frozenset[str]] = {
    "Leland": frozenset(""),
    "Maestro": frozenset("αµ"),
    "TTkStava": frozenset("#."),
}
BARLINE_MERGE_PT = 4.5    # thin+thick / double barlines are one label token; bars are never this narrow
BARLINE_SPAN_TOL = 1.0    # pt a barline may fall short of the outer staff lines
BARLINE_MAX_WIDTH = 2.5   # pt; stems and barlines are thinner, thick final barlines are merged anyway
BARLINE_MIN_HEIGHT = 5.0  # pt
PAGE_SPAN_FRACTION = 0.9  # of the page height
CONSENSUS_FRAC = 0.6      # share of a system's staves that must carry a barline at the same x
CONSENSUS_TOL = 1.5       # pt
LEFT_EDGE_TOL = 6.0       # pt from the staff left end: the system barline, not a bar boundary
RIGHT_EDGE_TOL = 6.0      # pt: a barline this close to the staff end closes the system


def label_bar_counts(tokens: list[str]) -> list[int]:
    """Accidental tokens per bar; a trailing empty segment after the last barline is not a bar."""
    bars = [0]
    for t in tokens:
        if t.startswith("barline"):
            bars.append(0)
        elif t.startswith("accidental."):
            bars[-1] += 1
    return bars[:-1] if len(bars) > 1 and not _tail_has_tokens(tokens) else bars


def _tail_has_tokens(tokens: list[str]) -> bool:
    last_bar = max((i for i, t in enumerate(tokens) if t.startswith("barline")), default=-1)
    return any(not t.startswith("barline") for t in tokens[last_bar + 1:])


def merge_barlines(xs: list[float]) -> list[float]:
    """Collapse barline x's closer than BARLINE_MERGE_PT (double/final barlines, duplicated drawing items)."""
    out: list[float] = []
    for x in sorted(xs):
        if not out or x - out[-1] > BARLINE_MERGE_PT:
            out.append(x)
    return out


def pdf_bar_counts(glyph_xs: list[float], barlines: list[float], left: float, right: float) -> list[int]:
    """Glyphs per bar of one staff. Barlines at the left edge are dropped; a tail after the last barline that holds
    no glyph and sits at the staff end is not a bar."""
    cuts = [x for x in barlines if x > left + LEFT_EDGE_TOL]
    counts = [0] * (len(cuts) + 1)
    for gx in glyph_xs:
        counts[sum(gx >= c for c in cuts)] += 1
    if len(counts) > 1 and counts[-1] == 0 and cuts[-1] >= right - RIGHT_EDGE_TOL:
        counts.pop()
    return counts


def compare_bars(label: list[int], pdf: list[int]) -> list[int] | None:
    """Indices (0-based) of bars whose counts differ, or None when the bar counts disagree (split unreliable)."""
    if len(label) != len(pdf):
        return None
    return [i for i, (a, b) in enumerate(zip(label, pdf)) if a != b]


def accidental_points(page) -> list[tuple[float, float]] | None:
    """(x, baseline y) of every accidental glyph on the page, or None when no known music font is present."""
    pts: list[tuple[float, float]] = []
    known = False
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                glyphs = ACCIDENTAL_GLYPHS.get(span["font"])
                if glyphs is None:
                    continue
                known = True
                pts += [(c["origin"][0], c["origin"][1]) for c in span["chars"] if c["c"] in glyphs]
    return pts if known else None


def vertical_segments(page) -> list[tuple[float, float, float]]:
    """(x, y0, y1) of thin vertical strokes (lines and thin rects), the same primitives staves_and_systems reads."""
    vs: list[tuple[float, float, float]] = []
    max_h = PAGE_SPAN_FRACTION * page.rect.height   # page-border frames are not barlines
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.x - b.x) < 0.5 and BARLINE_MIN_HEIGHT < abs(a.y - b.y) < max_h:
                    vs.append((a.x, min(a.y, b.y), max(a.y, b.y)))
            elif it[0] == "re":
                r = it[1]
                if r.width < BARLINE_MAX_WIDTH and BARLINE_MIN_HEIGHT < r.height < max_h:
                    vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
    return vs


def staff_barlines(vs: list[tuple[float, float, float]], staff: list[float]) -> list[float]:
    """Merged x's of vertical strokes spanning the five lines of one staff (stems are shorter than the staff)."""
    top, bottom = staff[0], staff[4]
    return merge_barlines([x for x, y0, y1 in vs if y0 <= top + BARLINE_SPAN_TOL and y1 >= bottom - BARLINE_SPAN_TOL])


def consensus_barlines(per_staff: list[list[float]]) -> list[float]:
    """Barline x's present on at least CONSENSUS_FRAC of a system's staves. Stems taller than the staff pass the
    per-staff test but never line up across staves; real barlines do. A one-staff system keeps its x's unfiltered
    (shortcut: stems there can add false bars, which only turns the per-bar split off via a bar-count mismatch)."""
    if len(per_staff) == 1:
        return per_staff[0]
    cands = merge_barlines([x for xs in per_staff for x in xs])
    need = CONSENSUS_FRAC * len(per_staff)
    return [c for c in cands if sum(any(abs(c - x) <= CONSENSUS_TOL for x in xs) for xs in per_staff) >= need]


def _self_check() -> None:
    assert label_bar_counts(["clef.G-L2", "accidental.flat-L3", "accidental.flat-S1", "note.quarter-S0", "barline-L1",
                             "accidental.sharp-L2", "note.half-L1", "barline-L1"]) == [2, 1]
    assert label_bar_counts(["note.quarter-S0", "barline-L1", "accidental.natural-S1", "note.half-L1"]) == [0, 1]
    assert merge_barlines([100.0, 102.0, 150.0, 150.2]) == [100.0, 150.0]
    # glyphs at 10 (header) and 60 sit in bar 1 and 2; barlines at the left edge, 50 and the staff end.
    assert pdf_bar_counts([10.0, 11.0, 60.0], [5.0, 50.0, 100.0], 5.0, 101.0) == [2, 1]
    assert compare_bars([2, 1], [2, 2]) == [1] and compare_bars([2], [2, 1]) is None
    assert consensus_barlines([[10.0, 50.0], [10.2, 80.0], [9.8, 50.5]]) == [9.8, 50.0]
    print("accid_check self-check ok")


if __name__ == "__main__":
    _self_check()
