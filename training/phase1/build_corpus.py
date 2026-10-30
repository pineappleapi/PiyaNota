"""Phase 1 step 2: choral corpus -> layout-ready Verovio MEI, one file per piece (PIYA-106).

Why this exists: the CRNN only ever saw Camera-PrIMuS single-staff incipits. Phase 1 renders real four-part
choral music in the SATB open-score layout our users photograph, so labels must come from the same MEI that
Verovio draws. Each piece goes music21 -> MusicXML -> Verovio MEI, then gets its system/page breaks and the
constructed events written into the MEI itself, so the measure -> system map is known exactly.

Decisions, all logged per piece in `corpus_log.json`:
* Only pieces with exactly 4 parts in S, A, T, B order (by name, else by mean pitch) are kept.
* Clefs are normalised to treble / treble / treble-8vb / bass (the only clefs Stage 3 supports; no C clefs).
  A piece whose voice would sit more than MAX_LEDGER_POSITIONS outside the staff under that clef is excluded.
* Constructed events (ml-cv-lead 6b: real dev GT has no meter change or multirest; key changes are rare in
  the corpus): a key change done as a real modulation (the rest of the piece is transposed so the drawn
  accidentals stay musical), a meter change between two signatures of equal bar length (so bar contents stay
  valid), and a full-choir multirest measure. Each is placed on a system break or inside a system at random.
* Source chords, tuplets, tremolos and multi-layer staves are refused; the piece is skipped (the base vocabulary has
  no chord, docs/decisions/piya-106-ser-15-plan.md Phase 1 step 2).
* `--divisi` (divisi arm, docs/decisions/piya-106-divisi-a6-design.md section 4, A6 mix) builds `<piece>__divisi`
  copies with same-stem chords injected from a separate RNG (`--divisi-seed`); without it the output is
  byte-identical to before.

Usage: python training/phase1/build_corpus.py --out D:/PiyaNota-training/data/phase1_renders [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import math
import random
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import music21
import verovio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from music_to_agnostic import MEI_NS, XML_ID, ConversionError, convert_staff, split_systems  # noqa: E402

ET.register_namespace("", MEI_NS)
ET.register_namespace("xml", "http://www.w3.org/XML/1998/namespace")

VOICES: tuple[str, ...] = ("Soprano", "Alto", "Tenor", "Bass")
VOICE_INITIAL: tuple[str, ...] = ("s", "a", "t", "b")
NORMALISED_CLEFS: tuple[type[music21.clef.Clef], ...] = (
    music21.clef.TrebleClef, music21.clef.TrebleClef, music21.clef.Treble8vbClef, music21.clef.BassClef)
# Drawn staff position of the lowest / highest note allowed: L-3 (4 ledger lines below) .. L9 (4 above).
MIN_POSITION = -6
MAX_POSITION = 16
MEASURES_PER_SYSTEM: tuple[int, ...] = (4, 5)
SYSTEMS_PER_PAGE = 3
MAX_KEY_FIFTHS = 5            # keep constructed keys within 5 sharps/flats, like real choral scores
MAX_TRANSPOSE_SEMITONES = 5   # a modulation further than a fourth drags voices out of range
P_KEY_CHANGE = 0.35
P_METER_CHANGE = 0.35
P_METER_REVERT = 0.5
P_MULTIREST = 0.3
P_AT_BREAK = 0.5
REPEAT_BARLINES: frozenset[str] = frozenset({"rptstart", "rptend", "rptboth"})
MULTIREST_LENGTHS: tuple[int, ...] = (2, 3, 4, 5, 6, 8, 12, 16)
# Meters of equal bar length: swapping within a family keeps every bar's contents valid.
METER_FAMILIES: tuple[tuple[tuple[str, ...], ...], ...] = (
    (("num", "4", "4"), ("sym", "common"), ("num", "2", "2"), ("sym", "cut")),
    (("num", "3", "4"), ("num", "6", "8")),
    (("num", "3", "2"), ("num", "6", "4")),
    (("num", "4", "2"), ("num", "2", "1")),
    (("num", "2", "4"), ("num", "4", "8")),
)
# Copied-member limits used by `_divisi_candidates` (unchanged since train-1; the A6 rules then apply `member_ok`).
DIVISI_MAX_SEMITONES = 12
# Old VOCAB has all three accidentals and the common note shapes only here; a member outside it made an OOV
# accidental or head token and the guard quarantined the strip (smoke 2026-10-15, freeze Amendment A1).
DIVISI_MEMBER_POSITIONS = (-3, 12)
# A6 member sampler (docs/superpowers/plans/2026-10-18-divisi-a6.md Task 2). Dyad weights renormalise over 0.85;
# triads (P_TRIAD_A6) are drawn separately. 7ths are minor only.
A6_INTERVALS: tuple[tuple[str, int, float], ...] = (
    ("2nd", 2, 0.12), ("3rd", 3, 0.16), ("4th", 4, 0.12), ("5th", 5, 0.12), ("6th", 6, 0.12), ("7th", 7, 0.05),
    ("8ve", 8, 0.16))
P_FREE_MEMBER = 0.6
P_TRIAD_A6 = 0.15
P_STEMS_DOWN_2ND = 0.30
# Stems-down share of stemmed 2nds a piece steers toward (round 4 ruling): the plain P_STEMS_DOWN_2ND draw realised
# .217 on the 10-piece smoke (round 3), under the frozen >= 30%, so a 2nd is forced down while the running share is
# below this.
STEMS_DOWN_2ND_TARGET = 0.33
# Inclusive, L1 = 0. A6.4: top widened from 13 for the 2-ledger members. The floor stays -5: a -6 head is always the
# chord's lowest, so it labels as `note.*-L-2`, which the old VOCAB has only for the eighth (Amendment A1), and the
# render guard quarantined every such strip on smoke r12.
MAX_MEMBER_STEPS = (-5, 14)
# Hard limits of any chord head, sounding pitch (Tenor is written treble-8vb). Choral-conductor 2026-10-21 (A6.4):
# soprano up to C6, alto down to E3 (G3 here, see MAX_MEMBER_STEPS), bass C2-G4; tenor keeps the A6.3 range.
# shortcut: bass F#4/G4 are drawn like any in-range member although the conductor wants them rare (shape training
# only); add a per-pitch weight if the full build shows them above ~1% of bass members.
DIVISI_MEMBER_LIMITS: dict[str, tuple[str, str]] = {
    "Soprano": ("B-3", "C6"), "Alto": ("G3", "E5"), "Tenor": ("B-2", "B4"), "Bass": ("C2", "G4")}
MAX_REDRAWS = 8
MAX_CHORD_NOTES = 3
MAX_CHORD_SEMITONES = 12
MINOR_SEVENTH_SEMITONES = 10
KEY_ACCIDENTAL_OCTAVES = range(1, 8)
# Simple-interval names a conductor would not write on one stem: aug unison, aug 2nd, aug 4th, dim 5th, dim 7th, dim 2nd.
FORBIDDEN_MEMBER_INTERVALS: frozenset[str] = frozenset({"A1", "d2", "A2", "A4", "d5", "d7"})
# A6 injection (docs/decisions/piya-106-divisi-a6-design.md section 4; plan Task 3). Shares of chord columns.
P_CHORD_FREE_STRIP = 0.25            # hallucination canary: a quarter of divisi strips carry no chord
CHORD_DENSITY = (0.20, 0.60)         # chord columns / note columns on a strip that carries chords
A6_DURATIONS: dict[str, float] = {"whole": .12, "half": .20, "dotted": .15, "quarter": .33, "beamed": .20}
BEAMED_TYPES: frozenset[str] = frozenset({"eighth", "16th", "32nd", "64th", "128th"})
P_TIE_CHORD = 1.0                    # A6.3: tie sites are supply-limited, so every one is chorded first
TIES_ENABLED: bool = True            # on: G1b passed the tied-chord case 6/6 (user-scored 2026-10-19)
MAX_CROSSING = 0.10                  # per piece: chord columns whose member crosses the adjacent voice
ACCIDENTAL_COL_TARGET = 0.12         # chord columns with a drawn accidental on any head
ACCIDENTAL_SITE_BOOST = 4.0          # site weight factor for chromatic notes while the piece is under target
# A6.3 (ml-cv-lead 2026-10-19): members 2+ ledger lines out (step <= -4 or >= 12) were 1.7% of members on the smoke.
LEDGER2_MEMBER_TARGET = 0.05         # share of members a piece steers toward
LEDGER2_SITE_BOOST = 3.0             # site weight factor for near-edge heads while under target
LEDGER2_MEMBER_CAP = 0.08            # never boost at or above this share
# Soprano (C6), alto (A3-G3) and bass (C2, E4-G4) reach 2 ledgers within DIVISI_MEMBER_LIMITS; tenor never does.
LEDGER2_VOICES: frozenset[str] = frozenset({"Soprano", "Alto", "Bass"})
LEDGER2_STEPS = (-4, 12)             # a member at or beyond these steps sits on 2+ ledger lines
NEAR_EDGE_STEPS = (-1, 9)            # a base head here reaches LEDGER2_STEPS with a 2nd-4th member
# A6.4 (ml-cv-lead + choral-conductor 2026-10-21): Bach's native ties gave 1.6% tied chord columns on the smoke, so
# barline pairs inside a system are tied synthetically toward this share of chord columns (native included).
TIE_CHORD_TARGET = 0.05
TIE_CHORD_CAP = 0.08
MERGE_METERS: frozenset[str] = frozenset({"4/4", "2/2"})
WHOLE_NOTE_QL = 4.0
# Merges (ruling 2026-10-18): plain notes in one bar become one longer note on the first pitch, always chorded.
MERGE_TO_WHOLE = True                # a whole 4/4 or 2/2 bar
MERGE_TO_HALF = True                 # quarter + quarter
MERGE_TO_DOTTED_HALF = True          # half + quarter
MERGE_TO_DOTTED_QUARTER = True       # quarter (on a beat) + eighth
MERGE_TO_DOTTED_HALF_3Q = True       # quarter + quarter + quarter (ruling 2026-10-18, round 3: dotted supply)
# Allowed start offsets (quarter lengths into the bar) of the merged note, per meter: beats 1/3 of 4/4, beat 1 of
# 2/2 and 3/4 for a half; beats 1/2 of 4/4 and beat 1 of 3/4 for a dotted half.
MERGE_HALF_STARTS: dict[str, tuple[float, ...]] = {"4/4": (0.0, 2.0), "2/2": (0.0,), "3/4": (0.0,)}
MERGE_DOTTED_HALF_STARTS: dict[str, tuple[float, ...]] = {"4/4": (0.0, 1.0), "3/4": (0.0,)}
MERGE_DOTTED_HALF_3Q_STARTS: dict[str, tuple[float, ...]] = {"4/4": (0.0, 1.0), "3/4": (0.0,)}
# A duration class whose running share is above its target by more than this is not drawn at all (round 3): the
# deficit floor alone still let quarters and beamed notes fill strips once the scarce classes ran out. The skip only
# applies once a strip has reached CHORD_DENSITY[0] (round 4): applied below it, 47 of 172 smoke strips ran out of
# classes and were undone as density-short (plain share .465 against .25).
DURATION_OVER_TARGET = 0.01
# Share of chord-bearing strips expected to end below CHORD_DENSITY[0] and be restored to plain; the chord-free draw
# is lowered by it so all plain strips together aim at P_CHORD_FREE_STRIP (3-piece smoke, round 1).
EXPECTED_DENSITY_SHORT = 0.05
STEMLESS = "none"                    # stems entry for a whole-note chord
MIDDLE_LINE_POSITION = 4             # L3 with L1 = 0
OCTAVE_SEMITONES = 12
# Per-piece mix steering: a class already at or above its target keeps this fraction of its weight, so the draw
# stays random but the realised mix (interval class, member source, duration) converges on the frozen targets.
DEFICIT_FLOOR = 0.05
DIVISI_SUFFIX = "__divisi"

# Divisi A7 (docs/decisions/piya-106-divisi-a7-design.md section 3), only with --a7; without it every A6 path is
# unchanged. `apply_a7` swaps the shared constants above; the rest are A7-only.
A7_ARM: str | None = None                       # "C" (chords) or "CL" (chords + layers)
P_TRIAD_A7 = 0.30
# ml-cv-lead 2026-10-30 (ruling 2): the design's .15 is out of reach at the conductor sites, so A7 keeps A6 v2's realised
# 2+ ledger exposure (.045) as a floor; ledger-site members are exempt from MAX_CROSSING under their own cap.
LEDGER2_MEMBER_TARGET_A7 = 0.10               # steering target (20-piece smoke: .08 realised .0435); floor .045
LEDGER2_FLOOR_A7 = 0.045
LEDGER2_SITE_BOOST_A7 = 6.0                    # design 3.1: raised because the 20-piece smoke fell short (.0417 at 3.0)
# Steering target for the free-member share (gate stays .60 +-.03): the 20-piece smoke realised .630 steering at .60,
# as A6 steered 2nds at .33 to realise >= .30.
P_FREE_MEMBER_A7 = 0.57
LEDGER2_MEMBER_CAP_A7 = 0.08
LEDGER_CROSS_CAP = 0.05                         # chord columns whose crossing member is a ledger-site member
# Raised floor so every dyad bucket's train count stays >= .95 of A6 build v2 with triads at .30 (corpus gate 5.4):
# A6 v2 had 16152 dyads in 18972 chords, so A7 needs about +16% chords; uniform(.32, .60) lifts the mean from .40 to .46.
CHORD_DENSITY_A7 = (0.32, 0.60)
# Template triads (choral-conductor shapes, 3.1): chance a drawn triad uses a template, per site duration class. The
# realised mix is about 50/50 with >= .70 of templates on whole/half/dotted notes and <= .05 beamed (design 3.1).
TEMPLATE_P_BY_CLASS: dict[str, float] = {"whole": 1.0, "half": 1.0, "dotted": 1.0, "quarter": .6, "beamed": .05}
TEMPLATE_VOICE_FACTOR: dict[str, float] = {"Soprano": 1.2, "Alto": .5, "Tenor": .8, "Bass": 1.2}
TEMPLATE_CADENCE_FACTOR = 1.5                   # a fermata note or the final bar
TEMPLATE_RANGES: dict[str, tuple[str, str]] = {"Tenor": ("C3", "G4"), "Alto": ("G3", "C5")}
SOPRANO_TEMPLATE_TOP = ("G5", "A5")             # usual top of a soprano template triad (weighted, not forced)
SOPRANO_TOP_WEIGHT = 3.0
ALTO_TEMPLATE_MAX_SPAN = 9                      # semitones: a 6th
BASS_LOW_THIRD_FLOOR = "E3"                     # no 3rd or 2nd whose lower note is below this
# Conductor ledger sites (3.1): a member 2+ ledger lines out is allowed only here.
LEDGER_SITE_SOPRANO_TOP = "C6"
LEDGER_SITE_ALTO_LOW_INTERVALS = frozenset({7, 8, 9, 12})       # 5th, 6th, octave above the low alto member
LEDGER_SITE_BASS_LOW = "C2"
LEDGER_SITE_BASS_HIGH = "E4"
LEDGER_SITE_BASS_HIGH_INTERVALS = frozenset({3, 4, 8, 9})       # 3rd or 6th below the high bass member
# Layers (arm CL, 3.2). The layer RNG is separate from the chord RNG, so arms C and CL get identical chords.
LAYER_BAR_SHARE = 0.08
LAYER_SAME_RHYTHM = 0.15
LAYER_MID_ENTRY = 0.20
LAYER_TIE_TARGET = 0.05                         # share of layer bars whose last layer-2 note ties over the barline
LAYER_TIE_CAP = 0.08
LAYER2_INTERVAL_WEIGHTS: dict[int, float] = {0: .5, 3: 2.0, 4: 2.0, 7: 1.0, 8: 1.5, 9: 1.5, 12: 1.0}


def apply_a7(arm: str) -> None:
    """Switch the shared A6 constants to their A7 values (design section 3)."""
    global A7_ARM, P_TRIAD_A6, LEDGER2_MEMBER_TARGET, LEDGER2_MEMBER_CAP, CHORD_DENSITY, LEDGER2_SITE_BOOST
    global P_FREE_MEMBER
    if arm not in ("C", "CL"):
        raise ValueError(f"A7 arm {arm!r}")
    A7_ARM = arm
    P_TRIAD_A6 = P_TRIAD_A7
    LEDGER2_MEMBER_TARGET = LEDGER2_MEMBER_TARGET_A7
    LEDGER2_MEMBER_CAP = LEDGER2_MEMBER_CAP_A7
    CHORD_DENSITY = CHORD_DENSITY_A7
    LEDGER2_SITE_BOOST = LEDGER2_SITE_BOOST_A7
    P_FREE_MEMBER = P_FREE_MEMBER_A7


@dataclass
class PiecePlan:
    """Everything decided for one piece; saved next to its MEI so renders and the G1b page can use it."""

    piece_id: str
    source: str
    composer: str
    measures: int = 0
    systems: list[list[int]] = field(default_factory=list)       # measure indices (0-based, MEI order)
    pages: list[list[int]] = field(default_factory=list)         # system indices per page
    measure_n: list[str] = field(default_factory=list)           # MEI @n per measure index
    key_change: dict[str, object] | None = None
    meter_change: dict[str, object] | None = None
    multirest: dict[str, object] | None = None
    tokens_per_voice: dict[str, int] = field(default_factory=dict)
    source_fixes: dict[str, int] = field(default_factory=dict)   # see _normalise_control_events


def _normalise_control_events(score_el: ET.Element) -> dict[str, int]:
    """Make fermatas, ties and barlines drawable in the label vocabulary; returns what was changed.

    Why: the agnostic vocabulary only has `fermata.above` (CPM, one voice per staff). The Bach sources put the
    alto/bass fermatas below and inverted, a leftover of two-voice-per-staff engraving; open-score choral
    editions print them above every staff, so they are moved above rather than dropped from the labels (the
    SVG check caught 8 per piece otherwise). A `<tie>` with no endid comes from a source tie music21 left
    open ("ties left open"): Verovio draws a dangling curve that no label can describe, so it is removed.
    """
    fixes = {"fermatas_moved_above": 0, "open_ties_removed": 0, "cross_staff_ties_removed": 0,
             "repeat_end_to_double": 0, "repeat_start_removed": 0}
    for fermata in score_el.iter(f"{{{MEI_NS}}}fermata"):
        if fermata.attrib.get("place", "above") != "above" or fermata.attrib.get("form", "norm") != "norm":
            fermata.set("place", "above")
            fermata.set("form", "norm")
            fixes["fermatas_moved_above"] += 1
    staff_of = _note_staff_map(score_el)
    for parent in list(score_el.iter()):
        for child in list(parent):
            if child.tag != f"{{{MEI_NS}}}tie":
                continue
            if not child.attrib.get("endid"):
                parent.remove(child)
                fixes["open_ties_removed"] += 1
                continue
            # music21 can close a source tie that is open in its own part onto the same pitch in a neighbouring
            # part (seen twice in Palestrina). Verovio then draws a curve between two staves; the converter labels
            # ties per staff, so neither end gets a label. A tie never joins two voices, so it is removed.
            start = staff_of.get(child.attrib.get("startid", "").lstrip("#"))
            end = staff_of.get(child.attrib["endid"].lstrip("#"))
            if start is not None and end is not None and start != end:
                parent.remove(child)
                fixes["cross_staff_ties_removed"] += 1
    # Repeats are a known limitation (docs/bug-tracker.md): the vocabulary has no repeat token and Stage 4/5 never
    # expand them, so renders carry none. A repeat closes a section in these sources, so its natural engraving
    # without dots is a double barline; the converter writes `dbl` as barline-L1, like every CPM barline type.
    # A start repeat on @left just goes: the previous measure's right barline is already drawn there.
    if next(score_el.iter(f"{{{MEI_NS}}}ending"), None) is not None:
        raise ValueError("volta endings (repeat structure the labels cannot describe)")
    for measure in score_el.iter(f"{{{MEI_NS}}}measure"):
        if measure.attrib.get("right") in REPEAT_BARLINES:
            measure.set("right", "dbl")
            fixes["repeat_end_to_double"] += 1
        if measure.attrib.get("left") in REPEAT_BARLINES:
            del measure.attrib["left"]
            fixes["repeat_start_removed"] += 1
    assert_no_repeats(score_el)
    # Scope has no C clefs (treble / treble-8vb / bass only); _normalise_clefs should guarantee it, this proves it.
    for el in score_el.iter():
        if el.attrib.get("clef.shape", el.attrib.get("shape")) == "C":
            raise ValueError(f"C clef survived normalisation on <{el.tag}>")
    return fixes


def _note_staff_map(score_el: ET.Element) -> dict[str, str]:
    """Map every note's xml:id to its staff @n, so ties can be checked for joining two voices."""
    staff_of: dict[str, str] = {}
    for staff in score_el.iter(f"{{{MEI_NS}}}staff"):
        for note in staff.iter(f"{{{MEI_NS}}}note"):
            note_id = note.attrib.get(XML_ID)
            if note_id is not None:
                staff_of[note_id] = staff.attrib.get("n", "")
    return staff_of


