"""MEI -> Camera-PrIMuS agnostic tokens, per staff and per system (PIYA-106 Phase 1 step 1).

The Phase 1 data engine renders SATB scores with Verovio and needs a label for every rendered staff strip in the
exact vocabulary the CRNN reads (`note.quarter-L4`, `accidental.sharp-S3`, ...). music21 10.5 drops key
signatures and multirests when it reads MEI, so this reads MEI XML directly.

Gate G1 (docs/decisions/piya-106-ser-15-plan.md, Phase 1): at least 99% token agreement with Camera-PrIMuS's gold
`.agnostic` on the local CPM samples, checked by `training/g1_converter_gate.py`. The rules below reproduce how
PrIMuS's own engine wrote those labels, so they are CPM conventions, not general engraving law:

* An MEI note without `<accid>` takes its alteration from the key signature only. PrIMuS MEI does not carry an
  accidental through the bar (its `.semantic` gives B-flat for an unmarked B after a B-natural in a flat key).
  The shown accidental is then re-engraved from pitch: shown when the alteration differs from what the bar has
  established so far for that step and octave.
* A tie is written `slur.end` before the continuation and `slur.start` after the note that starts it, both at
  the note's position. CPM has no phrase slurs.
* Beamed notes use `beamedRight/Both/Left{n}` with the note's own flag count, so a dotted eighth + sixteenth
  beam is `beamedRight1 ... beamedLeft2`.
* A multirest count is written digit by digit above the staff (`digit.2-S5 digit.4-S5 multirest-L3`); a
  time-signature numeral is one token (`digit.12-L4`).

Same-stem chords (divisi arm, Verovio dialect only) follow `_Reader.chord`: the lowest head is a normal `note.*`
token and each higher head a `chordnote-<pos>`; CPM has no chords, so G1 does not cover this rule (G1b does).

Two-layer bars (divisi A7, Verovio dialect only, gate G1c in `tests/test_g1c_layers.py`): the bar body opens with
`layer.split`, events of both layers follow in onset order (layer 1 first at a shared onset), and a layer-2 head or
rest takes the fused `.l2` class (`note.eighth.l2-L2`, `rest.quarter.l2-L3`, nominal rest positions as in layer 1).
A layer of invisible spacers only is not a layer; three drawn layers are refused.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Literal

MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

STEPS = "cdefgab"
DIATONIC_PER_OCTAVE = 7

# Staff position p: bottom line L1 = 0, space above it S1 = 1, L2 = 2, ... ; below the staff S0 = -1, L0 = -2.
# Reference pitch per clef shape as (diatonic index of the pitch, name of the pitch the clef line carries).
CLEF_REFERENCE_DIATONIC: dict[str, int] = {
    "G": 4 * DIATONIC_PER_OCTAVE + STEPS.index("g"),   # G4 on the clef line
    "C": 4 * DIATONIC_PER_OCTAVE + STEPS.index("c"),   # C4
    "F": 3 * DIATONIC_PER_OCTAVE + STEPS.index("f"),   # F3
}

SHARP_ORDER = "fcgdaeb"
FLAT_ORDER = "beadgcf"

# Key-signature glyph positions per clef, full order of 7. Every prefix actually used by CPM gold was checked
# against it (one placement per (clef, key), no variants); entries past the longest CPM prefix are completed by
# the standard alternating 4th/5th pattern and are UNVALIDATED:
#   G2 sharps 7/7, flats 6/7; G1 3/2; F4 5/4; F3 2/1; C1 5/4; C2 3/1; C3 3/4; C4 3/3.
KEYSIG_POSITIONS: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "clef.G-L2": ((8, 5, 9, 6, 3, 7, 4), (4, 7, 3, 6, 2, 5, 1)),
    "clef.G-L1": ((6, 3, 7, 4, 1, 5, 2), (2, 5, 1, 4, 0, 3, -1)),
    "clef.F-L4": ((6, 3, 7, 4, 1, 5, 2), (2, 5, 1, 4, 0, 3, -1)),
    "clef.F-L3": ((4, 1, 5, 2, 6, 3, 7), (7, 3, 6, 2, 5, 1, 4)),
    "clef.C-L1": ((3, 0, 4, 1, 5, 2, 6), (6, 2, 5, 1, 4, 0, 3)),
    "clef.C-L2": ((5, 2, 6, 3, 7, 4, 1), (8, 4, 7, 3, 6, 2, 5)),
    "clef.C-L3": ((7, 4, 8, 5, 2, 6, 3), (3, 6, 2, 5, 1, 4, 0)),
    "clef.C-L4": ((2, 6, 3, 7, 4, 8, 5), (5, 8, 4, 7, 3, 6, 2)),
}

DUR_NAME: dict[str, str] = {
    "breve": "double_whole", "1": "whole", "2": "half", "4": "quarter", "8": "eighth", "16": "sixteenth",
    "32": "thirty_second", "64": "sixty_fourth", "128": "hundred_twenty_eighth",
}
FLAG_COUNT: dict[str, int] = {"breve": 0, "1": 0, "2": 0, "4": 0, "8": 1, "16": 2, "32": 3, "64": 4, "128": 5}

ACCID_ALTER: dict[str, int] = {"s": 1, "f": -1, "n": 0, "ss": 2, "x": 2, "ff": -2}
ALTER_GLYPH: dict[int, str] = {1: "sharp", -1: "flat", 0: "natural", 2: "double_sharp", -2: "double_flat"}

REST_POSITION: dict[str, int] = {"breve": 4, "1": 6, "2": 4}   # whole hangs from L4, half sits on L3
DEFAULT_REST_POSITION = 4                                     # L3 for quarter and shorter
MULTIREST_POSITION = 4                                        # L3
MULTIREST_DIGIT_POSITION = 9                                  # S5, above the staff
METER_SYM_POSITION = 4                                        # L3
METER_COUNT_POSITION = 6                                      # L4
METER_UNIT_POSITION = 2                                       # L2
BARLINE_POSITION = 0                                          # L1
# Verovio 6.3 draws a whole-bar rest (<mRest>) as a breve rest once the bar holds two whole notes or more (4/2,
# 2/1, 8/4, 9/4 ...; probed over meters up to 8/2, it never uses a longa rest), else as a whole rest.
MREST_BREVE_FROM_WHOLES = Fraction(2)
FERMATA_ABOVE_POSITION = 11                                   # S6 in CPM gold whatever the note height
METER_SYM_GLYPH: dict[str, str] = {"common": "C", "cut": "C/"}
BARLINES_WRITTEN: frozenset[str] = frozenset({"single", "dbl", "end", "rptend", "rptstart", "rptboth", "dashed"})


class ConversionError(ValueError):
    """The MEI uses something this converter cannot label; the caller must drop the sample, not guess."""


def position_suffix(p: int) -> str:
    """Staff position -> agnostic suffix: 0 -> 'L1', 1 -> 'S1', -1 -> 'S0', -2 -> 'L0', -4 -> 'L-1'."""
    return f"L{p // 2 + 1}" if p % 2 == 0 else f"S{(p - 1) // 2 + 1}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass
class StaffState:
    """What a reader carries along one staff: clef, key and meter currently in force."""

    clef_shape: str = "G"
    clef_line: int = 2
    key_sig: str = "0"
    meter: tuple[str, ...] = ()
    # Bar length in whole notes, kept apart from `meter` because a signature drawn as a symbol (C) can still
    # carry count/unit, and the whole-bar rest glyph follows the length, not the symbol. None: not numeric.
    bar_wholes: Fraction | None = Fraction(1)
    # Diatonic steps from sounding to drawn position. A treble-8vb clef (clef.dis="8" place below) is +7: Verovio
    # keeps @oct as the sounding octave and draws C4 where a plain treble clef draws C5. The token stays the drawn
    # clef (clef.G-L2); Stage 3's tenor rule adds the octave back.
    clef_dis: int = 0

    @property
    def clef_token(self) -> str:
        return f"clef.{self.clef_shape}-L{self.clef_line}"

    def position(self, pname: str, octave: int) -> int:
        if self.clef_shape not in CLEF_REFERENCE_DIATONIC:
            raise ConversionError(f"clef shape {self.clef_shape!r}")
        reference = 2 * (self.clef_line - 1)
        return (reference + octave * DIATONIC_PER_OCTAVE + STEPS.index(pname)
                - CLEF_REFERENCE_DIATONIC[self.clef_shape] + self.clef_dis)

    def key_alter(self, pname: str) -> int:
        count, kind = _parse_key_sig(self.key_sig)
        order = SHARP_ORDER if kind == "s" else FLAT_ORDER
        if pname in order[:count]:
            return 1 if kind == "s" else -1
        return 0

    def header(self, with_meter: bool) -> list[str]:
        """Clef + key signature (+ meter): a first system carries all three, a continuation system no meter."""
        tokens = [self.clef_token]
        tokens += _key_sig_tokens(self.clef_token, self.key_sig)
        if with_meter:
            tokens += _meter_tokens(self.meter)
        return tokens


def _parse_key_sig(key_sig: str) -> tuple[int, str]:
    if key_sig in ("0", "", "none"):
        return 0, "s"
    count, kind = int(key_sig[:-1]), key_sig[-1]
    if kind not in "sf" or not 0 <= count <= 7:
        raise ConversionError(f"key.sig {key_sig!r}")
    return count, kind


def _key_sig_tokens(clef_token: str, key_sig: str) -> list[str]:
    count, kind = _parse_key_sig(key_sig)
    if count == 0:
        return []
    if clef_token not in KEYSIG_POSITIONS:
        raise ConversionError(f"no key-signature table for {clef_token}")
    sharps, flats = KEYSIG_POSITIONS[clef_token]
    glyph, positions = ("sharp", sharps) if kind == "s" else ("flat", flats)
    return [f"accidental.{glyph}-{position_suffix(p)}" for p in positions[:count]]


def _key_change_tokens(clef_token: str, old_key: str, new_key: str, dialect: Dialect) -> list[str]:
    """Glyphs drawn for a key change.

    Verovio 6.3 (no @cancelaccid) draws only the new signature, except that a change to no key would draw
    nothing, so it draws naturals on the old signature's positions instead (checked by probe on 2s->0, 2s->1s,
    1f->3f, 3f->1s, 0->2f, mid-system and at a break). PrIMuS behaviour is left as it was: CPM has no such case.
    """
    old_count, old_kind = _parse_key_sig(old_key)
    new_count, _ = _parse_key_sig(new_key)
    if dialect == "verovio" and new_count == 0 and old_count > 0:
        if clef_token not in KEYSIG_POSITIONS:
            raise ConversionError(f"no key-signature table for {clef_token}")
        sharps, flats = KEYSIG_POSITIONS[clef_token]
        positions = sharps if old_kind == "s" else flats
        return [f"accidental.natural-{position_suffix(p)}" for p in positions[:old_count]]
    return _key_sig_tokens(clef_token, new_key)


def _meter_tokens(meter: tuple[str, ...]) -> list[str]:
    if not meter:
        return []
    if meter[0] == "sym":
        return [f"metersign.{METER_SYM_GLYPH[meter[1]]}-{position_suffix(METER_SYM_POSITION)}"]
    count, unit = meter[1], meter[2]
    if not (count.isdigit() and unit.isdigit()):
        raise ConversionError(f"meter {count}/{unit}")
    return [f"digit.{count}-{position_suffix(METER_COUNT_POSITION)}",
            f"digit.{unit}-{position_suffix(METER_UNIT_POSITION)}"]


def _meter_from(el: ET.Element) -> tuple[str, ...] | None:
    """Meter declared on a scoreDef/staffDef (attributes, or a <meterSig> child as newer Verovio writes)."""
    attrs = dict(el.attrib)
    child = el.find(f"{{{MEI_NS}}}meterSig")
    if child is not None:
        attrs.update({f"meter.{k}": v for k, v in child.attrib.items() if k in ("count", "unit", "sym")})
    if "meter.sym" in attrs and attrs["meter.sym"] in METER_SYM_GLYPH:
        return ("sym", attrs["meter.sym"])
    if "meter.count" in attrs and "meter.unit" in attrs:
        return ("num", attrs["meter.count"], attrs["meter.unit"])
    return None


def _bar_wholes(count: str | None, unit: str | None, sym: str | None) -> Fraction | None:
    """Bar length in whole notes; C and cut C without count/unit are one whole note, as Verovio assumes."""
    if count is not None and unit is not None:
        return Fraction(int(count), int(unit)) if count.isdigit() and unit.isdigit() and int(unit) else None
    return Fraction(1) if sym in METER_SYM_GLYPH else None


def _bar_wholes_from(el: ET.Element) -> Fraction | None:
    child = el.find(f"{{{MEI_NS}}}meterSig")
    if child is not None:
        return _bar_wholes(child.attrib.get("count"), child.attrib.get("unit"), child.attrib.get("sym"))
    return _bar_wholes(el.attrib.get("meter.count"), el.attrib.get("meter.unit"), el.attrib.get("meter.sym"))


def _key_from(el: ET.Element) -> str | None:
    if "key.sig" in el.attrib:
        return el.attrib["key.sig"]
    child = el.find(f"{{{MEI_NS}}}keySig")
    if child is not None and "sig" in child.attrib:
        return child.attrib["sig"]
    return None


CLEF_DIS_STEPS: dict[str, int] = {"8": DIATONIC_PER_OCTAVE, "15": 2 * DIATONIC_PER_OCTAVE}


def _clef_dis(dis: str | None, place: str | None) -> int:
    """Drawn-minus-sounding diatonic offset of an octave clef; 0 when the clef has no displacement."""
    if dis is None:
        return 0
    if dis not in CLEF_DIS_STEPS or place not in ("above", "below"):
        raise ConversionError(f"clef dis {dis!r} place {place!r}")
    return CLEF_DIS_STEPS[dis] if place == "below" else -CLEF_DIS_STEPS[dis]


def _clef_from(el: ET.Element) -> tuple[str, int, int] | None:
    """(shape, line, displacement offset) declared on a scoreDef/staffDef, as attributes or a <clef> child."""
    if "clef.shape" in el.attrib:
        return (el.attrib["clef.shape"], int(el.attrib["clef.line"]),
                _clef_dis(el.attrib.get("clef.dis"), el.attrib.get("clef.dis.place")))
    child = el.find(f"{{{MEI_NS}}}clef")
    if child is not None and "shape" in child.attrib:
        return (child.attrib["shape"], int(child.attrib["line"]),
                _clef_dis(child.attrib.get("dis"), child.attrib.get("dis.place")))
    return None


Dialect = Literal["primus", "verovio"]


@dataclass
class MeasureTokens:
    """One measure on one staff.

    `defs` holds tokens for a key/meter change (or, on the first measure, the whole header) written before the
    bar. `state_before` is the clef/key/meter in force as the bar starts, which is what a continuation system's
    header shows when the bar opens a new system.
    """

    defs: list[str]
    body: list[str]
    state_before: StaffState
    meter_change: bool
    system_start: bool

    @property
    def tokens(self) -> list[str]:
        return self.defs + self.body


@dataclass
class _Reader:
    """Walks one staff's layer events and writes agnostic tokens."""

    state: StaffState
    dialect: Dialect
    bar_alters: dict[tuple[str, int], int] = field(default_factory=dict)
    tie_alter: dict[tuple[str, int], int] = field(default_factory=dict)
    tie_starts: set[int] = field(default_factory=set)
    tie_ends: set[int] = field(default_factory=set)
    fermatas: set[int] = field(default_factory=set)
    out: list[str] = field(default_factory=list)
    # Two-layer bar (A7): each event's tokens go to `chunks` as (onset, layer, seq, tokens) instead of `out`, so the
    # caller can interleave both layers by onset. None: single-layer reading, tokens straight to `out`.
    layer: int = 1
    chunks: list[tuple[Fraction, int, int, list[str]]] | None = None
    time: Fraction = Fraction(0)

    def _length(self, el: ET.Element) -> Fraction:
        """Duration in whole notes of one layer event (grace notes take none)."""
        tag = _local(el.tag)
        if tag in ("mRest", "mSpace"):
            if self.state.bar_wholes is None:
                raise ConversionError(f"whole-bar event under meter {self.state.meter}")
            return self.state.bar_wholes
        if "grace" in el.attrib:
            return Fraction(0)
        dur = el.attrib.get("dur", "4")
        if dur not in DUR_NAME:
            raise ConversionError(f"{tag} dur {dur!r}")
        base = Fraction(2) if dur == "breve" else Fraction(1, int(dur))
        dots = int(el.attrib.get("dots", "0"))
        return base * (2 - Fraction(1, 2 ** dots))

    def _close_event(self, el: ET.Element, start: int) -> None:
        if self.chunks is None:
            return
        chunk = self.out[start:]
        del self.out[start:]
        if self.layer == 2:
            chunk = [_layer2_token(t) for t in chunk]
        self.chunks.append((self.time, self.layer, len(self.chunks), chunk))
        self.time += self._length(el)

    def _has_fermata(self, el: ET.Element) -> bool:
        return el.attrib.get("fermata") == "above" or id(el) in self.fermatas

    def _shown_accidental(self, el: ET.Element, pname: str, octave: int, ends_tie: bool,
                          starts_tie: bool) -> int | None:
        """Alteration whose glyph is drawn before this note, or None."""
        accid_el = el.find(f"{{{MEI_NS}}}accid")
        written = accid_el.attrib.get("accid") if accid_el is not None else el.attrib.get("accid")
        if written is not None and written not in ACCID_ALTER:
            raise ConversionError(f"accid {written!r}")
        if self.dialect == "verovio":
            # Verovio MEI separates drawn (@accid) from sounding-only (@accid.ges); it draws exactly @accid.
            return ACCID_ALTER[written] if written is not None else None
        key = (pname, octave)
        if ends_tie and key in self.tie_alter and written is None:
            alter, show = self.tie_alter[key], False
        else:
            alter = ACCID_ALTER[written] if written is not None else self.state.key_alter(pname)
            in_force = self.bar_alters.get(key, self.state.key_alter(pname))
            # A written accidental is drawn even when the key or bar already implies it (courtesy).
            show = written is not None or alter != in_force
        self.bar_alters[key] = alter
        if starts_tie:
            self.tie_alter[key] = alter
        else:
            self.tie_alter.pop(key, None)
        return alter if show else None

    def note(self, el: ET.Element, beam_role: str | None) -> None:
        pname, octave = el.attrib["pname"], int(el.attrib["oct"])
        dur = el.attrib.get("dur", "4")
        if dur not in DUR_NAME:
            raise ConversionError(f"note dur {dur!r}")
        p = self.state.position(pname, octave)
        ends_tie, starts_tie = id(el) in self.tie_ends, id(el) in self.tie_starts
        shown = self._shown_accidental(el, pname, octave, ends_tie, starts_tie)

        if self._has_fermata(el):
            self.out.append(f"fermata.above-{position_suffix(FERMATA_ABOVE_POSITION)}")
        if ends_tie:
            self.out.append(f"slur.end-{position_suffix(p)}")
        if shown is not None:
            self.out.append(f"accidental.{ALTER_GLYPH[shown]}-{position_suffix(p)}")
        kind = "gracenote" if "grace" in el.attrib else "note"
        shape = f"beamed{beam_role}{FLAG_COUNT[dur]}" if beam_role else DUR_NAME[dur]
        self.out.append(f"{kind}.{shape}-{position_suffix(p)}")
        self._dots(el, p)
        if starts_tie:
            self.out.append(f"slur.start-{position_suffix(p)}")

    def chord(self, el: ET.Element, beam_role: str | None) -> None:
        """Same-stem chord (divisi arm, chord-vocabulary plan 10.4, PHASE4_GT_FORMAT section 4).

        Order: fermata, slur.end per tied-in member, accidentals bottom to top, the lowest head as `note.*` (beam
        form), the others as `chordnote-<pos>` bottom to top, one dot per head per dot, slur.start per tied member.
        Verovio dialect only: PrIMuS MEI has no chords and its accidental re-engraving is not defined for them.
        """
        if self.dialect != "verovio":
            raise ConversionError("chord in primus dialect")
        if "grace" in el.attrib:
            raise ConversionError("grace chord")
        dur = el.attrib.get("dur", "4")
        if dur not in DUR_NAME:
            raise ConversionError(f"chord dur {dur!r}")
        members = el.findall(f"{{{MEI_NS}}}note")
        heads = sorted((self.state.position(n.attrib["pname"], int(n.attrib["oct"])), n) for n in members)
        if len(heads) < 2 or len({p for p, _ in heads}) != len(heads):
            raise ConversionError("chord without two distinct head positions")
        if self._has_fermata(el) or any(self._has_fermata(n) for _, n in heads):
            self.out.append(f"fermata.above-{position_suffix(FERMATA_ABOVE_POSITION)}")
        self.out += [f"slur.end-{position_suffix(p)}" for p, n in heads if id(n) in self.tie_ends]
        for p, n in heads:
            shown = self._shown_accidental(n, n.attrib["pname"], int(n.attrib["oct"]), id(n) in self.tie_ends,
                                           id(n) in self.tie_starts)
            if shown is not None:
                self.out.append(f"accidental.{ALTER_GLYPH[shown]}-{position_suffix(p)}")
        shape = f"beamed{beam_role}{FLAG_COUNT[dur]}" if beam_role else DUR_NAME[dur]
        self.out.append(f"note.{shape}-{position_suffix(heads[0][0])}")
        self.out += [f"chordnote-{position_suffix(p)}" for p, _ in heads[1:]]
        # A line head's dot goes to the space above, or below when a higher head's dot already sits there (a
        # dotted second); allocated top down, written bottom to top.
        dot_at: list[int] = []
        for p, _ in reversed(heads):
            d = p if p % 2 else p + 1
            dot_at.append(p - 1 if d in dot_at and p % 2 == 0 else d)
        n_dots = int(el.attrib.get("dots", "0"))
        self.out += [f"dot-{position_suffix(d)}" for d in sorted(dot_at) for _ in range(n_dots)]
        self.out += [f"slur.start-{position_suffix(p)}" for p, n in heads if id(n) in self.tie_starts]

    def rest(self, el: ET.Element) -> None:
        dur = el.attrib.get("dur", "4")
        if dur not in DUR_NAME:
            raise ConversionError(f"rest dur {dur!r}")
        p = REST_POSITION.get(dur, DEFAULT_REST_POSITION)
        if self._has_fermata(el):
            self.out.append(f"fermata.above-{position_suffix(FERMATA_ABOVE_POSITION)}")
        self.out.append(f"rest.{DUR_NAME[dur]}-{position_suffix(p)}")
        self._dots(el, p)

    def mrest(self) -> None:
        """A whole-bar rest. PrIMuS draws it as a whole rest; Verovio switches glyph with the bar length."""
        dur = "1"
        if self.dialect == "verovio":
            if self.state.bar_wholes is None:
                raise ConversionError(f"whole-bar rest under meter {self.state.meter}")
            if self.state.bar_wholes >= MREST_BREVE_FROM_WHOLES:
                dur = "breve"
        self.out.append(f"rest.{DUR_NAME[dur]}-{position_suffix(REST_POSITION[dur])}")

    def multirest(self, el: ET.Element) -> None:
        num = el.attrib.get("num", "1")
        self.out += [f"digit.{ch}-{position_suffix(MULTIREST_DIGIT_POSITION)}" for ch in num]
        self.out.append(f"multirest-{position_suffix(MULTIREST_POSITION)}")

    def _dots(self, el: ET.Element, p: int) -> None:
        dot_p = p + 1 if p % 2 == 0 else p
        self.out += [f"dot-{position_suffix(dot_p)}"] * int(el.attrib.get("dots", "0"))

    def clef(self, el: ET.Element) -> None:
        self.state.clef_shape, self.state.clef_line = el.attrib["shape"], int(el.attrib["line"])
        self.state.clef_dis = _clef_dis(el.attrib.get("dis"), el.attrib.get("dis.place"))
        self.out.append(self.state.clef_token)

    def inline_def(self, el: ET.Element) -> None:
        """A key or meter change drawn inside a bar."""
        if _local(el.tag) == "meterSig":
            sym = el.attrib.get("sym")
            meter: tuple[str, ...] = (("sym", sym) if sym in METER_SYM_GLYPH
                                      else ("num", el.attrib.get("count", ""), el.attrib.get("unit", "")))
            self.state.meter = meter
            self.state.bar_wholes = _bar_wholes(el.attrib.get("count"), el.attrib.get("unit"), sym)
            self.out += _meter_tokens(meter)
        else:
            old_key, self.state.key_sig = self.state.key_sig, el.attrib.get("sig", "0")
            self.out += _key_change_tokens(self.state.clef_token, old_key, self.state.key_sig, self.dialect)

    def walk(self, parent: ET.Element, beam_notes: list[ET.Element] | None = None) -> None:
        for el in parent:
            tag = _local(el.tag)
            start = len(self.out)
            if tag in ("note", "chord"):
                role = None
                if beam_notes and len(beam_notes) > 1 and el in beam_notes:
                    i = beam_notes.index(el)
                    role = "Right" if i == 0 else "Left" if i == len(beam_notes) - 1 else "Both"
                if tag == "chord":
                    self.chord(el, role)
                else:
                    self.note(el, role)
                self._close_event(el, start)
            elif tag == "rest":
                self.rest(el)
                self._close_event(el, start)
            elif tag == "multiRest":
                if self.chunks is not None:
                    raise ConversionError("multirest in a two-layer bar")
                self.multirest(el)
            elif tag == "mRest":
                self.mrest()
                self._close_event(el, start)
            elif tag in ("space", "mSpace") and self.chunks is not None:
                self.time += self._length(el)   # an invisible gap still moves the layer's onset
            elif tag in ("clef", "meterSig", "keySig") and self.chunks is not None:
                raise ConversionError(f"<{tag}> inside a two-layer bar")
            elif tag == "beam":
                # A chord is one beam event; its member notes are not.
                in_chord = {id(n) for c in el.iter(f"{{{MEI_NS}}}chord") for n in c.iter(f"{{{MEI_NS}}}note")}
                notes = [n for n in el.iter() if _local(n.tag) == "chord"
                         or (_local(n.tag) == "note" and id(n) not in in_chord)]
                self.walk(el, notes)
            elif tag == "clef":
                self.clef(el)
            elif tag in ("meterSig", "keySig"):
                self.inline_def(el)
            elif tag in LAYER_IGNORED:
                continue
            elif tag in ("tuplet", "bTrem", "fTrem"):
                raise ConversionError(f"unsupported layer element <{tag}>")
            else:
                raise ConversionError(f"unknown layer element <{tag}>")


