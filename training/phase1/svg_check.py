"""Automatic label check of every Phase 1 render against what Verovio actually drew (PIYA-106, ml-cv-lead cond. c).

Why: G1 validated the converter on CPM gold only (the `primus` dialect). The SATB renders use the `verovio`
dialect, continuation headers, courtesy signatures, treble-8vb tenors and constructed events that CPM never had.
Instead of trusting the converter, this reads Verovio's SVG (with `svgHtml5`, every group carries its MEI
`data-id` and `class`) and compares, per (page, system, staff):

* ordered sequences with vertical staff positions: clefs, accidentals (key signatures, inline, courtesy,
  cancelling naturals; glyph kind from the SMuFL code point, so it is font independent) and noteheads;
* the ordered kinds of rest glyph (SMuFL code point -> agnostic duration name), so a whole-bar rest drawn as a
  breve rest cannot pass with a whole-rest label (a bare count let that through for 7,388 Palestrina rests);
* counts: rests (incl. whole-bar rests), multirests and their digits, meter glyphs, barlines, augmentation dots,
  tie ends, fermatas and beam groups;
* the measures each system holds, against the planned measure -> system map.

A render with any mismatch fails and is quarantined by the caller. Positions are read from the glyph anchor,
which SMuFL puts on the staff position the glyph belongs to; staff position 0 is the bottom line (L1).
Lyrics, staff labels, titles, stems and ledger lines are drawn but carry no token and are not compared.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
MEI_NS = "{http://www.music-encoding.org/ns/mei}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

ACCID_CODES: dict[str, str] = {"E260": "flat", "E261": "natural", "E262": "sharp", "E263": "double_sharp",
                               "E264": "double_flat"}
# SMuFL rest code points -> the duration names the agnostic vocabulary uses (restMaxima/restLonga have no token).
REST_CODES: dict[str, str] = {"E4E0": "maxima", "E4E1": "longa", "E4E2": "double_whole", "E4E3": "whole",
                              "E4E4": "half", "E4E5": "quarter", "E4E6": "eighth", "E4E7": "sixteenth",
                              "E4E8": "thirty_second", "E4E9": "sixty_fourth", "E4EA": "hundred_twenty_eighth"}
STAFF_LINES = 5
TRANSLATE_RE = re.compile(r"translate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)\s*\)")
TOKEN_RE = re.compile(r"^(.*)-([LS]-?\d+)$")   # 'note.quarter-L-1' -> ('note.quarter', 'L-1')
PATH_HLINE_RE =re.compile(r"M\s*(-?[\d.]+)[ ,]+(-?[\d.]+)\s*L\s*(-?[\d.]+)[ ,]+(-?[\d.]+)")
COUNT_FIELDS: tuple[str, ...] = ("rests", "multirests", "multirest_digits", "meter_glyphs", "barlines", "dots",
                                 "ties", "fermatas", "beams")
SEQUENCE_FIELDS: tuple[str, ...] = ("clefs", "accidentals", "notes", "rest_kinds")


@dataclass
class StaffView:
    """What one staff of one system carries, either as drawn (SVG) or as labelled (tokens)."""

    clefs: list[int] = field(default_factory=list)
    accidentals: list[tuple[str, int]] = field(default_factory=list)
    notes: list[int] = field(default_factory=list)
    rest_kinds: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {k: 0 for k in COUNT_FIELDS})


@dataclass
class StaffBox:
    """Staff geometry in SVG user units (before the page-margin translate)."""

    top: float
    bottom: float
    left: float
    right: float


@dataclass
class DrawnSystem:
    measure_ids: list[str]
    staves: dict[str, StaffView]
    boxes: dict[str, StaffBox]


@dataclass
class PageGeometry:
    """User units -> output pixels: px = (u + margin) * scale."""

    scale: float
    margin_x: float
    margin_y: float
    width_px: float
    height_px: float


@dataclass
class MeiIndex:
    """Ids from the rendered MEI, so SVG control events (ties, fermatas) can be put on their staff."""

    staff_of: dict[str, str]
    ties: dict[str, tuple[str, str]]
    fermatas: dict[str, str]
    measure_ids: list[str]


def _cls(el: ET.Element) -> str:
    return el.attrib.get("class", "").split(" ")[0]


def _code(use: ET.Element) -> str:
    return use.attrib.get(XLINK_HREF, "#")[1:5]


def _use_y(use: ET.Element) -> float:
    m = TRANSLATE_RE.search(use.attrib.get("transform", ""))
    if m is None:
        raise ValueError(f"glyph without translate: {use.attrib}")
    return float(m.group(2))


def token_position(suffix: str) -> int:
    """'L1' -> 0, 'S1' -> 1, 'L0' -> -2, 'L-1' -> -4 (inverse of music_to_agnostic.position_suffix)."""
    kind, n = suffix[0], int(suffix[1:])
    return 2 * (n - 1) if kind == "L" else 2 * n - 1


def index_mei(mei_path: Path) -> MeiIndex:
    root = ET.parse(mei_path).getroot()
    staff_of: dict[str, str] = {}
    for staff in root.iter(f"{MEI_NS}staff"):
        for el in staff.iter():
            if XML_ID in el.attrib:
                staff_of[el.attrib[XML_ID]] = staff.attrib.get("n", "")
    ties = {t.attrib[XML_ID]: (t.attrib.get("startid", "").lstrip("#"), t.attrib.get("endid", "").lstrip("#"))
            for t in root.iter(f"{MEI_NS}tie") if XML_ID in t.attrib}
    fermatas = {f.attrib[XML_ID]: f.attrib.get("startid", "").lstrip("#")
                for f in root.iter(f"{MEI_NS}fermata") if XML_ID in f.attrib}
    measure_ids = [m.attrib.get(XML_ID, "") for m in root.iter(f"{MEI_NS}measure")]
    return MeiIndex(staff_of=staff_of, ties=ties, fermatas=fermatas, measure_ids=measure_ids)


def page_geometry(root: ET.Element) -> PageGeometry:
    width_px = float(root.attrib["width"].removesuffix("px"))
    height_px = float(root.attrib["height"].removesuffix("px"))
    inner = next(e for e in root.iter(f"{SVG_NS}svg") if "definition-scale" in e.attrib.get("class", ""))
    view_w = float(inner.attrib["viewBox"].split()[2])
    margin = next(e for e in root.iter(f"{SVG_NS}g") if _cls(e) == "page-margin")
    m = TRANSLATE_RE.search(margin.attrib.get("transform", "translate(0,0)"))
    mx, my = (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)
    return PageGeometry(scale=width_px / view_w, margin_x=mx, margin_y=my, width_px=width_px, height_px=height_px)


def _staff_lines(staff: ET.Element) -> StaffBox:
    ys: list[float] = []
    xs: list[float] = []
    for path in staff.findall(f"{SVG_NS}path"):
        m = PATH_HLINE_RE.search(path.attrib.get("d", ""))
        if m and m.group(2) == m.group(4):
            ys.append(float(m.group(2)))
            xs += [float(m.group(1)), float(m.group(3))]
    if len(ys) != STAFF_LINES:
        raise ValueError(f"staff with {len(ys)} lines")
    return StaffBox(top=min(ys), bottom=max(ys), left=min(xs), right=max(xs))


def _read_staff(staff: ET.Element, view: StaffView, drawn_notes: set[str]) -> StaffBox:
    box = _staff_lines(staff)
    half = (box.bottom - box.top) / (2 * (STAFF_LINES - 1))

    def pos(use: ET.Element) -> int:
        return round((box.bottom - _use_y(use)) / half)

    def visit(el: ET.Element) -> None:
        c = _cls(el)
        if c == "clef":
            for use in el.findall(f"{SVG_NS}use"):
                view.clefs.append(pos(use))
            return
        if c in ("keyAccid", "accid"):
            for use in el.iter(f"{SVG_NS}use"):
                if _code(use) in ACCID_CODES:
                    view.accidentals.append((ACCID_CODES[_code(use)], pos(use)))
            return
        if c == "note":
            drawn_notes.add(el.attrib.get("data-id", ""))
            head = next((g for g in el.iter(f"{SVG_NS}g") if _cls(g) == "notehead"), None)
            use = head.find(f"{SVG_NS}use") if head is not None else None
            view.notes.append(pos(use) if use is not None else -999)
        elif c in ("rest", "mRest"):
            view.counts["rests"] += 1
            kinds = [REST_CODES[_code(u)] for u in el.iter(f"{SVG_NS}use") if _code(u) in REST_CODES]
            view.rest_kinds.append(kinds[0] if len(kinds) == 1 else f"unreadable:{len(kinds)}")
        elif c == "multiRest":
            view.counts["multirests"] += 1
        elif c == "multiRestNum":
            view.counts["multirest_digits"] += len(el.findall(f"{SVG_NS}use"))
            return
        elif c == "meterSig":
            view.counts["meter_glyphs"] += len(el.findall(f"{SVG_NS}use"))
            return
        elif c == "dots":
            view.counts["dots"] += len(el.findall(f"{SVG_NS}ellipse")) + len(el.findall(f"{SVG_NS}use"))
            return
        elif c == "beam":
            view.counts["beams"] += 1
        for child in el:
            visit(child)

    for child in staff:
        visit(child)
    return box


def read_page(svg_text: str, mei: MeiIndex) -> tuple[list[DrawnSystem], PageGeometry]:
    root = ET.fromstring(svg_text)
    geometry = page_geometry(root)
    systems: list[DrawnSystem] = []
    for sys_el in (e for e in root.iter(f"{SVG_NS}g") if _cls(e) == "system"):
        staves: dict[str, StaffView] = {}
        boxes: dict[str, StaffBox] = {}
        drawn_notes: set[str] = set()
        measure_ids: list[str] = []
        for measure in (e for e in sys_el.iter(f"{SVG_NS}g") if _cls(e) == "measure"):
            measure_ids.append(measure.attrib.get("data-id", ""))
            staff_ns: list[str] = []
            for staff in (e for e in measure if _cls(e) == "staff"):
                n = staff.attrib.get("data-n", "")
                staff_ns.append(n)
                box = _read_staff(staff, staves.setdefault(n, StaffView()), drawn_notes)
                old = boxes.get(n)
                boxes[n] = box if old is None else StaffBox(min(old.top, box.top), max(old.bottom, box.bottom),
                                                            min(old.left, box.left), max(old.right, box.right))
            barline = next((e for e in measure if _cls(e) == "barLine"), None)
            if barline is not None and len(barline) > 0:
                for n in staff_ns:
                    staves[n].counts["barlines"] += 1
        seen_ties: set[str] = set()
        for el in sys_el.iter(f"{SVG_NS}g"):
            c, data_id = _cls(el), el.attrib.get("data-id", "")
            if c == "tie" and data_id not in seen_ties:
                seen_ties.add(data_id)
                if data_id not in mei.ties:
                    raise ValueError(f"tie {data_id} not in MEI")
                for end in mei.ties[data_id]:
                    if end in drawn_notes:
                        staves[mei.staff_of[end]].counts["ties"] += 1
            elif c == "fermata":
                target = mei.fermatas.get(data_id)
                if target is None or target not in mei.staff_of:
                    raise ValueError(f"fermata {data_id} not mapped to a staff")
                staves[mei.staff_of[target]].counts["fermatas"] += 1
        systems.append(DrawnSystem(measure_ids=measure_ids, staves=staves, boxes=boxes))
    return systems, geometry


def label_view(tokens: list[str]) -> StaffView:
    view = StaffView()
    for tok in tokens:
        m = TOKEN_RE.match(tok)
        if m is None:
            raise ValueError(f"token without a position suffix: {tok}")
        name, suffix = m.group(1), m.group(2)
        if tok.startswith("clef."):
            view.clefs.append(2 * (int(tok.split("-L")[1]) - 1))
        elif name.startswith("accidental."):
            view.accidentals.append((name.split(".", 1)[1], token_position(suffix)))
        elif name.startswith(("note.", "gracenote.")):
            view.notes.append(token_position(suffix))
        elif name.startswith("rest."):
            view.counts["rests"] += 1
            view.rest_kinds.append(name.split(".", 1)[1])
        elif name == "multirest":
            view.counts["multirests"] += 1
        elif name.startswith("digit.") and suffix == "S5":
            view.counts["multirest_digits"] += len(name.split(".", 1)[1])
        elif name.startswith("digit."):
            view.counts["meter_glyphs"] += len(name.split(".", 1)[1])
        elif name.startswith("metersign."):
            view.counts["meter_glyphs"] += 1
        elif name == "barline":
            view.counts["barlines"] += 1
        elif name == "dot":
            view.counts["dots"] += 1
        elif name in ("slur.start", "slur.end"):
            view.counts["ties"] += 1
        elif name.startswith("fermata."):
            view.counts["fermatas"] += 1
        if "beamedRight" in name:
            view.counts["beams"] += 1
    return view


def compare(drawn: StaffView, label: StaffView) -> list[str]:
    """Human-readable differences; empty when the labels match the drawing."""
    out: list[str] = []
    for name in SEQUENCE_FIELDS:
        d, lab = getattr(drawn, name), getattr(label, name)
        if d != lab:
            out.append(f"{name}: drawn {d} label {lab}")
    for name in COUNT_FIELDS:
        if drawn.counts[name] != label.counts[name]:
            out.append(f"{name}: drawn {drawn.counts[name]} label {label.counts[name]}")
    return out