def assert_no_repeats(score_el: ET.Element) -> None:
    """Refuse to hand Verovio a repeat barline: its dots would be drawn with no label (known limitation)."""
    for el in score_el.iter():
        for attr in ("left", "right", "form"):
            if el.attrib.get(attr, "").startswith("rpt"):
                raise ValueError(f"repeat barline survived normalisation: <{el.tag}> @{attr}={el.attrib[attr]}")


def _satb_order(score: music21.stream.Score) -> list[music21.stream.Part] | None:
    """Parts in S, A, T, B order, or None when the piece is not a four-voice choral texture."""
    parts = list(score.parts)
    if len(parts) != 4:
        return None
    names = [(p.partName or "").strip().lower() for p in parts]
    if all(n and n[0] == v for n, v in zip(names, VOICE_INITIAL)):
        return parts
    means = []
    for p in parts:
        pitches = [n.pitch.ps for n in p.recurse().notes if isinstance(n, music21.note.Note)]
        if not pitches:
            return None
        means.append(statistics.mean(pitches))
    return parts if means == sorted(means, reverse=True) else None


def _normalise_clefs(parts: list[music21.stream.Part]) -> None:
    """One clef per voice for the whole piece; the notes keep their sounding pitch."""
    for part, clef_cls in zip(parts, NORMALISED_CLEFS):
        for clef in list(part.recurse().getElementsByClass(music21.clef.Clef)):
            clef.activeSite.remove(clef)
        first = part.getElementsByClass(music21.stream.Measure).first()
        if first is None:
            raise ConversionError("part without measures")
        first.insert(0, clef_cls())


def _drawn_position(pitch: music21.pitch.Pitch, voice_index: int) -> int:
    """Staff position (L1 = 0) under the normalised clef, for the range check."""
    diatonic = pitch.octave * 7 + "CDEFGAB".index(pitch.step)
    bottom_line = {0: 4 * 7 + 2, 1: 4 * 7 + 2, 2: 3 * 7 + 2, 3: 2 * 7 + 4}[voice_index]   # E4, E4, E3(8vb), G2
    return diatonic - bottom_line


def _range_problem(parts: list[music21.stream.Part]) -> str | None:
    for i, part in enumerate(parts):
        positions = [_drawn_position(n.pitch, i) for n in part.recurse().notes if isinstance(n, music21.note.Note)]
        if positions and (min(positions) < MIN_POSITION or max(positions) > MAX_POSITION):
            return f"range {VOICES[i]} {min(positions)}..{max(positions)}"
    return None


def _key_fifths_at(part: music21.stream.Part, measure_index: int) -> int:
    fifths = 0
    for i, m in enumerate(part.getElementsByClass(music21.stream.Measure)):
        if i > measure_index:
            break
        for ks in m.getElementsByClass(music21.key.KeySignature):
            fifths = ks.sharps
    return fifths


def _modulate(parts: list[music21.stream.Part], start: int, rng: random.Random) -> dict[str, object] | None:
    """Transpose measures >= start to a new key and put the new signature there. None when no key fits."""
    old = _key_fifths_at(parts[0], start)
    candidates: list[tuple[int, music21.interval.Interval]] = []
    for new in range(-MAX_KEY_FIFTHS, MAX_KEY_FIFTHS + 1):
        if new == old:
            continue
        a = music21.key.KeySignature(old).asKey("major").tonic
        b = music21.key.KeySignature(new).asKey("major").tonic
        iv = music21.interval.Interval(music21.pitch.Pitch(f"{a.name}4"), music21.pitch.Pitch(f"{b.name}4"))
        if iv.semitones > 6:
            iv = music21.interval.Interval(music21.pitch.Pitch(f"{a.name}4"), music21.pitch.Pitch(f"{b.name}3"))
        elif iv.semitones < -6:
            iv = music21.interval.Interval(music21.pitch.Pitch(f"{a.name}4"), music21.pitch.Pitch(f"{b.name}5"))
        if abs(iv.semitones) <= MAX_TRANSPOSE_SEMITONES:
            candidates.append((new, iv))
    if not candidates:
        return None
    # Changes to no key are over-sampled: they are the only case where Verovio draws cancelling naturals.
    to_zero = [c for c in candidates if c[0] == 0]
    new, iv = to_zero[0] if to_zero and rng.random() < 0.3 else rng.choice(candidates)
    for part in parts:
        measures = list(part.getElementsByClass(music21.stream.Measure))
        for m in measures[start:]:
            for ks in list(m.getElementsByClass(music21.key.KeySignature)):
                m.remove(ks)
            m.transpose(iv, inPlace=True)
        measures[start].insert(0, music21.key.KeySignature(new))
        part.makeAccidentals(inPlace=True, overrideStatus=True)
    return {"old_fifths": old, "new_fifths": new, "interval": iv.directedName}


def _meter_attrs(meter: tuple[str, ...]) -> dict[str, str]:
    return {"meter.sym": meter[1]} if meter[0] == "sym" else {"meter.count": meter[1], "meter.unit": meter[2]}


def _initial_meter(score_def: ET.Element) -> tuple[str, ...] | None:
    attrs = dict(score_def.attrib)
    child = score_def.find(f".//{{{MEI_NS}}}meterSig")
    if child is not None:
        attrs.update({f"meter.{k}": v for k, v in child.attrib.items()})
    if attrs.get("meter.sym") in ("common", "cut"):
        return ("sym", attrs["meter.sym"])
    if "meter.count" in attrs and "meter.unit" in attrs:
        return ("num", attrs["meter.count"], attrs["meter.unit"])
    return None


def _layout(n: int, force: set[int], forbid: set[int], rng: random.Random) -> list[list[int]]:
    """Measures per system: 4-5, but a forced measure always opens a system and a forbidden one never does."""
    systems: list[list[int]] = [[0]]
    target = rng.choice(MEASURES_PER_SYSTEM)
    for i in range(1, n):
        if i in force or (len(systems[-1]) >= target and i not in forbid):
            systems.append([i])
            target = rng.choice(MEASURES_PER_SYSTEM)
        else:
            systems[-1].append(i)
    return systems


def _insert_before_measure(measure: ET.Element, parents: dict[ET.Element, ET.Element], new: ET.Element,
                           before_defs: bool) -> None:
    """Insert `new` before `measure`; with before_defs, also before the scoreDefs that lead into it (a break
    must come before a key/meter change, or Verovio draws the change at the end of the old system)."""
    parent = parents[measure]
    children = list(parent)
    idx = children.index(measure)
    if before_defs:
        while idx > 0 and children[idx - 1].tag == f"{{{MEI_NS}}}scoreDef":
            idx -= 1
    parent.insert(idx, new)


def _sounding(parts: list[music21.stream.Part]) -> list[list[tuple[float, float, music21.pitch.Pitch]]]:
    """Per voice, (start, end, pitch) of every sounding head in quarter lengths from the piece start.

    Chord heads are included because voices injected earlier are chords by the time a later voice is processed.
    """
    out: list[list[tuple[float, float, music21.pitch.Pitch]]] = []
    for part in parts:
        spans = []
        for m in part.getElementsByClass(music21.stream.Measure):
            for n in m.getElementsByClass((music21.note.Note, music21.chord.Chord)):
                start = float(m.offset + n.offset)
                for pitch in n.pitches:
                    spans.append((start, start + float(n.quarterLength), pitch))
        out.append(spans)
    return out


def _divisi_candidates(base: music21.pitch.Pitch, members: list[music21.pitch.Pitch], others: list[
        music21.pitch.Pitch], voice_index: int, generics: frozenset[int]) -> list[music21.pitch.Pitch]:
    """Pitches another voice sounds that may join this chord: interval class in `generics` to the base note, no
    generic unison with any member, the whole chord within 12 semitones, drawn within DIVISI_MEMBER_POSITIONS."""
    found: dict[str, music21.pitch.Pitch] = {}
    for p in others:
        if music21.interval.Interval(base, p).generic.undirected not in generics:
            continue
        if any(music21.interval.Interval(q, p).generic.undirected == 1 for q in members):
            continue
        chord_ps = [q.ps for q in members] + [p.ps]
        if max(chord_ps) - min(chord_ps) > DIVISI_MAX_SEMITONES:
            continue
        if not DIVISI_MEMBER_POSITIONS[0] <= _drawn_position(p, voice_index) <= DIVISI_MEMBER_POSITIONS[1]:
            continue
        found[p.nameWithOctave] = p
    return [found[k] for k in sorted(found, key=lambda k: (found[k].ps, k))]


def bar_accidentals(measure_index: int, offset: float, parts: list[music21.stream.Part]) -> dict[str, int]:
    """Alter in force per step+octave (e.g. "G4" -> 1) at `offset` of the measure, across all voices.

    Why: choral free members may only use accidentals already printed in the bar, so the chord never adds a new
    accidental the choir has not seen. Covers the key signature in effect (mid-piece changes included, per part)
    and every head sounded strictly before `offset` in the same measure, in any voice, including the heads of chords
    injected earlier (a sharp on an injected member is printed, so it is in force for later free members).
    """
    in_force: dict[str, int] = {}
    for part in parts:
        measures = list(part.getElementsByClass(music21.stream.Measure))
        key_sig: music21.key.KeySignature | None = None
        for m in measures[:measure_index + 1]:
            for ks in m.getElementsByClass(music21.key.KeySignature):
                key_sig = ks
        if key_sig is not None:
            for letter in "CDEFGAB":
                acc = key_sig.accidentalByStep(letter)
                if acc is not None:
                    for octave in KEY_ACCIDENTAL_OCTAVES:
                        in_force[f"{letter}{octave}"] = int(acc.alter)
    for part in parts:
        measures = list(part.getElementsByClass(music21.stream.Measure))
        if measure_index >= len(measures):
            continue
        heads = measures[measure_index].getElementsByClass((music21.note.Note, music21.chord.Chord))
        for n in sorted(heads, key=lambda x: x.offset):
            if n.offset < offset:
                for pitch in n.pitches:
                    in_force[f"{pitch.step}{pitch.octave}"] = int(pitch.alter)
    return in_force