# Drawn nothing the vocabulary can name (lyrics, articulation) or nothing at all (invisible spacers).
LAYER_IGNORED: frozenset[str] = frozenset({"accid", "dot", "verse", "syl", "artic", "space", "mSpace"})
DRAWN_EVENT_TAGS: frozenset[str] = frozenset({"note", "chord", "rest", "mRest", "multiRest"})

# = stage3_transcription.LAYER_SPLIT_TOKEN / LAYER2_TAG (not imported: stage3 pulls in torch; a test pins them equal).
LAYER_SPLIT = "layer.split"
LAYER2_TAG = ".l2"


def _layer2_token(token: str) -> str:
    """Layer-2 form of a token: heads and rests get the fused `.l2` class; chordnotes, dots, accidentals and slurs
    stay as they are and belong to the head they follow (A7 design section 4)."""
    if token.startswith("gracenote."):
        raise ConversionError("grace note in layer 2")
    if token.startswith(("note.", "rest.")):
        return token.replace("-", LAYER2_TAG + "-", 1)
    return token


def _draws(layer: ET.Element) -> bool:
    return any(_local(el.tag) in DRAWN_EVENT_TAGS for el in layer.iter())


def _apply_def(state: StaffState, el: ET.Element) -> tuple[bool, bool]:
    """Apply a scoreDef/staffDef to the state; return (key changed, meter changed)."""
    clef = _clef_from(el)
    if clef is not None:
        state.clef_shape, state.clef_line, state.clef_dis = clef
    key, meter = _key_from(el), _meter_from(el)
    key_changed = key is not None and key != state.key_sig
    if key is not None:
        state.key_sig = key
    meter_changed = meter is not None
    if meter is not None:
        state.meter = meter
        state.bar_wholes = _bar_wholes_from(el)
    return key_changed, meter_changed


