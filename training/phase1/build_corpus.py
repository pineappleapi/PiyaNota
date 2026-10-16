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
* `--divisi` (divisi arm, docs/decisions/piya-106-divisi-arm-freeze.md section 3) builds `<piece>__divisi` copies with
  same-stem chords injected from a separate RNG; without it the output is byte-identical to before.

Usage: python training/phase1/build_corpus.py --out D:/PiyaNota-training/data/phase1_renders [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
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
# Divisi arm (docs/decisions/piya-106-divisi-arm-freeze.md section 3). Generic intervals per class, frozen weights.
DIVISI_INTERVALS: tuple[tuple[str, frozenset[int], float], ...] = (
    ("3rd", frozenset({3}), 0.35), ("6th", frozenset({6}), 0.25), ("8ve", frozenset({8}), 0.20),
    ("4th5th", frozenset({4, 5}), 0.10), ("2nd", frozenset({2}), 0.10))
DIVISI_GENERICS: frozenset[int] = frozenset().union(*(g for _, g, _ in DIVISI_INTERVALS))
# (1, 4) gave a chordnote share of 17.5% on the full build, above the 6-14% gate; freeze section 3 allows only the
# span length to change (2026-10-16). (1, 2) straddled 14% in both estimates, (1, 1) did not.
DIVISI_SPAN_BARS = (1, 1)
DIVISI_MAX_SEMITONES = 12
# Old VOCAB has all three accidentals and the common note shapes only here; a member outside it made an OOV
# accidental or head token and the guard quarantined the strip (smoke 2026-10-15, freeze Amendment A1).
DIVISI_MEMBER_POSITIONS = (-3, 12)
P_TRIAD = 0.05
DIVISI_SUFFIX = "__divisi"


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
    """Per voice, (start, end, pitch) of every note in quarter lengths from the piece start."""
    out: list[list[tuple[float, float, music21.pitch.Pitch]]] = []
    for part in parts:
        spans = []
        for m in part.getElementsByClass(music21.stream.Measure):
            for n in m.getElementsByClass(music21.note.Note):
                start = float(m.offset + n.offset)
                spans.append((start, start + float(n.quarterLength), n.pitch))
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


def inject_divisi(parts: list[music21.stream.Part], systems: list[list[int]], drng: random.Random) -> dict[
        str, object]:
    """Turn notes into same-stem chords that double another voice (freeze section 3); returns the realised stats.

    One span of DIVISI_SPAN_BARS bars per voice-system, plus each voice's final note. The interval class is drawn first by the
    frozen weights; when no other voice offers that class at the onset, the onset stays single (no redraw), so the
    realised mix is logged, not assumed. Uses only `drng`, never the Phase 1 stream.
    shortcut: tied, grace and tuplet notes are never chorded (counted as skipped), so the converter needs no tied or
    tuplet chord path; real tied divisi is then unseen in training (freeze section 1 known-lost).
    """
    sounding = _sounding(parts)
    stats: dict[str, collections.Counter[str]] = {k: collections.Counter() for k in
                                                   ("class", "skipped", "onsets", "chords", "triads")}
    names = [c for c, _, _ in DIVISI_INTERVALS]
    weights = [w for _, _, w in DIVISI_INTERVALS]
    for vi, part in enumerate(parts):
        measures = list(part.getElementsByClass(music21.stream.Measure))
        chosen: list[int] = []
        for system in systems:
            length = min(drng.randint(*DIVISI_SPAN_BARS), len(system))
            start = drng.randrange(len(system) - length + 1)
            chosen += system[start:start + length]
        targets = [n for i in chosen for n in measures[i].getElementsByClass(music21.note.Note)]
        last = list(part.recurse().getElementsByClass(music21.note.Note))[-1:]
        targets += [n for n in last if all(n is not t for t in targets)]   # music21 `in` compares by value
        for n in targets:
            voice = VOICES[vi]
            stats["onsets"][voice] += 1
            if n.duration.isGrace or n.duration.tuplets or n.tie is not None:
                stats["skipped"]["grace" if n.duration.isGrace else "tuplet" if n.duration.tuplets else "tie"] += 1
                continue
            m = n.getContextByClass(music21.stream.Measure)
            t = float(m.offset + n.getOffsetBySite(m))
            others = [p for vj, spans in enumerate(sounding) if vj != vi for s, e, p in spans if s <= t < e]
            cls = drng.choices(range(len(names)), weights=weights)[0]
            pool = _divisi_candidates(n.pitch, [n.pitch], others, vi, DIVISI_INTERVALS[cls][1])
            if not pool:
                stats["skipped"]["no_candidate"] += 1
                continue
            members = [n.pitch, drng.choice(pool)]
            if drng.random() < P_TRIAD:
                third = _divisi_candidates(n.pitch, members, others, vi, DIVISI_GENERICS)
                if third:
                    members.append(drng.choice(third))
                    stats["triads"][voice] += 1
            chord = music21.chord.Chord([copy.deepcopy(p) for p in members])
            chord.duration = copy.deepcopy(n.duration)
            chord.beams = copy.deepcopy(n.beams)
            chord.expressions = list(n.expressions)
            chord.articulations = list(n.articulations)
            chord.lyrics = list(n.lyrics)
            chord.stemDirection = n.stemDirection
            m.replace(n, chord)
            stats["class"][f"{voice}:{names[cls]}"] += 1
            stats["chords"][voice] += 1
        if stats["chords"][VOICES[vi]]:
            part.makeAccidentals(inPlace=True, overrideStatus=True)
    return {k: dict(v) for k, v in stats.items()}


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


def build_divisi(path: Path, composer: str, work_dir: Path) -> tuple[PiecePlan, str, dict[str, object]]:
    """Two-pass divisi build (ml-cv-lead 2026-10-15): pass 1 is the normal build, which fixes the systems; spans are
    chosen per system from those; pass 2 rebuilds from a fresh Phase 1 stream with the injection hook.

    The layout must come out identical, since the hook never touches the Phase 1 stream. A difference means it did,
    so it raises RuntimeError (a hard stop for the whole run, not a skipped piece)."""
    piece_id = f"{composer}_{path.stem}".replace(" ", "_")
    base, _ = build_piece(path, composer, random.Random(f"phase1:{piece_id}"), work_dir)
    # plan.systems index MEI measures, which include a constructed multirest ("mr"); music21 measures do not.
    rank = {mei_i: r for r, mei_i in enumerate(i for i, n in enumerate(base.measure_n) if n != "mr")}
    systems = [s for s in ([rank[i] for i in sys_ if i in rank] for sys_ in base.systems) if s]
    drng = random.Random(f"divisi:{piece_id}")
    stats: dict[str, object] = {}
    plan, mei_text = build_piece(path, composer, random.Random(f"phase1:{piece_id}"), work_dir,
                                 lambda parts: stats.update(inject_divisi(parts, systems, drng)))
    if (plan.systems, plan.pages, plan.measure_n) != (base.systems, base.pages, base.measure_n):
        raise RuntimeError(f"{piece_id}: divisi pass 2 layout differs from pass 1")
    plan.piece_id = piece_id + DIVISI_SUFFIX
    return plan, mei_text, stats


def check_labels(mei_path: Path, plan: PiecePlan) -> None:
    """Every staff must convert and split into exactly the planned systems, or the piece is dropped."""
    for s in range(1, 5):
        systems = split_systems(convert_staff(mei_path, str(s), dialect="verovio"))
        if len(systems) != len(plan.systems):
            raise ValueError(f"staff {s}: {len(systems)} label systems vs {len(plan.systems)} planned")
        plan.tokens_per_voice[VOICES[s - 1]] = sum(len(t) for t in systems)


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
    args = parser.parse_args()
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
                    plan, mei_text, stats = build_divisi(path, composer, work_dir)
                    extra = {"split": split_of[piece_id], "divisi": stats}
                    for k, v in stats.items():
                        totals[k].update(v)  # type: ignore[arg-type]
                else:
                    plan, mei_text = build_piece(path, composer, rng, work_dir)
                mei_path = corpus_dir / f"{out_id}.mei"
                mei_path.write_text(mei_text, encoding="utf-8")
                check_labels(mei_path, plan)
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
        missing = sorted(set(split_of) - {str(e["piece_id"]) for e in log})
        summary = {"pieces_missing_from_build": missing, "realised": {k: dict(v) for k, v in totals.items()}}
        (args.out / "divisi_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(json.dumps(summary["realised"], indent=1))


if __name__ == "__main__":
    main()