def free_member(base: music21.pitch.Pitch, generic: int, direction: int, in_force: dict[str, int],
                key: music21.key.Key) -> music21.pitch.Pitch | None:
    """Diatonic member `generic` steps (2 = second .. 8 = octave) above/below `base` in `key`, or None.

    Natural minor is the default for minor keys because the key signature carries it; a raised degree appears
    only when `in_force` has it for that step and octave. Returns None for a 7th that is not a minor 7th (the
    frozen rule is "7th: minor only"; the caller re-draws) and for a result needing a double accidental.
    """
    index = base.octave * 7 + "CDEFGAB".index(base.step) + direction * (generic - 1)
    octave, step_i = divmod(index, 7)
    letter = "CDEFGAB"[step_i]
    key_acc = key.accidentalByStep(letter)
    alter = in_force.get(f"{letter}{octave}", int(key_acc.alter) if key_acc is not None else 0)
    if abs(alter) > 1:
        return None
    result = music21.pitch.Pitch(letter + {-1: "-", 0: "", 1: "#"}[alter] + str(octave))
    if generic == 7 and abs(result.ps - base.ps) != MINOR_SEVENTH_SEMITONES:
        return None
    return result


def member_ok(chord: list[music21.pitch.Pitch], voice_index: int) -> bool:
    """True when `chord` (all notes on one stem) is singable and drawable for the voice.

    Why each check: DIVISI_MEMBER_LIMITS and MAX_MEMBER_STEPS keep every head singable and tokenisable; span and note
    count keep the stem a normal choral divisi; the interval ban is the conductor rule (no aug/dim leaps, no
    chromatic second or unison) and a generic unison would overprint two heads.
    """
    lo_ps, hi_ps = (music21.pitch.Pitch(p).ps for p in DIVISI_MEMBER_LIMITS[VOICES[voice_index]])
    if len(chord) > MAX_CHORD_NOTES:
        return False
    for p in chord:
        if not lo_ps <= p.ps <= hi_ps:
            return False
        if not MAX_MEMBER_STEPS[0] <= _drawn_position(p, voice_index) <= MAX_MEMBER_STEPS[1]:
            return False
    if max(p.ps for p in chord) - min(p.ps for p in chord) > MAX_CHORD_SEMITONES:
        return False
    for i, a in enumerate(chord):
        for b in chord[i + 1:]:
            if (a.step, a.octave) == (b.step, b.octave):
                return False
            lower, upper = sorted((a, b), key=lambda p: p.ps)
            if music21.interval.Interval(lower, upper).simpleName in FORBIDDEN_MEMBER_INTERVALS:
                return False
    return True


def _duration_class(dur: music21.duration.Duration) -> str:
    """Class of a written duration; same rule as divisi_a6_feasibility.duration_class (that module imports this one,
    so it cannot be imported from there)."""
    if dur.dots > 0:
        return "dotted"
    if dur.type in BEAMED_TYPES:
        return "beamed"
    return dur.type if dur.type in ("whole", "half", "quarter") else "other"


def _key_alter(fifths: int, step: str) -> int:
    acc = music21.key.KeySignature(fifths).accidentalByStep(step)
    return int(acc.alter) if acc is not None else 0


def _chromatic(pitch: music21.pitch.Pitch, fifths: int) -> bool:
    """True when the pitch leaves the key signature, so it will most likely be drawn with an accidental."""
    return int(pitch.alter) != _key_alter(fifths, pitch.step)


def _ledger2_boost(voice: str, near_edge: bool, realised: int, members: int) -> float:
    """Site weight factor steering members 2+ ledger lines out toward LEDGER2_MEMBER_TARGET (A6.3)."""
    share = realised / max(members, 1)
    if voice not in LEDGER2_VOICES or not near_edge or share >= LEDGER2_MEMBER_CAP:
        return 1.0
    return LEDGER2_SITE_BOOST if share < LEDGER2_MEMBER_TARGET else 1.0


def _is_ledger2(step: int) -> bool:
    return step <= LEDGER2_STEPS[0] or step >= LEDGER2_STEPS[1]


def _deficit_weights(targets: list[float], realised: list[int], done: int) -> list[float]:
    """Draw weights that pull a running mix toward `targets` (shares summing to 1).

    Why: static weights drift: sites, sources and classes fail at different rates (copied members often have no
    candidate; Bach has few whole and dotted notes). Weighting by the remaining deficit after `done` draws makes the
    per-piece mix track the targets wherever the piece allows it.
    """
    return [max(t * (done + 1) - r, DEFICIT_FLOOR * t) for t, r in zip(targets, realised)]


def _has_second(pitches: list[music21.pitch.Pitch], voice_index: int) -> bool:
    """True when two heads sit on adjacent staff positions, so one head is displaced beside the stem."""
    positions = sorted(_drawn_position(p, voice_index) for p in pitches)
    return any(b - a == 1 for a, b in zip(positions, positions[1:]))


def _stem_direction(pitches: list[music21.pitch.Pitch], voice_index: int, drng: random.Random,
                    force_down_2nd: bool = False) -> str:
    """Explicit stem for every injected chord, so the stem logged in the stats is the stem Verovio draws.

    A chord holding a same-stem 2nd gets stems down with P_STEMS_DOWN_2ND (both displacement sides must be seen in
    training), or always down with `force_down_2nd`: the caller sets it while the piece's stems-down share of 2nds is
    under STEMS_DOWN_2ND_TARGET, because copied 2nds sit mostly above the base and the plain draw fell short (round
    4). Any other chord follows the engraving rule: the head furthest from the middle line decides, ties down.
    """
    positions = sorted(_drawn_position(p, voice_index) for p in pitches)
    if _has_second(pitches, voice_index):
        return "down" if force_down_2nd or drng.random() < P_STEMS_DOWN_2ND else "up"
    return "down" if positions[-1] - MIDDLE_LINE_POSITION >= MIDDLE_LINE_POSITION - positions[0] else "up"


def _ps(name: str) -> float:
    return music21.pitch.Pitch(name).ps


def _is_cadence(note: music21.note.GeneralNote, mi: int, n_measures: int) -> bool:
    """A fermata note (Bach marks phrase-end cadences with one) or the final bar."""
    return mi == n_measures - 1 or any(isinstance(e, music21.expressions.Fermata) for e in note.expressions)


def _ledger_sites_ok(base: music21.pitch.Pitch, members: list[music21.pitch.Pitch], vi: int, cadence: bool) -> bool:
    """A7 conductor ledger sites (design 3.1): a member 2+ ledger lines out only where a choir writes one. Always True
    outside A7, so A6 draws are unchanged."""
    if A7_ARM is None:
        return True
    heads = sorted([base] + members, key=lambda p: p.ps)
    voice = VOICES[vi]
    for p in members:
        if not _is_ledger2(_drawn_position(p, vi)):
            continue
        i = next(k for k, h in enumerate(heads) if h is p)
        if voice == "Soprano":
            ok = p.nameWithOctave == LEDGER_SITE_SOPRANO_TOP and i == len(heads) - 1
        elif voice == "Alto":
            ok = (cadence and i == 0 and _drawn_position(p, vi) <= LEDGER2_STEPS[0]
                  and int(heads[1].ps - p.ps) in LEDGER_SITE_ALTO_LOW_INTERVALS)
        elif voice == "Bass":
            ok = ((p.nameWithOctave == LEDGER_SITE_BASS_LOW and i == 0 and heads[1].ps - p.ps == OCTAVE_SEMITONES)
                  or (p.nameWithOctave == LEDGER_SITE_BASS_HIGH and i == len(heads) - 1
                      and int(p.ps - heads[-2].ps) in LEDGER_SITE_BASS_HIGH_INTERVALS))
        else:
            ok = False                                        # no tenor 2+ ledger members
        if not ok:
            return False
    return True


# Conductor ledger sites per voice: (pitch, member must sit above the base note, cadence only).
LEDGER_SITES: dict[str, tuple[tuple[str, bool, bool], ...]] = {
    "Soprano": ((LEDGER_SITE_SOPRANO_TOP, True, False),),
    "Alto": (("A3", False, True), ("G3", False, True)),
    "Bass": ((LEDGER_SITE_BASS_LOW, False, False), (LEDGER_SITE_BASS_HIGH, True, False)),
    "Tenor": (),
}


def _ledger_site_pitch(base: music21.pitch.Pitch, generic: int, vi: int, cadence: bool, in_force: dict[str, int],
                       fifths: int) -> music21.pitch.Pitch | None:
    """A conductor ledger-site pitch `generic` steps from `base`, natural and in force in the bar, or None (A7 3.1:
    directed draw, since a random member almost never lands on one of these few sites)."""
    for name, above, cadence_only in LEDGER_SITES[VOICES[vi]]:
        q = music21.pitch.Pitch(name)
        if (cadence_only and not cadence) or (q.ps > base.ps) != above:
            continue
        if in_force.get(f"{q.step}{q.octave}", _key_alter(fifths, q.step)) != 0:
            continue
        if music21.interval.Interval(base, q).generic.undirected == generic:
            return q
    return None


def _ledger_reachable(base: music21.pitch.Pitch, vi: int) -> bool:
    """A ledger site lies within an octave of the base note on the right side (A7 replacement for NEAR_EDGE_STEPS)."""
    return any(0 < (q.ps - base.ps if above else base.ps - q.ps) <= OCTAVE_SEMITONES
               for name, above, _ in LEDGER_SITES[VOICES[vi]] for q in [music21.pitch.Pitch(name)])


def _close_position(heads: list[music21.pitch.Pitch]) -> bool:
    """Three heads stacked in 3rds/4ths within an octave (3+3, 3+4, 4+3 and their inversions)."""
    gaps = [b.ps - a.ps for a, b in zip(heads, heads[1:])]
    return all(3 <= g <= 5 for g in gaps) and heads[-1].ps - heads[0].ps < OCTAVE_SEMITONES


def _template_shape_ok(heads: list[music21.pitch.Pitch], base: music21.pitch.Pitch, voice: str, root_pc: int,
                       third_pc: int, fifth_pc: int) -> bool:
    """Choral-conductor template shapes per voice (design 3.1)."""
    lo, mid, hi = heads
    if voice in ("Soprano", "Tenor", "Alto"):
        root_third_octave = (lo.pitchClass == root_pc and mid.pitchClass == third_pc
                             and hi.ps - lo.ps == OCTAVE_SEMITONES)
        if voice == "Soprano":
            return _close_position(heads) or root_third_octave
        rng = TEMPLATE_RANGES[voice]
        if not all(_ps(rng[0]) <= h.ps <= _ps(rng[1]) for h in heads):
            return False
        if voice == "Alto":
            return _close_position(heads) and hi.ps - lo.ps <= ALTO_TEMPLATE_MAX_SPAN
        return _close_position(heads)
    # Bass: open only, the sung note is the root at the bottom: root-5th-octave, or root-octave plus a 3rd.
    if lo.nameWithOctave != base.nameWithOctave or lo.pitchClass != root_pc or hi.ps - lo.ps < OCTAVE_SEMITONES:
        return False
    if any(b.ps - a.ps <= 4 and a.ps < _ps(BASS_LOW_THIRD_FLOOR) for a, b in zip(heads, heads[1:])):
        return False
    fifth_shape = mid.pitchClass == fifth_pc and mid.ps - lo.ps == 7 and hi.ps - lo.ps == OCTAVE_SEMITONES
    third_shape = {mid.pitchClass, hi.pitchClass} == {root_pc, third_pc} and OCTAVE_SEMITONES in (
        mid.ps - lo.ps, hi.ps - lo.ps)
    return fifth_shape or third_shape


def _template_members(base: music21.pitch.Pitch, vi: int, t: float, fifths: int,
                      sounding: list[list[tuple[float, float, music21.pitch.Pitch]]], drng: random.Random,
                      accept: Callable[[list[music21.pitch.Pitch]], bool] = lambda _: True
                      ) -> list[music21.pitch.Pitch] | None:
    """Two members forming a conductor template triad with `base`, from the triad the other voices sound at `t`.

    Members are spelled as the texture spells them, so they add no accidental the bar does not already sound. Three
    pitch classes, or the root doubled; never a doubled 3rd or leading tone. None when the texture at `t` is not a
    plain triad or no shape passing `accept` (the caller's range, crossing and cross-relation checks) fits the voice;
    the caller then draws a random triad."""
    others = [p for vj, spans in enumerate(sounding) if vj != vi for s, e, p in spans if s <= t < e]
    spelled: dict[int, music21.pitch.Pitch] = {base.pitchClass: base}
    for p in others:
        spelled.setdefault(p.pitchClass, p)
    if len(spelled) != 3:
        return None
    triad = music21.chord.Chord(list(spelled.values()))
    if not triad.isTriad():
        return None
    root_pc, third_pc, fifth_pc = triad.root().pitchClass, triad.third.pitchClass, triad.fifth.pitchClass
    leading_pc = (music21.key.KeySignature(fifths).asKey("major").tonic.pitchClass - 1) % 12
    cands: list[music21.pitch.Pitch] = []
    for pc, p in spelled.items():
        if p.accidental is not None and p.accidental.alter not in (-1, 0, 1):
            continue                                       # no double or microtonal accidental members
        for octave in range(base.octave - 2, base.octave + 3):
            q = copy.deepcopy(p)                           # a name round-trip breaks on odd spellings (bwv121.6)
            q.octave = octave
            if abs(q.ps - base.ps) <= OCTAVE_SEMITONES and q.nameWithOctave != base.nameWithOctave:
                cands.append(q)
    options: list[tuple[list[music21.pitch.Pitch], float]] = []
    voice = VOICES[vi]
    for a_i, a in enumerate(cands):
        for b in cands[a_i + 1:]:
            if a.nameWithOctave == b.nameWithOctave:
                continue
            heads = sorted([base, a, b], key=lambda p: p.ps)
            pcs = collections.Counter(h.pitchClass for h in heads)
            if len(pcs) == 2 and (max(pcs, key=pcs.get) != root_pc or root_pc == leading_pc):
                continue                           # only the root may double, never a leading-tone root
            if len(pcs) == 1 or not _template_shape_ok(heads, base, voice, root_pc, third_pc, fifth_pc):
                continue
            if not accept([a, b]):
                continue
            top_ok = _ps(SOPRANO_TEMPLATE_TOP[0]) <= heads[-1].ps <= _ps(SOPRANO_TEMPLATE_TOP[1])
            options.append(([a, b], SOPRANO_TOP_WEIGHT if voice == "Soprano" and top_ok else 1.0))
    if not options:
        return None
    return drng.choices([o for o, _ in options], weights=[w for _, w in options])[0]