def _staff_notes(score: ET.Element, staff_n: str) -> list[ET.Element]:
    notes: list[ET.Element] = []
    for measure in score.iter(f"{{{MEI_NS}}}measure"):
        for staff in measure.findall(f"{{{MEI_NS}}}staff"):
            if staff.attrib.get("n") == staff_n:
                notes += list(staff.iter(f"{{{MEI_NS}}}note"))
    return notes


def _same_pitch(a: ET.Element, b: ET.Element) -> bool:
    return (a.attrib.get("pname"), a.attrib.get("oct")) == (b.attrib.get("pname"), b.attrib.get("oct"))


def _tie_pairs(score: ET.Element, notes: list[ET.Element]) -> tuple[set[int], set[int]]:
    """Element ids of notes that start / end a drawable tie on this staff.

    A tie is drawn only between same-pitch notes. PrIMuS has a few `tie="i"` notes whose next note is a
    different pitch; no curve is drawn there and gold writes no slur tokens. Verovio MEI writes ties as
    `<tie startid endid>` control events instead of `@tie`.
    """
    starts: set[int] = set()
    ends: set[int] = set()
    plain = [n for n in notes if "grace" not in n.attrib]
    for a, b in zip(plain, plain[1:]):
        # A chain broken upstream (B tied to A tied to A) is not labelled past the break, matching CPM gold.
        chain_ok = a.attrib.get("tie") == "i" or id(a) in ends
        if a.attrib.get("tie") in ("i", "m") and b.attrib.get("tie") in ("m", "t") and _same_pitch(a, b) and chain_ok:
            starts.add(id(a))
            ends.add(id(b))
    by_id = {n.attrib[XML_ID]: n for n in notes if XML_ID in n.attrib}
    for tie in score.iter(f"{{{MEI_NS}}}tie"):
        a = by_id.get(tie.attrib.get("startid", "").lstrip("#"))
        b = by_id.get(tie.attrib.get("endid", "").lstrip("#"))
        if a is not None and b is not None and _same_pitch(a, b):
            starts.add(id(a))
            ends.add(id(b))
    return starts, ends


def _fermata_ids(score: ET.Element, staff_n: str) -> set[int]:
    """Notes/rests carrying a `<fermata startid>` control event placed above (the vocabulary has no below)."""
    events: dict[str, ET.Element] = {}
    for measure in score.iter(f"{{{MEI_NS}}}measure"):
        for staff in measure.findall(f"{{{MEI_NS}}}staff"):
            if staff.attrib.get("n") == staff_n:
                for el in staff.iter():
                    if _local(el.tag) in ("note", "rest", "chord") and XML_ID in el.attrib:
                        events[el.attrib[XML_ID]] = el
    out: set[int] = set()
    for fermata in score.iter(f"{{{MEI_NS}}}fermata"):
        target = events.get(fermata.attrib.get("startid", "").lstrip("#"))
        if target is not None and fermata.attrib.get("place", "above") == "above":
            out.add(id(target))
    return out


def convert_staff(mei_path: Path, staff_n: str = "1", dialect: Dialect = "primus") -> list[MeasureTokens]:
    """Agnostic tokens per measure for one staff of an MEI file.

    `dialect` says how accidentals are encoded: "primus" (CPM/PrIMuS MEI 4, only some drawn accidentals are
    encoded, so they are re-engraved from pitch) or "verovio" (MEI exported by Verovio, where @accid is exactly
    what is drawn). Pass it explicitly: guessing it from the file is unreliable on pieces with no accidentals.
    """
    root = ET.parse(mei_path).getroot()
    score = root.find(f".//{{{MEI_NS}}}score")
    if score is None:
        raise ConversionError("no <score>")
    state = StaffState()
    measures: list[MeasureTokens] = []
    defs: list[str] = []
    meter_change = False
    system_start = True
    tie_carry: dict[tuple[str, int], int] = {}
    tie_starts, tie_ends = _tie_pairs(score, _staff_notes(score, staff_n))
    fermatas = _fermata_ids(score, staff_n)
    first_def = True
    for el in score.iter():
        tag = _local(el.tag)
        if tag in ("sb", "pb"):
            system_start = True
        elif tag == "scoreDef":
            old_key = state.key_sig
            key_changed, meter_changed = _apply_def(state, el)
            for staff_def in el.iter(f"{{{MEI_NS}}}staffDef"):
                if staff_def.attrib.get("n") == staff_n:
                    k2, m2 = _apply_def(state, staff_def)
                    key_changed, meter_changed = key_changed or k2, meter_changed or m2
            if first_def:
                defs += state.header(with_meter=True)
                meter_change = bool(state.meter)
                first_def = False
            else:
                if key_changed:
                    defs += _key_change_tokens(state.clef_token, old_key, state.key_sig, dialect)
                if meter_changed:
                    defs += _meter_tokens(state.meter)
                    meter_change = True
        elif tag == "measure":
            staff = next((s for s in el.findall(f"{{{MEI_NS}}}staff") if s.attrib.get("n") == staff_n), None)
            if staff is None:
                raise ConversionError(f"measure without staff {staff_n}")
            layers = staff.findall(f"{{{MEI_NS}}}layer")
            # PrIMuS never has two layers; in Verovio MEI a layer of invisible spacers only draws nothing.
            drawn = layers if dialect == "primus" else [layer for layer in layers if _draws(layer)] or layers[:1]
            if len(drawn) != 1 and (dialect == "primus" or len(drawn) != 2):
                raise ConversionError(f"{len(drawn)} layers in a measure")
            state_before = StaffState(**vars(state))
            body: list[str] = []
            # A tie across the barline keeps its alteration; everything else the bar established is forgotten.
            if len(drawn) == 1:
                reader = _Reader(state=state, dialect=dialect, tie_alter=tie_carry, tie_starts=tie_starts,
                                 tie_ends=tie_ends, fermatas=fermatas, out=body)
                reader.walk(drawn[0])
            else:
                # Two-layer bar (A7 G1c): events in drawn-x order = onset order, layer 1 first at a shared onset.
                chunks: list[tuple[Fraction, int, int, list[str]]] = []
                for k, layer in enumerate(sorted(drawn, key=lambda ly: int(ly.attrib.get("n", "1"))), start=1):
                    _Reader(state=state, dialect=dialect, tie_alter=tie_carry, tie_starts=tie_starts,
                            tie_ends=tie_ends, fermatas=fermatas, layer=k, chunks=chunks).walk(layer)
                body.append(LAYER_SPLIT)
                body += [t for *_, chunk in sorted(chunks, key=lambda c: c[:3]) for t in chunk]
            right = el.attrib.get("right", "single")
            if right in BARLINES_WRITTEN:
                body.append(f"barline-{position_suffix(BARLINE_POSITION)}")
            elif right != "invis":
                raise ConversionError(f"measure@right {right!r}")
            measures.append(MeasureTokens(defs=defs, body=body, state_before=state_before,
                                          meter_change=meter_change, system_start=system_start))
            defs, meter_change, system_start = [], False, False
    if not measures:
        raise ConversionError("no measures")
    if defs:
        measures[-1].body += defs
    return measures