@dataclass(eq=False)
class _Site:
    """One place a chord can go: a note, a run of notes merged into one longer note, or a tied note pair.

    eq=False: music21 notes compare by value, so two equal-looking sites would let `pool.remove` drop the wrong one.
    """

    kind: str                                            # "note" | "merge" | "tie"
    cls: str                                             # duration class (A6_DURATIONS key)
    mi: int                                              # measure index of the first head
    heads: list[tuple[int, music21.note.Note]]           # (measure index, note), in order
    chromatic: bool
    merge: str = ""                                      # merge kind ("whole", "half", ...) when kind == "merge"
    unbeam_offset: float | None = None                   # dotted quarter: offset of the eighth that loses its beam


def _plain(n: music21.base.Music21Object) -> bool:
    """A note that may be folded into a merged note: nothing on it (tie, tuplet, grace, fermata, articulation) that
    the single merged note would have to carry or would silently drop."""
    return (isinstance(n, music21.note.Note) and not n.duration.isGrace and not n.duration.tuplets
            and n.tie is None and not n.expressions and not n.articulations)


def _is_plain_type(n: music21.base.Music21Object, dur_type: str) -> bool:
    return isinstance(n, music21.note.Note) and n.duration.type == dur_type and n.duration.dots == 0


def _mergeable(measure: music21.stream.Measure, meter: str | None) -> bool:
    """A 4/4 or 2/2 bar of plain untied notes (no rest, grace, tuplet, fermata or articulation) that fill it."""
    if meter not in MERGE_METERS:
        return False
    items = list(measure.notesAndRests)
    if len(items) < 2 or not all(_plain(n) for n in items):
        return False
    return sum(float(n.quarterLength) for n in items) == WHOLE_NOTE_QL


def _span_pitches(sounding: list[list[tuple[float, float, music21.pitch.Pitch]]], voice_index: int, t: float,
                  t_end: float) -> list[music21.pitch.Pitch]:
    """Distinct pitches the other voices sound anywhere in the chord's span [t, t_end): the copied-member pool.

    Why: taking only the pitches sounding at the onset left the copied pool empty so often that the member mix sat
    at 74/26 free/copied against the frozen 60/40 (two smokes, review round 2). A pitch another voice reaches later
    while the chord still sounds is just as much in the texture. `_draw_members` still applies member_ok, the
    crossing budget and the cross-relation check to every copied member.
    """
    found: dict[str, music21.pitch.Pitch] = {}
    for vj, spans in enumerate(sounding):
        if vj != voice_index:
            for s, e, p in spans:
                if s < t_end and e > t:
                    found.setdefault(p.nameWithOctave, p)
    return list(found.values())


def _base_conflicts(base: music21.pitch.Pitch, vi: int, t: float, t_end: float,
                    sounding: list[list[tuple[float, float, music21.pitch.Pitch]]]) -> bool:
    """True when a merged note's held base pitch crosses the adjacent voice or cross-relates during its span.

    Why: the merge holds the first pitch over notes that were different pitches, so a base that was fine at the
    downbeat can collide with the other voices later in the span (review round 2).
    """
    above = [p.ps for s, e, p in sounding[vi - 1] if s < t_end and e > t] if vi > 0 else []
    below = [p.ps for s, e, p in sounding[vi + 1] if s < t_end and e > t] if vi + 1 < len(sounding) else []
    if (above and base.ps > min(above)) or (below and base.ps < max(below)):
        return True
    return any(q.step == base.step and q.octave == base.octave and q.alter != base.alter
               for vj, spans in enumerate(sounding) if vj != vi for s, e, q in spans if s < t_end and e > t)


def _merge_drops_relied_accidental(removed: list[tuple[float, music21.pitch.Pitch]], mi: int,
                                   free_placed: list[tuple[int, float, music21.pitch.Pitch, int]]) -> bool:
    """True when a merge would fold away a head whose accidental a free member already placed later in the bar uses.

    Why: a free member may only use an accidental in force when it is drawn (`bar_accidentals`), and sites are drawn
    in random order, so a merge drawn later (same voice or a later voice) can remove the very note that put the
    accidental in force. Round 3 smoke, bwv101.7 bar 9: an alto free F#4 on beat 3 relied on the alto's F#4 eighth,
    which a dotted-quarter merge on beat 1 then folded away, so the final score had a new accidental. Only removed
    heads (all but the first, which the merged note keeps) count, and only a free member whose alter leaves the key
    signature can lose its licence; a member on the key alter is always allowed.

    Args:
        removed: (offset in the bar, pitch) of each head the merge removes.
        mi: measure index of the merge.
        free_placed: (measure index, offset in the bar, pitch, key fifths) of every free member placed so far.
    """
    return any(pmi == mi and roff < poff and (r.step, r.octave, r.alter) == (p.step, p.octave, p.alter)
               and int(p.alter) != _key_alter(fx, p.step)
               for roff, r in removed for pmi, poff, p, fx in free_placed)


def _member_overrides_relied_accidental(members: list[music21.pitch.Pitch], placements: list[tuple[int, float]],
                                        free_placed: list[tuple[int, float, music21.pitch.Pitch, int]]) -> bool:
    """True when a new member would change the alter in force for a free member already placed later in the bar.

    Why: the same hole as `_merge_drops_relied_accidental`, from the other side (review round 5). C major: a soprano
    F#4 eighth at offset 2.0 licenses an alto free F#4 at 3.0; a tenor copied F4 natural placed at 2.5 (from a bass
    F4) passes its own span check [2.5, 3.0), yet `bar_accidentals` at 3.0 then reads F4 = 0 and the audit finds a
    new accidental. Any member counts, not only copied ones, since every head before the free member is read.

    Args:
        members: the chord's added pitches (the base note is already in the score).
        placements: (measure index, offset in the bar) of each head the chord is written on.
        free_placed: (measure index, offset in the bar, pitch, key fifths) of every free member placed so far.
    """
    return any(pmi == hmi and hoff < poff and (q.step, q.octave) == (p.step, p.octave) and q.alter != p.alter
               and int(p.alter) != _key_alter(fx, p.step)
               for q in members for hmi, hoff in placements for pmi, poff, p, fx in free_placed)


def _free_members_of(record: dict[str, object]) -> list[tuple[int, float, music21.pitch.Pitch, int]]:
    """(measure index, offset in the bar, pitch, key fifths) of each free member of an injected chord record.

    The offset is read from the chord's measure, so it is the merged note's onset for a merge record too.
    """
    measure: music21.stream.Measure = record["measure"]  # type: ignore[assignment]
    members: list[music21.pitch.Pitch] = record["members"]  # type: ignore[assignment]
    sources: list[str] = record["sources"]  # type: ignore[assignment]
    offset = float(measure.elementOffset(record["chord"]))
    return [(int(record["mi"]), offset, p, int(record["fifths"]))  # type: ignore[call-overload]
            for p, src in zip(members, sources) if src == "free"]


def _merge_pairs(measure: music21.stream.Measure, meter: str | None
                 ) -> list[tuple[str, str, list[music21.note.Note], float | None]]:
    """Two- or three-note merges in one bar: (merge kind, duration class, notes, offset of the eighth that loses its
    beam).

    Why: Bach offers ~3% chord-capable dotted and ~6% half notes against 15% / 20% targets (ruling 2026-10-18), so
    adjacent notes are folded into one note of the target length, only at the metric positions where that note is
    normal notation and never across a barline. A dotted quarter takes the eighth of a quarter-eighth-eighth figure;
    the remaining eighth then stands alone, so its two-note beam is dropped (it becomes a flagged eighth).
    Half + quarter alone left dotted at 11% against 15% (10-piece smoke, round 2), so three plain quarters starting on
    beat 1 or 2 of 4/4 or beat 1 of 3/4 also fold into a dotted half (`dotted_half_3q`).
    """
    if meter is None:
        return []
    beat = float(music21.meter.TimeSignature(meter).beatDuration.quarterLength)
    items = list(measure.notesAndRests)
    out: list[tuple[str, str, list[music21.note.Note], float | None]] = []
    for k in range(len(items) - 1):
        a, b = items[k], items[k + 1]
        if not (_plain(a) and _plain(b)):
            continue
        off = float(measure.elementOffset(a))
        if float(measure.elementOffset(b)) != off + float(a.quarterLength):
            continue
        if MERGE_TO_HALF and _is_plain_type(a, "quarter") and _is_plain_type(b, "quarter") \
                and off in MERGE_HALF_STARTS.get(meter, ()):
            out.append(("half", "half", [a, b], None))
        if MERGE_TO_DOTTED_HALF and _is_plain_type(a, "half") and _is_plain_type(b, "quarter") \
                and off in MERGE_DOTTED_HALF_STARTS.get(meter, ()):
            out.append(("dotted_half", "dotted", [a, b], None))
        c3 = items[k + 2] if k + 2 < len(items) else None
        if (MERGE_TO_DOTTED_HALF_3Q and c3 is not None and _plain(c3) and _is_plain_type(a, "quarter")
                and _is_plain_type(b, "quarter") and _is_plain_type(c3, "quarter")
                and float(measure.elementOffset(c3)) == off + 2 * float(a.quarterLength)
                and off in MERGE_DOTTED_HALF_3Q_STARTS.get(meter, ())):
            out.append(("dotted_half_3q", "dotted", [a, b, c3], None))
        if MERGE_TO_DOTTED_QUARTER and _is_plain_type(a, "quarter") and _is_plain_type(b, "eighth") \
                and off % beat == 0:
            beams = b.beams.beamsList
            c = items[k + 2] if k + 2 < len(items) else None
            if not beams:
                out.append(("dotted_quarter", "dotted", [a, b], None))
            elif (len(beams) == 1 and beams[0].type == "start" and c is not None and _is_plain_type(c, "eighth")
                  and len(c.beams.beamsList) == 1 and c.beams.beamsList[0].type == "stop"):
                out.append(("dotted_quarter", "dotted", [a, b], float(measure.elementOffset(c))))
    return out


def _strip_sites(measures: list[music21.stream.Measure], meters: list[str | None], fifths: list[int],
                 system: list[int], skipped: collections.Counter[str]) -> tuple[list[_Site], int]:
    """Chord sites and note-column count of one (voice, system) strip; notes never chordable count in `skipped`.

    A tie pair is a site only with TIES_ENABLED and both notes inside the strip, so a chord never spills into the
    next system (that strip's density was drawn on its own). Merge sites overlap the note sites of their notes; the
    caller drops every site sharing a note with one already used."""
    notes = [(mi, n) for mi in system for n in measures[mi].getElementsByClass(music21.note.Note)]
    columns = sum(1 for _, n in notes if not n.duration.isGrace)
    sites: list[_Site] = []
    for k, (mi, n) in enumerate(notes):
        if n.duration.isGrace or n.duration.tuplets:
            skipped["grace" if n.duration.isGrace else "tuplet"] += 1
            continue
        if n.tie is not None:
            nxt = notes[k + 1] if k + 1 < len(notes) else None
            prev = notes[k - 1] if k > 0 else None
            starts_pair = (nxt is not None and n.tie.type == "start" and nxt[1].tie is not None
                           and nxt[1].tie.type == "stop" and not nxt[1].duration.tuplets)
            ends_pair = (prev is not None and n.tie.type == "stop" and prev[1].tie is not None
                         and prev[1].tie.type == "start" and not prev[1].duration.tuplets)
            cls = _duration_class(n.duration)
            if TIES_ENABLED and starts_pair and nxt is not None and cls in A6_DURATIONS:
                sites.append(_Site("tie", cls, mi, [(mi, n), nxt], _chromatic(n.pitch, fifths[mi])))
            elif not (TIES_ENABLED and ends_pair):
                skipped["tie"] += 1
            continue
        cls = _duration_class(n.duration)
        if cls not in A6_DURATIONS:
            skipped["duration"] += 1
            continue
        sites.append(_Site("note", cls, mi, [(mi, n)], _chromatic(n.pitch, fifths[mi])))
    for mi in system:
        m = measures[mi]
        if MERGE_TO_WHOLE and "whole" in A6_DURATIONS and _mergeable(m, meters[mi]):
            bar = list(m.getElementsByClass(music21.note.Note))
            sites.append(_Site("merge", "whole", mi, [(mi, n) for n in bar], _chromatic(bar[0].pitch, fifths[mi]),
                               merge="whole"))
        for kind, cls, pair, unbeam in _merge_pairs(m, meters[mi]):
            if cls in A6_DURATIONS:
                sites.append(_Site("merge", cls, mi, [(mi, n) for n in pair], _chromatic(pair[0].pitch, fifths[mi]),
                                   merge=kind, unbeam_offset=unbeam))
    return sites, columns


def _draw_members(base: music21.pitch.Pitch, mi: int, offset: float, t: float, t_end: float, vi: int,
                  parts: list[music21.stream.Part], sounding: list[list[tuple[float, float, music21.pitch.Pitch]]],
                  fifths: int, drng: random.Random, class_weights: list[float], prefer_copied: bool,
                  prefer_chromatic: bool, crossing: int, done: int, check_cross_relation: bool,
                  template_p: float = 0.0, cadence: bool = False,
                  texture: list[list[tuple[float, float, music21.pitch.Pitch]]] | None = None,
                  prefer_ledger: bool = False, ledger_crossing: int = 0
                  ) -> tuple[list[music21.pitch.Pitch], list[str], str, bool, bool] | str:
    """Members for a chord on `base` sounding over [t, t_end): (members, sources, bucket, crosses).

    `class_weights` cover A6_INTERVALS then the triad. Returns the bucket name instead when MAX_REDRAWS attempts all
    fail, so the caller logs a shortfall; the class is drawn once and kept, so a hard class shows up as shortfall,
    not as a silent swap. Each member tries its preferred source (free or copied) first and the other one second.
    While copied is under target (`prefer_copied`, ruling round 3) a member is copied whenever a copied candidate
    passes every check (range/member_ok, cross-relation, crossing budget); a dyad whose drawn class has none switches
    to another dyad class still in deficit that has one, and only then falls back to a free member. Triad members
    keep their drawn class (they are not steered per class).
    Crossing is judged over the whole span (a member crossing the adjacent voice anywhere counts). Copied members
    may be any pitch another voice sounds in the span (`_span_pitches`), so a copied member is always rejected
    when another voice sounds the same step and octave with a different alter during the span. For a merged note
    (`check_cross_relation`) the accidentals in force are those at its downbeat, so that check covers every member.
    """
    in_force = bar_accidentals(mi, offset, parts)
    key = music21.key.KeySignature(fifths).asKey("major")    # signature only; in_force carries the bar's alters
    span_others = _span_pitches(sounding, vi, t, t_end)     # computed once; reused by every member attempt
    above = [p.ps for s, e, p in sounding[vi - 1] if s < t_end and e > t] if vi > 0 else []
    below = [p.ps for s, e, p in sounding[vi + 1] if s < t_end and e > t] if vi + 1 < len(sounding) else []
    weights = [w for _, _, w in A6_INTERVALS]

    def crossing_ok(ms: list[music21.pitch.Pitch]) -> tuple[bool, bool, bool]:
        """(within budget, a plain member crosses, a ledger-site member crosses). A7 ledger-site members cross under
        LEDGER_CROSS_CAP instead of MAX_CROSSING (ml-cv-lead ruling 2); outside A7 this is the plain budget."""
        def crosses(q: music21.pitch.Pitch) -> bool:
            return bool((above and q.ps > min(above)) or (below and q.ps < max(below)))

        def exempt(q: music21.pitch.Pitch) -> bool:
            return (A7_ARM is not None and _is_ledger2(_drawn_position(q, vi))
                    and _ledger_sites_ok(base, [q], vi, cadence))
        plain = any(crosses(q) and not exempt(q) for q in ms)
        ledger = any(crosses(q) and exempt(q) for q in ms)
        ok = not (plain and crossing + 1 > MAX_CROSSING * (done + 1)) and not (
            ledger and ledger_crossing + 1 > LEDGER_CROSS_CAP * (done + 1))
        return ok, plain, ledger

    def fits(q: music21.pitch.Pitch, generic: int, chosen: list[music21.pitch.Pitch]) -> bool:
        semis = abs(q.ps - base.ps)
        if abs(q.alter) > 1 or (generic == 8 and semis != OCTAVE_SEMITONES) or (
                generic == 7 and semis != MINOR_SEVENTH_SEMITONES):
            return False
        if not member_ok([base] + chosen + [q], vi):
            return False
        if any(o.step == q.step and o.octave == q.octave and o.alter != q.alter for o in span_others):
            return False
        return crossing_ok([q])[0]

    def copied_fits(ci: int, chosen: list[music21.pitch.Pitch]) -> list[music21.pitch.Pitch]:
        generic = A6_INTERVALS[ci][1]
        return [q for q in _divisi_candidates(base, [base] + chosen, span_others, vi, frozenset({generic}))
                if fits(q, generic, chosen)]

    dyad = drng.choices(range(len(A6_INTERVALS) + 1), weights=class_weights)[0]
    triad = dyad == len(A6_INTERVALS)
    bucket = "triad" if triad else A6_INTERVALS[dyad][0]
    # A7 template triad (template_p is 0 outside A7, so no extra draw happens there); random triad if none fits.
    if triad and template_p > 0 and drng.random() < template_p:
        def template_ok(tm: list[music21.pitch.Pitch]) -> bool:
            return (member_ok([base] + tm, vi) and _ledger_sites_ok(base, tm, vi, cadence) and crossing_ok(tm)[0]
                    and not any(q.step == p.step and q.octave == p.octave and q.alter != p.alter
                                for p in tm for q in span_others))

        tm = _template_members(base, vi, t, fifths, texture or sounding, drng, template_ok)
        if tm is not None:
            _, cross, lcross = crossing_ok(tm)
            return tm, ["template", "template"], "triad_template", cross, lcross
    for attempt in range(MAX_REDRAWS):
        classes = drng.choices(range(len(A6_INTERVALS)), weights=weights, k=2) if triad else [dyad]
        members: list[music21.pitch.Pitch] = []
        sources: list[str] = []
        for ci in classes:
            fitting = copied_fits(ci, members) if prefer_copied else []
            if prefer_copied and not fitting and not triad:
                deficit = [cj for cj in range(len(A6_INTERVALS)) if cj != ci
                           and class_weights[cj] > DEFICIT_FLOOR * A6_INTERVALS[cj][2]]
                options = [(cj, f) for cj in deficit for f in [copied_fits(cj, members)] if f]
                if options:
                    ci, fitting = drng.choices(options, weights=[class_weights[cj] for cj, _ in options])[0]
                    bucket = A6_INTERVALS[ci][0]
            generic = A6_INTERVALS[ci][1]
            copied = _divisi_candidates(base, [base] + members, span_others, vi, frozenset({generic}))
            chromatic = [p for p in copied if _chromatic(p, fifths)]
            p: music21.pitch.Pitch | None = None
            src = "copied"
            ledger_p = (_ledger_site_pitch(base, generic, vi, cadence, in_force, fifths)
                        if prefer_ledger and not any(_is_ledger2(_drawn_position(m, vi)) for m in members) else None)
            if ledger_p is not None and fits(ledger_p, generic, members):
                p, src = ledger_p, "ledger"          # its own source: not in the free/copied mix (P_FREE_MEMBER)
            elif fitting:
                chromatic_fit = [q for q in fitting if _chromatic(q, fifths)]
                p = drng.choice(chromatic_fit if prefer_chromatic and not members and chromatic_fit else fitting)
            elif prefer_chromatic and attempt == 0 and not members and chromatic and not prefer_copied:
                p = drng.choice(chromatic)
            else:
                for src in (("free",) if prefer_copied else ("free", "copied")):
                    if src == "free":
                        p = free_member(base, generic, drng.choice((1, -1)), in_force, key)
                    else:
                        p = drng.choice(copied) if copied else None
                    if p is not None:
                        break
            if p is None or abs(p.alter) > 1:
                break
            semis = abs(p.ps - base.ps)
            if (generic == 8 and semis != OCTAVE_SEMITONES) or (generic == 7 and semis != MINOR_SEVENTH_SEMITONES):
                break
            members.append(p)
            sources.append(src)
        if len(members) != len(classes) or not member_ok([base] + members, vi):
            continue
        # Below the .045 floor a random (non-template) dyad or triad may also use A6's any-position ledger member
        # (ruling 2 fallback, extended to random triads 2026-10-30); template triads always keep the conductor sites.
        if not _ledger_sites_ok(base, members, vi, cadence) and not prefer_ledger:
            continue
        if any(q.step == p.step and q.octave == p.octave and q.alter != p.alter
               for p, src in zip(members, sources) if check_cross_relation or src == "copied" for q in span_others):
            continue
        ok, cross, lcross = crossing_ok(members)
        if not ok:
            continue
        return members, sources, bucket, cross, lcross
    return bucket


def _make_chord(pitches: list[music21.pitch.Pitch], src: music21.note.Note, stem: str,
                merged_ql: float | None = None) -> music21.chord.Chord:
    """Chord on `src`'s rhythm, or of `merged_ql` for a merged note (which carries no beams, marks or lyrics)."""
    chord = music21.chord.Chord([copy.deepcopy(p) for p in pitches])
    if merged_ql is not None:
        chord.duration = music21.duration.Duration(merged_ql)
    else:
        chord.duration = copy.deepcopy(src.duration)
        chord.beams = copy.deepcopy(src.beams)
        chord.expressions = list(src.expressions)
        chord.articulations = list(src.articulations)
        chord.lyrics = list(src.lyrics)
    if stem != STEMLESS:
        chord.stemDirection = stem
    return chord


def _accidental_display(part: music21.stream.Part, fresh: bool) -> dict[tuple[int, float, str], bool]:
    """Shown-accidental flag of every single-note head, keyed (measure index, offset, pitch).

    `fresh` runs makeAccidentals on a copy first (the pre-injection baseline); otherwise the part is read as is.
    """
    if fresh:
        part = copy.deepcopy(part)
        part.makeAccidentals(inPlace=True, overrideStatus=True)
    out: dict[tuple[int, float, str], bool] = {}
    for mi, m in enumerate(part.getElementsByClass(music21.stream.Measure)):
        for n in m.getElementsByClass(music21.note.Note):
            acc = n.pitch.accidental
            out[(mi, float(m.elementOffset(n)), n.pitch.nameWithOctave)] = bool(acc is not None and acc.displayStatus)
    return out


def _barline_tie_candidates(measures: list[music21.stream.Measure], fifths: list[int], system: list[int]
                            ) -> tuple[list[tuple[music21.note.Note, music21.note.Note]], int]:
    """Barline note pairs inside one system that a synthetic tie may join (A6.4), and the untied same-pitch pairs.

    Conductor rules: never from a rest or a fermata note, never into a key change, plain notes only (no tie, tuplet,
    grace, articulation), the continuation on beat 1. Untied same-pitch pairs are left alone as negatives for the
    tie false-positive metric, so they are counted, not offered."""
    out: list[tuple[music21.note.Note, music21.note.Note]] = []
    repeats = 0
    for mi, nmi in zip(system, system[1:]):
        last = list(measures[mi].getElementsByClass((music21.note.Note, music21.note.Rest, music21.chord.Chord)))
        first = list(measures[nmi].getElementsByClass((music21.note.Note, music21.note.Rest, music21.chord.Chord)))
        if not last or not first:
            continue
        prev, nxt = last[-1], first[0]
        if not (isinstance(prev, music21.note.Note) and isinstance(nxt, music21.note.Note)):
            continue
        if prev.pitch.ps == nxt.pitch.ps:
            if not (prev.tie is not None and prev.tie.type != "stop" and nxt.tie is not None):
                repeats += 1
            continue
        if (_plain(prev) and _plain(nxt) and float(measures[nmi].elementOffset(nxt)) == 0.0
                and fifths[mi] == fifths[nmi] and _duration_class(prev.duration) in A6_DURATIONS
                and _duration_class(nxt.duration) in A6_DURATIONS):
            out.append((prev, nxt))
    return out, repeats


def _apply_barline_tie(prev: music21.note.Note, nxt: music21.note.Note) -> Callable[[], None]:
    """Ties `nxt` to `prev` at prev's pitch (accidental display is redone by makeAccidentals); returns the undo."""
    old = nxt.pitch
    nxt.pitch = copy.deepcopy(prev.pitch)
    prev.tie, nxt.tie = music21.tie.Tie("start"), music21.tie.Tie("stop")

    def undo() -> None:
        nxt.pitch = old
        prev.tie = nxt.tie = None
    return undo