def convert_file(mei_path: Path, staff_n: str = "1", dialect: Dialect = "primus") -> list[str]:
    """Whole-staff agnostic token stream (one CPM incipit = one line)."""
    return [t for m in convert_staff(mei_path, staff_n, dialect) for t in m.tokens]


def split_systems(measures: list[MeasureTokens]) -> list[list[str]]:
    """Token stream per system, cut at the encoded system/page breaks.

    A continuation system opens with clef + key and no meter, as engraved scores do; a meter change that falls
    on the break is still written. A key or meter change on the break is also drawn as a courtesy signature after
    the last barline of the previous system (Verovio 6.3 always does this, checked per render by
    `training/phase1/svg_check.py`), so the change tokens are appended there as well.
    """
    systems: list[list[str]] = []
    for i, m in enumerate(measures):
        if i == 0:
            systems.append(list(m.tokens))
            continue
        if m.system_start:
            systems[-1] += m.defs
            header = m.state_before.header(with_meter=False)
            if m.meter_change:
                header += _meter_tokens(m.state_before.meter)
            systems.append(header + m.body)
        else:
            systems[-1] += m.tokens
    return systems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mei", type=Path)
    parser.add_argument("--staff", default="1")
    args = parser.parse_args()
    try:
        print("\t".join(convert_file(args.mei, args.staff)))
    except ConversionError as exc:
        print(f"cannot convert: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