def inject_divisi(parts: list[music21.stream.Part], systems: list[list[int]], drng: random.Random) -> dict[
        str, object]:
    """A6 injection: same-stem chords across whole strips at the frozen mix (design section 4); returns the stats.

    Why it is shaped this way:
    * The chord-free decision and density are drawn per (voice, system) before anything else, from `drng` only, so
      they depend on the seed alone and every font render of a strip agrees (injection happens before render). The
      chord-free draw is lowered by EXPECTED_DENSITY_SHORT so that all plain strips (drawn chord-free plus strips
      undone for short density) together aim at P_CHORD_FREE_STRIP; `chord_free_strips` counts both kinds.
    * Sites: the duration class is drawn by `_deficit_weights` over A6_DURATIONS among the classes the strip still
      offers, then a site of that class, real notes before merged ones. (The plan's static A6_DURATIONS[c] /
      available[c] weights realised 53% quarters on bwv66.6.) Bach has few whole, half and dotted notes, so plain
      notes inside one bar may be merged (whole bar in 4/4 or 2/2; quarter+quarter, half+quarter, quarter+eighth at
      normal metric positions) into one note on the first pitch, which is then always chorded; labels come from the
      MEI, so they stay exact. Interval class (incl. triad) and member source are steered the same way toward
      A6_INTERVALS / P_TRIAD_A6 and P_FREE_MEMBER.
    * Members follow `_draw_members` (conductor rules, re-draws, crossing budget over the chord's whole span); a
      failed draw goes back to the pool up to MAX_REDRAWS times, then the site stays single. Failures are logged in
      `shortfall`, so the realised mix is measured, not assumed.
    * Accidental columns are never invented: while the piece is under ACCIDENTAL_COL_TARGET, chromatic sites weigh
      ACCIDENTAL_SITE_BOOST times more and a chromatic copied member is tried first. `free_new_accidentals` is a
      post-hoc audit on the final score (not the rule free_member used), and `induced_accidentals` counts original
      heads whose shown accidental changed because of the injection (reported, no gate).
    * A strip that cannot reach CHORD_DENSITY[0] is restored to plain (`density_short_keys`), so every strip is
      either plain or inside CHORD_DENSITY. Over-target duration classes are skipped only once the strip has reached
      that floor; below it the least over-target class is taken, so the duration skip does not empty strips.
    * A merge that would remove a head whose accidental an already placed free member uses is skipped
      (`skipped["merge_accidental_relied_on"]`), and so is a chord whose member would change that accidental
      (`skipped["member_overrides_relied_accidental"]`), so the post-hoc audit stays 0.
    * Whole-note chords have no stem; their entry in `stems` is STEMLESS so the list stays one entry per chord.
    * A6.4: before sites are listed, a chord strip gets synthetic barline ties (`_barline_tie_candidates`) for its
      share of the running TIE_CHORD_TARGET deficit, never past TIE_CHORD_CAP; a strip restored to plain loses them.
      `tie_sources` is one entry per chord column like `stems` ("native", "synth" or "").
    shortcut: tied notes are chorded only when TIES_ENABLED (both sides, same members); off until G1b passes ties.
    """
    stats: dict[str, collections.Counter[str]] = {k: collections.Counter() for k in
                                                   ("class", "duration", "steps", "skipped", "shortfall", "merged")}
    scalars: collections.Counter[str] = collections.Counter({k: 0 for k in (
        "accidental_cols", "ties", "crossing", "free", "copied", "chord_free_strips", "strips",
        "free_new_accidentals", "induced_accidentals", "chords_total", "merged_whole", "ledger2_members",
        "synth_ties", "synth_tie_pairs", "untied_repeat_pairs")})
    stems: dict[str, list[str]] = {}
    tie_sources: dict[str, list[str]] = {}
    synth_ids: set[int] = set()                  # ids of the start notes of synthetic ties
    synth_undo: dict[tuple[int, int], list[Callable[[], None]]] = {}
    repeats_of: dict[tuple[int, int], int] = {}
    tie_cols = expected_cols = 0.0               # piece running totals for the synthetic tie budget
    density_per_strip: list[float] = []
    chord_free_keys: list[str] = []
    density_short_keys: list[str] = []
    est_accidental_cols = 0      # predicted (chromatic head) columns, steers the site bias before makeAccidentals
    seconds_done = seconds_down = 0  # committed stemmed 2nds and how many are stems down (STEMS_DOWN_2ND_TARGET)
    free_placed: list[tuple[int, float, music21.pitch.Pitch, int]] = []   # committed free members, for merges
    baseline = [_accidental_display(part, fresh=True) for part in parts]
    # The harmony a template triad completes is the original four-part texture, not chords injected earlier.
    texture = _sounding(parts) if A7_ARM is not None else None
    audit: list[tuple[int, music21.stream.Measure, music21.chord.Chord, list[music21.pitch.Pitch], list[str],
                      int]] = []

    p_free = max(0.0, (P_CHORD_FREE_STRIP - EXPECTED_DENSITY_SHORT) / (1 - EXPECTED_DENSITY_SHORT))
    decisions: dict[tuple[int, int], float | None] = {}
    for vi in range(len(parts)):
        for si in range(len(systems)):
            decisions[(vi, si)] = None if drng.random() < p_free else drng.uniform(*CHORD_DENSITY)

    per_voice: list[tuple[list[music21.stream.Measure], list[int], list[tuple[list[_Site], int]]]] = []
    dur_names = list(A6_DURATIONS)
    bucket_names = [c for c, _, _ in A6_INTERVALS] + ["triad"]
    # Dyads renormalise over 1 - triad share (A7 3.1). A6 keeps exactly 1, not a float ratio that could flip a draw.
    dyad_scale = 1.0 if A7_ARM is None else (1 - P_TRIAD_A6) / sum(w for _, _, w in A6_INTERVALS)
    bucket_targets = [w * dyad_scale for _, _, w in A6_INTERVALS] + [P_TRIAD_A6]
    for vi, part in enumerate(parts):
        measures = list(part.getElementsByClass(music21.stream.Measure))
        meters: list[str | None] = []
        fifths: list[int] = []
        meter: str | None = None
        key_fifths = 0
        for m in measures:
            if m.timeSignature is not None:
                meter = m.timeSignature.ratioString
            for ks in m.getElementsByClass(music21.key.KeySignature):
                key_fifths = ks.sharps
            meters.append(meter)
            fifths.append(key_fifths)
        strips: list[tuple[list[_Site], int]] = []
        for si, system in enumerate(systems):
            skipped: collections.Counter[str] = collections.Counter()
            sites, columns = _strip_sites(measures, meters, fifths, system, skipped)
            density_d = decisions[(vi, si)]
            if density_d is not None and TIES_ENABLED and columns:
                native = sum(len(s.heads) for s in sites if s.kind == "tie")
                expected_cols += density_d * columns
                budget = TIE_CHORD_TARGET * expected_cols - tie_cols - native
                room = TIE_CHORD_CAP * expected_cols - tie_cols - native
                want = min(int(budget / 2 + drng.random()) if budget > 0 else 0, max(0, int(room // 2)))
                cands, _ = _barline_tie_candidates(measures, fifths, system)
                drng.shuffle(cands)
                taken: set[int] = set()
                undos: list[Callable[[], None]] = []
                for prev, nxt in cands:
                    if len(undos) >= want:
                        break
                    if id(prev) in taken or id(nxt) in taken:    # a note joins one synthetic tie at most
                        continue
                    taken.update((id(prev), id(nxt)))
                    undos.append(_apply_barline_tie(prev, nxt))
                    synth_ids.add(id(prev))
                synth_undo[(vi, si)] = undos
                tie_cols += native + 2 * len(undos)
                if undos:
                    skipped = collections.Counter()
                    sites, columns = _strip_sites(measures, meters, fifths, system, skipped)
                repeats_of[(vi, si)] = _barline_tie_candidates(measures, fifths, system)[1]
            strips.append((sites, columns))
            if decisions[(vi, si)] is not None:
                stats["skipped"].update(skipped)
        per_voice.append((measures, fifths, strips))

    injected_voices: list[int] = []
    for vi, part in enumerate(parts):
        voice = VOICES[vi]
        measures, fifths, strips = per_voice[vi]
        sounding = _sounding(parts)        # voices above are chords by now; their heads count as sounding
        injected: list[music21.chord.Chord] = []
        for si, (sites, columns) in enumerate(strips):
            if columns == 0:
                continue
            strip_key = f"{voice}|{si}"
            scalars["strips"] += 1
            density = decisions[(vi, si)]
            if density is None:
                scalars["chord_free_strips"] += 1
                chord_free_keys.append(strip_key)
                density_per_strip.append(0.0)
                continue
            records: list[dict[str, object]] = []
            undo: list[Callable[[], None]] = []
            cols, n_cols = 0, columns
            used: set[int] = set()         # ids of notes already chorded or merged away
            tries: collections.Counter[int] = collections.Counter()
            pool = list(sites)
            while cols / n_cols < density:
                pool = [s for s in pool if all(id(n) not in used for _, n in s.heads)]
                if not pool:
                    break
                done = scalars["chords_total"] + len(records)
                est = est_accidental_cols + sum(1 for r in records if r["est_acc"])
                boost = done == 0 or est / done < ACCIDENTAL_COL_TARGET
                ties = [s for s in pool if s.kind == "tie"]
                plain = [s for s in pool if s.kind != "tie"]
                use_ties = bool(ties) and (not plain or drng.random() < P_TIE_CHORD)
                choose_from = ties if use_ties else plain
                dur_done = collections.Counter(str(r["cls"]) for r in records) + stats["duration"]
                available = [c for c in dur_names if any(s.cls == c for s in choose_from)]
                # Ties skip the duration cap: they are supply-limited (~1% of chords), and capping them ended the
                # strip before any plain site was tried (A6.3 review).
                offered = available if use_ties else [
                    c for c in available if not (done and dur_done[c] / done > A6_DURATIONS[c] + DURATION_OVER_TARGET)]
                if not offered:
                    if not available or cols / n_cols >= CHORD_DENSITY[0]:
                        break                  # floor reached: stop rather than overfill an over-target class
                    # Below the floor (round 4 ruling): the least over-target class, so the strip is not undone.
                    offered = [min(available, key=lambda c: dur_done[c] / done - A6_DURATIONS[c])]
                cls_w = _deficit_weights([A6_DURATIONS[c] for c in offered], [dur_done[c] for c in offered], done)
                cls = drng.choices(offered, weights=cls_w)[0]
                of_cls = [s for s in choose_from if s.cls == cls]
                of_cls = [s for s in of_cls if s.kind != "merge"] or of_cls     # real notes before merged ones
                pending = [p for r in records for p in r["members"]]  # type: ignore[attr-defined]
                l2_done = scalars["ledger2_members"] + sum(_is_ledger2(_drawn_position(p, vi)) for p in pending)
                m_done = (scalars["free"] + scalars["copied"] + scalars["template"] + scalars["ledger"]
                          + len(pending))   # committed + this strip's, once
                site = drng.choices(of_cls, weights=[
                    (ACCIDENTAL_SITE_BOOST if boost and s.chromatic else 1.0)
                    * _ledger2_boost(voice, (A7_ARM is not None and _ledger_reachable(s.heads[0][1].pitch, vi))
                                     or not NEAR_EDGE_STEPS[0] < _drawn_position(s.heads[0][1].pitch, vi)
                                     < NEAR_EDGE_STEPS[1], l2_done, m_done)
                    for s in of_cls])[0]
                pool.remove(site)
                add_cols = len(site.heads) if site.kind == "tie" else 1
                add_n = 1 - len(site.heads) if site.kind == "merge" else 0
                if (cols + add_cols) / (n_cols + add_n) > CHORD_DENSITY[1]:
                    continue
                mi, base_note = site.heads[0]
                m = measures[mi]
                offset = float(m.elementOffset(base_note))
                t = float(m.offset) + offset
                t_end = t + sum(float(n.quarterLength) for _, n in site.heads)
                if site.kind == "merge" and _base_conflicts(base_note.pitch, vi, t, t_end, sounding):
                    stats["skipped"]["merge_base_conflict"] += 1
                    continue
                if site.kind == "merge":
                    removed = [(float(m.elementOffset(n)), n.pitch) for _, n in site.heads[1:]]
                    if _merge_drops_relied_accidental(removed, mi, free_placed + [
                            r_free for r in records for r_free in _free_members_of(r)]):
                        stats["skipped"]["merge_accidental_relied_on"] += 1
                        continue
                crossing = scalars["crossing"] + sum(1 for r in records if r["cross"])
                bucket_done = collections.Counter(str(r["bucket"]).split("_")[0] for r in records)
                for key_, count in stats["class"].items():
                    bucket_done[key_.split(":")[1].split("_")[0]] += count
                class_w = _deficit_weights(bucket_targets, [bucket_done[b] for b in bucket_names], done)
                strip_sources = [src for r in records for src in r["sources"]]  # type: ignore[attr-defined]
                copied_done = scalars["copied"] + strip_sources.count("copied")
                # Free/copied only on both sides: A7's template and ledger members are outside this mix (A6: identical).
                members_done = (scalars["free"] + scalars["copied"] + strip_sources.count("free")
                                + strip_sources.count("copied"))
                prefer_copied = copied_done < (1 - P_FREE_MEMBER) * (members_done + 1)
                cadence = _is_cadence(base_note, mi, len(measures))
                template_p = 0.0 if A7_ARM is None else min(1.0, TEMPLATE_P_BY_CLASS.get(site.cls, 0.0)
                                                             * TEMPLATE_VOICE_FACTOR[voice]
                                                             * (TEMPLATE_CADENCE_FACTOR if cadence else 1.0))
                drawn = _draw_members(base_note.pitch, mi, offset, t, t_end, vi, parts, sounding, fifths[mi], drng,
                                      class_w, prefer_copied, boost, crossing, done, site.kind == "merge",
                                      template_p, cadence, texture,
                                      A7_ARM is not None and l2_done < LEDGER2_MEMBER_TARGET * (m_done + 1),
                                      scalars["ledger_crossing"] + sum(1 for r in records if r["lcross"]))
                if isinstance(drawn, str):
                    stats["shortfall"][drawn] += 1
                    tries[id(site)] += 1
                    if tries[id(site)] < MAX_REDRAWS:
                        pool.append(site)          # scarce duration sites get another class, not lost
                    continue
                members, sources, bucket, cross, lcross = drawn
                placements = [(mi, offset)] if site.kind == "merge" else [
                    (hmi, float(measures[hmi].elementOffset(n))) for hmi, n in site.heads]
                if _member_overrides_relied_accidental(members, placements, free_placed + [
                        r_free for r in records for r_free in _free_members_of(r)]):
                    stats["skipped"]["member_overrides_relied_accidental"] += 1
                    continue
                pitches = [base_note.pitch] + members
                strip_2nds = [r["stem"] for r in records if r["second"]]
                seconds_n = seconds_done + len(strip_2nds)
                down_n = seconds_down + strip_2nds.count("down")
                # The first 2nd of a piece uses the plain draw: forcing it down biased by voice/position (round 5).
                # Counted as if this 2nd went up, so the piece share never ends under target (A6.3 review).
                force_down = seconds_n > 0 and down_n / (seconds_n + 1) < STEMS_DOWN_2ND_TARGET
                stem = STEMLESS if site.cls == "whole" else _stem_direction(pitches, vi, drng, force_down)
                common: dict[str, object] = {
                    "bucket": f"2nd_{stem}" if bucket == "2nd" else bucket, "stem": stem, "members": members,
                    "sources": sources, "cross": cross, "lcross": lcross, "fifths": fifths[mi],
                    "est_acc": any(_chromatic(p, fifths[mi]) for p in pitches), "tie": site.kind == "tie",
                    "synth_tie": site.kind == "tie" and id(base_note) in synth_ids,
                    # Dyads only: the gate's 2nd_up/2nd_down buckets; a triad holding a 2nd is a "triad" (A6.3 review).
                    "second": stem != STEMLESS and len(pitches) == 2 and _has_second(pitches, vi)}
                if site.kind == "merge":
                    old = [(float(m.elementOffset(n)), n) for _, n in site.heads]
                    chord = _make_chord(pitches, base_note, stem, merged_ql=t_end - t)
                    for _, n in old:
                        m.remove(n)
                    m.insert(offset, chord)
                    partner: music21.note.NotRest | None = None
                    old_beams = music21.beam.Beams()
                    if site.unbeam_offset is not None:
                        partner = next(x for x in m.getElementsByClass((music21.note.Note, music21.chord.Chord))
                                       if float(m.elementOffset(x)) == site.unbeam_offset)
                        old_beams = partner.beams
                        partner.beams = music21.beam.Beams()

                    def _undo_merge(m: music21.stream.Measure = m, chord: music21.chord.Chord = chord,
                                    old: list[tuple[float, music21.note.Note]] = old,
                                    partner: music21.note.NotRest | None = partner,
                                    old_beams: music21.beam.Beams = old_beams) -> None:
                        if partner is not None:
                            partner.beams = old_beams
                        m.remove(chord)
                        for off, n in old:
                            m.insert(off, n)
                    undo.append(_undo_merge)
                    records.append({**common, "t": t, "cls": site.cls, "chord": chord, "merge": site.merge,
                                    "mi": mi, "measure": m})
                else:
                    for k, (hmi, n) in enumerate(site.heads):
                        hm = measures[hmi]
                        chord = _make_chord(pitches, n, stem)
                        if site.kind == "tie":
                            chord.tie = music21.tie.Tie("start" if k == 0 else "stop")
                        t_head = float(hm.offset + hm.elementOffset(n))
                        hm.replace(n, chord)

                        def _undo_replace(hm: music21.stream.Measure = hm, chord: music21.chord.Chord = chord,
                                          n: music21.note.Note = n) -> None:
                            hm.replace(chord, n)
                        undo.append(_undo_replace)
                        records.append({**common, "t": t_head, "cls": _duration_class(n.duration), "chord": chord,
                                        "merge": "", "mi": hmi, "measure": hm})
                used.update(id(n) for _, n in site.heads)
                cols += add_cols
                n_cols += add_n
            if cols / n_cols < CHORD_DENSITY[0]:
                for fn in reversed(undo + synth_undo.get((vi, si), [])):
                    fn()
                stats["skipped"]["density_short"] += 1
                scalars["chord_free_strips"] += 1
                density_short_keys.append(strip_key)
                density_per_strip.append(0.0)
                continue
            density_per_strip.append(cols / n_cols)
            records.sort(key=lambda r: float(r["t"]))  # type: ignore[arg-type]
            stems[strip_key] = [str(r["stem"]) for r in records]
            tie_sources[strip_key] = ["synth" if r["synth_tie"] else "native" if r["tie"] else "" for r in records]
            scalars["synth_tie_pairs"] += len(synth_undo.get((vi, si), []))
            scalars["untied_repeat_pairs"] += repeats_of.get((vi, si), 0)
            seconds_done += sum(1 for r in records if r["second"])
            seconds_down += sum(1 for r in records if r["second"] and r["stem"] == "down")
            for r in records:
                members_r: list[music21.pitch.Pitch] = r["members"]  # type: ignore[assignment]
                sources_r: list[str] = r["sources"]  # type: ignore[assignment]
                stats["class"][f"{voice}:{r['bucket']}"] += 1
                stats["duration"][str(r["cls"])] += 1
                if r["bucket"] == "triad_template":   # placement mix of templates (design 3.1; A7 only)
                    stats.setdefault("template_duration", collections.Counter())[str(r["cls"])] += 1
                stats["steps"].update(f"{voice}:{_drawn_position(p, vi)}" for p in members_r)
                l2 = sum(_is_ledger2(_drawn_position(p, vi)) for p in members_r)
                scalars["ledger2_members"] += l2
                scalars.update(sources_r)
                scalars["crossing"] += int(bool(r["cross"]))
                if A7_ARM is not None:              # A6 summaries keep their keys
                    scalars["ledger_crossing"] += int(bool(r["lcross"]))
                scalars["ties"] += int(bool(r["tie"]))
                scalars["synth_ties"] += int(bool(r["synth_tie"]))
                if r["merge"]:
                    stats["merged"][str(r["merge"])] += 1
                    scalars["merged_whole"] += int(r["merge"] == "whole")
                est_accidental_cols += int(bool(r["est_acc"]))
                injected.append(r["chord"])  # type: ignore[arg-type]
                audit.append((int(r["mi"]), r["measure"], r["chord"], members_r, sources_r,  # type: ignore[arg-type]
                              int(r["fifths"])))  # type: ignore[call-overload]
                free_placed += _free_members_of(r)
            scalars["chords_total"] += len(records)
        if injected:
            part.makeAccidentals(inPlace=True, overrideStatus=True)
            scalars["accidental_cols"] += sum(1 for c in injected if any(
                p.accidental is not None and p.accidental.displayStatus for p in c.pitches))
            injected_voices.append(vi)
    for mi, m, chord, members, sources, fx in audit:      # post-hoc: the final score, not the rule that drew them
        in_force = bar_accidentals(mi, float(m.elementOffset(chord)), parts)
        # A tie continuation carries the tie start's accidental over the barline (choral-conductor 2026-10-22).
        tied_over = {n.pitch.nameWithOctave for n in chord.notes
                     if n.tie is not None and n.tie.type in ("stop", "continue")}
        for p, src in zip(members, sources):
            key_alter = _key_alter(fx, p.step)
            if src == "free" and p.nameWithOctave not in tied_over and int(p.alter) not in (
                    key_alter, in_force.get(f"{p.step}{p.octave}", key_alter)):
                scalars["free_new_accidentals"] += 1
    for vi in injected_voices:
        after = _accidental_display(parts[vi], fresh=False)
        scalars["induced_accidentals"] += sum(1 for k, shown in after.items()
                                              if k in baseline[vi] and baseline[vi][k] != shown)
    out: dict[str, object] = {k: dict(v) for k, v in stats.items()}
    out.update(scalars)
    out.update(stems=stems, tie_sources=tie_sources, density_per_strip=density_per_strip,
               chord_free_keys=sorted(chord_free_keys),
               density_short_keys=sorted(density_short_keys))
    return out


def _bar_ql(measure: music21.stream.Measure, meter: str | None) -> float | None:
    return float(music21.meter.TimeSignature(meter).barDuration.quarterLength) if meter else None


def _layerable(measure: music21.stream.Measure, bar_ql: float | None) -> bool:
    """One plain layer that fills the bar: no tuplet, grace note, existing voice, or chord stemmed down (a layered
    bar draws layer 1 stems up; a down-stemmed injected chord would change the stem the chord stats logged)."""
    items = list(measure.notesAndRests)
    if bar_ql is None or not items or measure.getElementsByClass(music21.stream.Voice):
        return False
    if any(n.duration.isGrace or n.duration.tuplets for n in items):
        return False
    if any(isinstance(n, music21.chord.Chord) and n.stemDirection == "down" for n in items):
        return False
    return abs(sum(float(n.quarterLength) for n in items) - bar_ql) < 1e-9


def _rhythm(measure: music21.stream.Measure) -> list[tuple[float, float, bool]]:
    return [(float(measure.elementOffset(n)), float(n.quarterLength), n.isRest) for n in measure.notesAndRests]


def _layer2_pitch(l1: music21.pitch.Pitch, mi: int, offset: float, t: float, t_end: float, vi: int,
                  parts: list[music21.stream.Part], sounding: list[list[tuple[float, float, music21.pitch.Pitch]]],
                  fifths: int, lrng: random.Random) -> music21.pitch.Pitch | None:
    """A layer-2 pitch at or below layer 1 and not below the next voice, from the pitches the texture sounds over
    [t, t_end), moved by octaves.

    Within the voice's divisi limits and the A1 drawn band; no cross-relation with another voice in the span, and no
    accidental the bar does not already have in force at that height (as free members)."""
    in_force = bar_accidentals(mi, offset, parts)
    span = _span_pitches(sounding, vi, t, t_end)
    lo_ps, hi_ps = (_ps(p) for p in DIVISI_MEMBER_LIMITS[VOICES[vi]])
    # Layer 2 never crosses below the next voice down (a soprano 2 under the alto reads as a different part).
    below = [p.ps for s, e, p in sounding[vi + 1] if s < t_end and e > t] if vi + 1 < len(sounding) else []
    lo_ps = max([lo_ps] + below)
    options: dict[str, tuple[music21.pitch.Pitch, float]] = {}
    for q in span + [l1]:
        if q.accidental is not None and q.accidental.alter not in (-1, 0, 1):
            continue
        for octave in range(q.octave - 2, q.octave + 3):
            c = copy.deepcopy(q)
            c.octave = octave
            w = LAYER2_INTERVAL_WEIGHTS.get(int(round(l1.ps - c.ps)))
            if w is None or abs(c.alter) > 1 or not lo_ps <= c.ps <= hi_ps:
                continue
            if not DIVISI_MEMBER_POSITIONS[0] <= _drawn_position(c, vi) <= DIVISI_MEMBER_POSITIONS[1]:
                continue
            if any(o.step == c.step and o.octave == c.octave and o.alter != c.alter for o in span):
                continue
            key_alter = _key_alter(fifths, c.step)
            if int(c.alter) != in_force.get(f"{c.step}{c.octave}", key_alter) and not any(
                    o.nameWithOctave == c.nameWithOctave for o in span):
                continue
            options.setdefault(c.nameWithOctave, (c, w))
    if not options:
        return None
    keys = sorted(options)
    return options[lrng.choices(keys, weights=[options[k][1] for k in keys])[0]][0]


def inject_layers(parts: list[music21.stream.Part], systems: list[list[int]], lrng: random.Random,
                  chord_stats: dict[str, object]) -> dict[str, int]:
    """A7 arm CL (design 3.2): a second layer in about LAYER_BAR_SHARE of the bars of chord-bearing strips.

    Layer 2 takes another SATB voice's rhythm in the same bar (or, LAYER_SAME_RHYTHM of the time, the voice's own
    rhythm: same-rhythm split stems), with pitches at or below layer 1 from the sounding texture. Layer 1 stems up,
    layer 2 down. LAYER_MID_ENTRY of layer bars start layer 2 with rests (entry mid-bar). Chord-free canary strips
    get no layers. Synthetic barline ties on layer-2 notes stay in their layer, or tie into a one-layer bar at the
    same pitch ("unis."), up to LAYER_TIE_TARGET of layer bars (never past LAYER_TIE_CAP). Runs after
    `inject_divisi` on its own RNG, so the chords are the ones arm C gets.
    """
    stats: collections.Counter[str] = collections.Counter({k: 0 for k in (
        "layer_bars", "layer_same_rhythm", "layer_mid_entry", "layer2_notes", "layer2_rests", "layer_chord_bars",
        "layer_ties_in_layer", "layer_ties_unis", "layer_attempts")})
    plain_strips = set(chord_stats.get("chord_free_keys", [])) | set(chord_stats.get("density_short_keys", []))  # type: ignore[arg-type]
    sounding = _sounding(parts)
    measures = [list(p.getElementsByClass(music21.stream.Measure)) for p in parts]
    meters: list[str | None] = []
    fifths: list[int] = []
    meter: str | None = None
    key_fifths = 0
    for m in measures[0]:
        if m.timeSignature is not None:
            meter = m.timeSignature.ratioString
        for ks in m.getElementsByClass(music21.key.KeySignature):
            key_fifths = ks.sharps
        meters.append(meter)
        fifths.append(key_fifths)
    layered: list[tuple[int, int, int]] = []           # (voice, system, measure index)
    for vi in range(len(parts)):
        for si, system in enumerate(systems):
            if f"{VOICES[vi]}|{si}" in plain_strips:
                continue
            # A quota per strip, filled from its bars in random order: a bar that cannot take a layer (tuplet, a
            # chord stemmed down, no donor) passes its turn to another bar instead of lowering the share.
            quota = int(LAYER_BAR_SHARE * len(system) + lrng.random())
            bars = list(system)
            lrng.shuffle(bars)
            for mi in bars:
                if quota == 0:
                    break
                stats["layer_attempts"] += 1
                reason = _add_layer(parts, measures, vi, mi, meters[mi], fifths[mi], sounding, lrng, stats)
                if reason:
                    stats[f"skip_{reason}"] += 1
                else:
                    layered.append((vi, si, mi))
                    quota -= 1
    # Probabilistic rounding on both, so a piece with ~3 layer bars still ties sometimes (int() of the cap was 0).
    want = min(int(LAYER_TIE_TARGET * len(layered) + lrng.random()), math.ceil(LAYER_TIE_CAP * len(layered)))
    order = list(layered)
    lrng.shuffle(order)
    for vi, si, mi in order:
        if stats["layer_ties_in_layer"] + stats["layer_ties_unis"] >= want:
            break
        system = systems[si]
        if mi == system[-1] or fifths[mi] != fifths[mi + 1]:
            continue
        kind = _layer_tie(measures[vi][mi], measures[vi][mi + 1], vi, mi, parts, sounding, fifths[mi])
        if kind:
            stats[f"layer_ties_{kind}"] += 1
    return dict(stats)


def _add_layer(parts: list[music21.stream.Part], measures: list[list[music21.stream.Measure]], vi: int, mi: int,
               meter: str | None, fifths: int, sounding: list[list[tuple[float, float, music21.pitch.Pitch]]],
               lrng: random.Random, stats: collections.Counter[str]) -> str:
    """Add layer 2 to one bar; returns "" or why the bar stayed one layer."""
    m = measures[vi][mi]
    bar_ql = _bar_ql(m, meter)
    if not _layerable(m, bar_ql):
        return "not_layerable"
    same = lrng.random() < LAYER_SAME_RHYTHM
    if same:
        donor = m
    else:
        own = _rhythm(m)
        donors = [measures[vj][mi] for vj in range(len(parts)) if vj != vi
                  and _layerable(measures[vj][mi], bar_ql) and _rhythm(measures[vj][mi]) != own]
        if not donors:
            return "no_donor"
        donor = lrng.choice(donors)
    events = [(float(donor.elementOffset(n)), n) for n in donor.notesAndRests]
    rest_until = 0
    if lrng.random() < LAYER_MID_ENTRY:
        # Cut only where no beam runs on, so layer 2's remaining beams stay whole.
        cuts = [k for k in range(1, len(events)) if events[k][0] <= bar_ql / 2
                and not any(b.type in ("start", "continue") for b in events[k - 1][1].beams.beamsList)]
        if cuts:
            rest_until = lrng.choice(cuts)
    layer1 = [(float(m.elementOffset(n)), n) for n in m.notesAndRests]
    new: list[tuple[float, music21.note.GeneralNote]] = []
    for k, (off, src) in enumerate(events):
        ql = float(src.quarterLength)
        if src.isRest or k < rest_until:
            new.append((off, music21.note.Rest(quarterLength=ql)))
            continue
        over = [n for o, n in layer1 if o <= off < o + float(n.quarterLength) and not n.isRest]
        if not over:
            return "layer1_rest"                         # no layer-1 pitch to sit under
        l1 = min(over[0].pitches, key=lambda p: p.ps)
        t = float(m.offset) + off
        p = _layer2_pitch(l1, mi, off, t, t + ql, vi, parts, sounding, fifths, lrng)
        if p is None:
            return "no_pitch"
        n = music21.note.Note(p, quarterLength=ql)
        n.beams = copy.deepcopy(src.beams) if k >= rest_until else music21.beam.Beams()
        n.stemDirection = "down"
        new.append((off, n))
    if not any(isinstance(n, music21.note.Note) for _, n in new):
        return "no_layer2_note"
    v1, v2 = music21.stream.Voice(id="1"), music21.stream.Voice(id="2")
    for off, n in layer1:
        m.remove(n)
        if not n.isRest:
            n.stemDirection = "up"
        v1.insert(off, n)
    for off, n in new:
        v2.insert(off, n)
    m.insert(0, v1)
    m.insert(0, v2)
    stats["layer_bars"] += 1
    stats["layer_same_rhythm"] += int(same)
    stats["layer_mid_entry"] += int(rest_until > 0)
    stats["layer2_notes"] += sum(isinstance(n, music21.note.Note) for _, n in new)
    stats["layer2_rests"] += sum(n.isRest for _, n in new)
    stats["layer_chord_bars"] += int(any(isinstance(n, music21.chord.Chord) for _, n in layer1))
    return ""


def _layer_tie(m: music21.stream.Measure, nxt: music21.stream.Measure, vi: int, mi: int,
               parts: list[music21.stream.Part], sounding: list[list[tuple[float, float, music21.pitch.Pitch]]],
               fifths: int) -> str:
    """Tie a layered bar's last layer-2 note over the barline: into the next bar's layer 2 (the note there takes the
    pitch), or into a one-layer bar whose first note has the same pitch ("unis."). Returns the kind or ""."""
    voices = {v.id: v for v in m.getElementsByClass(music21.stream.Voice)}
    last = list(voices["2"].notesAndRests) if "2" in voices else []
    if not last or not isinstance(last[-1], music21.note.Note) or last[-1].tie is not None:
        return ""
    end = last[-1]
    nvoices = {v.id: v for v in nxt.getElementsByClass(music21.stream.Voice)}
    if "2" in nvoices:
        first = list(nvoices["2"].notesAndRests)
        if not first or not isinstance(first[0], music21.note.Note) or first[0].tie is not None or first[0].offset:
            return ""
        over = [n for n in nvoices["1"].notesAndRests if n.offset == 0 and not n.isRest]
        if not over or end.pitch.ps > min(p.ps for p in over[0].pitches):
            return ""
        t = float(nxt.offset)
        if any(o.step == end.pitch.step and o.octave == end.pitch.octave and o.alter != end.pitch.alter
               for o in _span_pitches(sounding, vi, t, t + float(first[0].quarterLength))):
            return ""
        first[0].pitch = copy.deepcopy(end.pitch)
        end.tie, first[0].tie = music21.tie.Tie("start"), music21.tie.Tie("stop")
        return "in_layer"
    heads = list(nxt.notesAndRests)
    if not (heads and isinstance(heads[0], music21.note.Note) and heads[0].tie is None
            and nxt.elementOffset(heads[0]) == 0 and _plain(heads[0])):
        return ""
    # "unis.": layer 2 takes the next bar's first pitch, if that stays under layer 1 and above the voice below.
    target = heads[0].pitch
    off = float(voices["2"].elementOffset(end))
    t, t_end = float(m.offset) + off, float(m.offset) + off + float(end.quarterLength)
    over = [n for n in voices["1"].notesAndRests if not n.isRest
            and float(voices["1"].elementOffset(n)) <= off < float(voices["1"].elementOffset(n)) + float(n.quarterLength)]
    below = [p.ps for s, e, p in sounding[vi + 1] if s < t_end and e > t] if vi + 1 < len(sounding) else []
    if not over or target.ps > min(p.ps for p in over[0].pitches) or (below and target.ps < max(below)):
        return ""
    if any(o.step == target.step and o.octave == target.octave and o.alter != target.alter
           for o in _span_pitches(sounding, vi, t, t_end)):
        return ""
    end.pitch = copy.deepcopy(target)
    end.tie, heads[0].tie = music21.tie.Tie("start"), music21.tie.Tie("stop")
    return "unis"


def build_piece(path: Path, composer: str, rng: random.Random, work_dir: Path,
                inject: Callable[[list[music21.stream.Part]], None] | None = None) -> tuple[PiecePlan, str]:
    """Return the plan and the final MEI text; raises ConversionError/ValueError with the skip reason.

    `inject` (divisi arm) edits the parts after the constructed key change and before export; it must not touch
    `rng`, so the plan stays the one the piece gets without it."""
    piece_id = f"{composer}_{path.stem}".replace(" ", "_")
    plan = PiecePlan(piece_id=piece_id, source=str(path), composer=composer)
    score = music21.converter.parse(str(path))
    if not isinstance(score, music21.stream.Score):
        raise ValueError("not a score")
    parts = _satb_order(score)
    if parts is None:
        raise ValueError(f"not 4-part SATB ({len(score.parts)} parts)")
    for part in parts:
        if part.recurse().getElementsByClass(music21.chord.Chord):
            raise ConversionError("chord in a voice")
        if part.recurse().getElementsByClass(music21.stream.Voice):
            raise ConversionError("multiple voices in a part")
    _normalise_clefs(parts)
    problem = _range_problem(parts)
    if problem:
        raise ValueError(problem)
    n_source = len(parts[0].getElementsByClass(music21.stream.Measure))
    if n_source < 4:
        raise ValueError("fewer than 4 measures")

    key_at = rng.randrange(2, n_source) if rng.random() < P_KEY_CHANGE else None
    if key_at is not None:
        backup = copy.deepcopy(score)
        info = _modulate(parts, key_at, rng)
        at_break = rng.random() < P_AT_BREAK
        if info is not None and _range_problem(parts) is None:
            plan.key_change = {**info, "source_measure_index": key_at, "at_break": at_break}
        else:
            # The modulation pushed a voice out of range: keep the piece, drop the constructed key change.
            score = backup
            restored = _satb_order(score)
            if restored is None:
                raise ValueError("SATB order lost after restoring the unmodulated copy")
            parts = restored
            key_at = None
    if inject is not None:
        inject(parts)

    xml_path = work_dir / f"{piece_id}.musicxml"
    score.write("musicxml", fp=str(xml_path))
    tk = verovio.toolkit()
    if not tk.loadFile(str(xml_path)):
        raise ValueError("verovio could not load the MusicXML")
    root = ET.fromstring(tk.getMEI({"scoreBased": True}))
    score_el = root.find(f".//{{{MEI_NS}}}score")
    if score_el is None:
        raise ValueError("no <score> in Verovio MEI")
    for parent in list(score_el.iter()):
        for child in list(parent):
            if child.tag in (f"{{{MEI_NS}}}sb", f"{{{MEI_NS}}}pb"):
                parent.remove(child)
    plan.source_fixes = _normalise_control_events(score_el)
    parents = {c: p for p in score_el.iter() for c in p}
    measures = list(score_el.iter(f"{{{MEI_NS}}}measure"))
    if len(measures) != n_source:
        raise ValueError(f"measure count music21 {n_source} vs MEI {len(measures)}")
    key_measure = measures[key_at] if plan.key_change is not None and key_at is not None else None

    main_def = score_el.find(f"{{{MEI_NS}}}scoreDef")
    meter0 = _initial_meter(main_def) if main_def is not None else None
    family = next((f for f in METER_FAMILIES if meter0 in f), None)
    meter_measure: ET.Element | None = None
    revert_measure: ET.Element | None = None
    if family is not None and rng.random() < P_METER_CHANGE:
        new_meter = rng.choice([m for m in family if m != meter0])
        at = rng.randrange(1, len(measures) - 1)
        meter_measure = measures[at]
        _insert_before_measure(meter_measure, parents, ET.Element(f"{{{MEI_NS}}}scoreDef", _meter_attrs(new_meter)),
                               before_defs=False)
        plan.meter_change = {"from": list(meter0), "to": list(new_meter), "at_break": rng.random() < P_AT_BREAK}
        if rng.random() < P_METER_REVERT and at + 2 < len(measures):
            revert_measure = measures[rng.randrange(at + 2, len(measures))]
            _insert_before_measure(revert_measure, parents,
                                   ET.Element(f"{{{MEI_NS}}}scoreDef", _meter_attrs(meter0)), before_defs=False)
            plan.meter_change["reverts"] = True
    parents = {c: p for p in score_el.iter() for c in p}

    multirest_measure: ET.Element | None = None
    if rng.random() < P_MULTIREST:
        num = rng.choice(MULTIREST_LENGTHS)
        intro = rng.random() < 0.5
        anchor = measures[0] if intro else measures[rng.randrange(2, len(measures))]
        multirest_measure = ET.Element(f"{{{MEI_NS}}}measure", {"n": "mr", XML_ID: "mrest_m"})
        for s in range(1, 5):
            staff = ET.SubElement(multirest_measure, f"{{{MEI_NS}}}staff", {"n": str(s), XML_ID: f"mrest_s{s}"})
            layer = ET.SubElement(staff, f"{{{MEI_NS}}}layer", {"n": "1", XML_ID: f"mrest_l{s}"})
            ET.SubElement(layer, f"{{{MEI_NS}}}multiRest", {"num": str(num), XML_ID: f"mrest_r{s}"})
        # Before any key/meter change leading into the anchor, so the change still lands on the anchor bar.
        _insert_before_measure(anchor, parents, multirest_measure, before_defs=not intro)
        plan.multirest = {"num": num, "intro": intro, "at_break": (not intro) and rng.random() < P_AT_BREAK}
    parents = {c: p for p in score_el.iter() for c in p}

    measures = list(score_el.iter(f"{{{MEI_NS}}}measure"))
    index = {id(m): i for i, m in enumerate(measures)}
    force: set[int] = set()
    forbid: set[int] = set()
    for event, el in ((plan.key_change, key_measure), (plan.meter_change, meter_measure),
                      (plan.multirest, multirest_measure)):
        if event is None or el is None:
            continue
        i = index[id(el)]
        if i == 0:
            continue
        event["measure_index"] = i
        (force if event.get("at_break") else forbid).add(i)
    if revert_measure is not None and plan.meter_change is not None:
        plan.meter_change["revert_measure_index"] = index[id(revert_measure)]
    plan.systems = _layout(len(measures), force, forbid, rng)
    plan.pages = [list(range(i, min(i + SYSTEMS_PER_PAGE, len(plan.systems))))
                  for i in range(0, len(plan.systems), SYSTEMS_PER_PAGE)]
    for s, sys_measures in enumerate(plan.systems[1:], start=1):
        tag = "pb" if s % SYSTEMS_PER_PAGE == 0 else "sb"
        _insert_before_measure(measures[sys_measures[0]], parents, ET.Element(f"{{{MEI_NS}}}{tag}"),
                               before_defs=True)
    if len(plan.systems) == 1:
        # With breaks="encoded" and no <sb> at all, Verovio lays the piece out automatically; a multirest then
        # pushed the last planned measure onto a second system (palestrina_Gloria_70_c). A leading <sb> makes the
        # one-system plan an encoded layout like every other piece.
        _insert_before_measure(measures[0], parents, ET.Element(f"{{{MEI_NS}}}sb"), before_defs=True)
    plan.measures = len(measures)
    plan.measure_n = [m.attrib.get("n", "") for m in measures]
    return plan, ET.tostring(root, encoding="unicode")


def build_divisi(path: Path, composer: str, work_dir: Path, inject_seed: str = "divisi") -> tuple[
        PiecePlan, str, dict[str, object]]:
    """Two-pass divisi build (ml-cv-lead 2026-10-15): pass 1 is the normal build, which fixes the systems; chords are
    placed per system from those; pass 2 rebuilds from a fresh Phase 1 stream with the injection hook.

    The layout must come out identical, since the hook never touches the Phase 1 stream. A difference means it did,
    so it raises RuntimeError (a hard stop for the whole run, not a skipped piece). `inject_seed` "divisi" reproduces
    the corpus seed string `divisi:<piece>`; test renders use other seeds on the same layout. Strip keys in the stats
    (`stems`, `chord_free_keys`, `density_short_keys`) are prefixed with the output piece id, as `<piece>|<voice>|<system>`."""
    piece_id = f"{composer}_{path.stem}".replace(" ", "_")
    base, _ = build_piece(path, composer, random.Random(f"phase1:{piece_id}"), work_dir)
    # plan.systems index MEI measures, which include a constructed multirest ("mr"); music21 measures do not. A
    # multirest-only system stays as an empty list so system indices match plan.systems.
    rank = {mei_i: r for r, mei_i in enumerate(i for i, n in enumerate(base.measure_n) if n != "mr")}
    systems = [[rank[i] for i in sys_ if i in rank] for sys_ in base.systems]
    drng = random.Random(f"{inject_seed}:{piece_id}")
    stats: dict[str, object] = {}

    def inject(parts: list[music21.stream.Part]) -> None:
        stats.update(inject_divisi(parts, systems, drng))
        if A7_ARM == "CL":   # own RNG: arm C and arm CL get the same chords
            stats["layers"] = inject_layers(parts, systems, random.Random(f"{inject_seed}-layers:{piece_id}"), stats)

    plan, mei_text = build_piece(path, composer, random.Random(f"phase1:{piece_id}"), work_dir, inject)
    if (plan.systems, plan.pages, plan.measure_n) != (base.systems, base.pages, base.measure_n):
        raise RuntimeError(f"{piece_id}: divisi pass 2 layout differs from pass 1")
    plan.piece_id = piece_id + DIVISI_SUFFIX
    stems: dict[str, list[str]] = stats["stems"]  # type: ignore[assignment]
    stats["stems"] = {f"{plan.piece_id}|{k}": v for k, v in stems.items()}
    sources: dict[str, list[str]] = stats["tie_sources"]  # type: ignore[assignment]
    stats["tie_sources"] = {f"{plan.piece_id}|{k}": v for k, v in sources.items()}
    stats["chord_free_keys"] = [f"{plan.piece_id}|{k}" for k in stats["chord_free_keys"]]  # type: ignore[attr-defined]
    stats["density_short_keys"] = [f"{plan.piece_id}|{k}"  # type: ignore[attr-defined]
                                   for k in stats["density_short_keys"]]
    return plan, mei_text, stats


def check_labels(mei_path: Path, plan: PiecePlan) -> None:
    """Every staff must convert and split into exactly the planned systems, or the piece is dropped."""
    for s in range(1, 5):
        systems = split_systems(convert_staff(mei_path, str(s), dialect="verovio"))
        if len(systems) != len(plan.systems):
            raise ValueError(f"staff {s}: {len(systems)} label systems vs {len(plan.systems)} planned")
        plan.tokens_per_voice[VOICES[s - 1]] = sum(len(t) for t in systems)


def missing_pieces(requested: set[str], log: list[dict[str, object]]) -> tuple[list[str], dict[str, str]]:
    """(requested pieces not built, reason per skipped piece).

    A requested piece is missing unless the log says "included": one never reached AND one the build skipped
    (unsupported source, ConversionError). Why: a skipped test-half piece must not shrink the test set unseen.
    """
    built = {str(e["piece_id"]) for e in log if e["status"] == "included"}
    skipped = {str(e["piece_id"]): str(e.get("reason", "")) for e in log if e["status"] != "included"}
    return sorted(requested - built), skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--composers", default="bach,palestrina")
    parser.add_argument("--limit", type=int, default=0, help="max source files per composer (0 = all)")
    parser.add_argument("--pieces", default="", help="comma-separated piece ids to rebuild (default: all); the "
                        "log is then written to corpus_log_pieces.json so the full build's log is kept")
    parser.add_argument("--divisi", type=Path, default=None, metavar="PHASE2_MANIFEST",
                        help="divisi arm: build <piece>__divisi for every piece in this Phase 2 manifest, keeping its "
                        "split; use a separate --out, the Phase 1 corpus is never rewritten")
    parser.add_argument("--divisi-seed", default="divisi", help="injection seed prefix (corpus: divisi; test "
                        "renders: divisi-t1..t3); the layout never depends on it")
    parser.add_argument("--ties", action="store_true", help="sample builds only: chord tied notes (TIES_ENABLED); the "
                        "committed default stays off until G1b passes the tied-chord case")
    parser.add_argument("--a7", choices=("C", "CL"), help="divisi A7 arm (design section 3): C = chords, CL = chords + "
                        "layers; needs --divisi and a divisi-a7* seed (A6 seeds are not reused, design 12)")
    args = parser.parse_args()
    global TIES_ENABLED
    TIES_ENABLED = TIES_ENABLED or args.ties
    if args.a7:
        if args.divisi is None or not args.divisi_seed.startswith("divisi-a7"):
            raise SystemExit("--a7 needs --divisi and a --divisi-seed starting with divisi-a7")
        apply_a7(args.a7)
    corpus_dir = args.out / "corpus"
    work_dir = args.out / "work"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, args.pieces.split(",")))
    split_of: dict[str, str] = {}
    if args.divisi is not None:
        for line in args.divisi.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if split_of.setdefault(row["piece"], row["split"]) != row["split"]:
                raise SystemExit(f"{row['piece']} is in both splits of {args.divisi}")
        only = (only or set(split_of)) & set(split_of)
    totals: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    scalar_totals: collections.Counter[str] = collections.Counter()
    list_totals: dict[str, list[object]] = collections.defaultdict(list)
    stems_all: dict[str, list[str]] = {}
    tie_sources_all: dict[str, list[str]] = {}
    log: list[dict[str, object]] = []
    t0 = time.time()
    for composer in args.composers.split(","):
        paths = sorted(music21.corpus.getComposer(composer), key=str)
        paths = [Path(str(p)) for p in paths if Path(str(p)).suffix in (".mxl", ".xml", ".musicxml", ".krn")]
        if args.limit:
            paths = paths[: args.limit]
        for i, path in enumerate(paths):
            piece_id = f"{composer}_{path.stem}".replace(" ", "_")
            if only and piece_id not in only:
                continue
            rng = random.Random(f"phase1:{piece_id}")
            entry: dict[str, object] = {"piece_id": piece_id, "source": str(path), "composer": composer}
            out_id = piece_id + DIVISI_SUFFIX if args.divisi is not None else piece_id
            try:
                extra: dict[str, object] = {}
                if args.divisi is not None:
                    plan, mei_text, stats = build_divisi(path, composer, work_dir, args.divisi_seed)
                    extra = {"split": split_of[piece_id], "divisi": stats}
                else:
                    plan, mei_text = build_piece(path, composer, rng, work_dir)
                mei_path = corpus_dir / f"{out_id}.mei"
                mei_path.write_text(mei_text, encoding="utf-8")
                check_labels(mei_path, plan)
                if args.divisi is not None:
                    for k, v in stats.items():
                        if k == "stems":
                            stems_all.update(v)  # type: ignore[arg-type]
                        elif k == "tie_sources":
                            tie_sources_all.update(v)  # type: ignore[arg-type]
                        elif isinstance(v, dict):
                            totals[k].update(v)
                        elif isinstance(v, list):
                            list_totals[k] += v
                        else:
                            scalar_totals[k] += int(v)  # type: ignore[call-overload]
                (corpus_dir / f"{out_id}.plan.json").write_text(json.dumps({**asdict(plan), **extra}, indent=1),
                                                                encoding="utf-8")
                entry.update(status="included", systems=len(plan.systems), key_change=plan.key_change is not None,
                             meter_change=plan.meter_change is not None, multirest=plan.multirest is not None,
                             **extra)
            except ConversionError as exc:
                entry.update(status="skipped", reason=f"unsupported: {exc}")
                (corpus_dir / f"{out_id}.mei").unlink(missing_ok=True)
            except (ValueError, music21.exceptions21.Music21Exception) as exc:
                entry.update(status="skipped", reason=str(exc)[:200])
                (corpus_dir / f"{out_id}.mei").unlink(missing_ok=True)
            log.append(entry)
            if i % 25 == 0:
                print(f"{composer} {i}/{len(paths)} {time.time() - t0:.0f}s {entry['status']} "
                      f"{entry.get('reason', '')}", flush=True)
    log_name = "corpus_log_pieces.json" if only and args.divisi is None else "corpus_log.json"
    (args.out / log_name).write_text(json.dumps(log, indent=1), encoding="utf-8")
    included = sum(1 for e in log if e["status"] == "included")
    print(f"included {included} / {len(log)}")
    if args.divisi is not None:
        missing, skipped = missing_pieces(only, log)
        realised: dict[str, object] = {k: dict(v) for k, v in totals.items()}
        realised.update(scalar_totals)
        summary = {"pieces_missing_from_build": missing, "skipped_pieces": skipped, "seed": args.divisi_seed,
                   "realised": realised, **list_totals, "stems": stems_all, "tie_sources": tie_sources_all}
        (args.out / "divisi_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(json.dumps(realised, indent=1))


if __name__ == "__main__":
    main()
