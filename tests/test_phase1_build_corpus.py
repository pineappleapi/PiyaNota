"""Tests for the Phase 1 corpus normalisation (PIYA-106): what reaches Verovio must be describable by the labels.

Repeats are a known limitation (docs/bug-tracker.md): no repeat token exists, so no rpt* barline may be rendered.
"""

import json
import random
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "phase1"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
import music21  # noqa: E402
import build_corpus  # noqa: E402
from build_corpus import (MEI_NS, _normalise_clefs, _normalise_control_events, _satb_order,  # noqa: E402
                          assert_no_repeats, bar_accidentals, build_divisi, check_labels, free_member, inject_divisi, member_ok)
from music_to_agnostic import convert_staff, split_systems  # noqa: E402

SCORE_DEF = ('<scoreDef meter.count="4" meter.unit="4"><staffGrp><staffDef n="1" lines="5" clef.shape="G" '
             'clef.line="2"/></staffGrp></scoreDef>')


def _score(measures: str, extra: str = "") -> ET.Element:
    return ET.fromstring(f'<score xmlns="{MEI_NS}">{SCORE_DEF}<section>{measures}{extra}</section></score>')


def _measure(n: int, attrs: str = "", note_id: str = "") -> str:
    ident = f' xml:id="{note_id}"' if note_id else ""
    return (f'<measure n="{n}"{attrs}><staff n="1"><layer n="1"><note{ident} pname="c" oct="5" dur="1"/>'
            '</layer></staff></measure>')


def test_repeats_become_double_or_plain_barlines() -> None:
    score = _score(_measure(1, ' left="rptstart"') + _measure(2, ' right="rptend"') + _measure(3, ' right="rptboth"')
                   + _measure(4, ' right="end"'))
    fixes = _normalise_control_events(score)
    measures = list(score.iter(f"{{{MEI_NS}}}measure"))
    assert [m.attrib.get("right") for m in measures] == [None, "dbl", "dbl", "end"]
    assert all("left" not in m.attrib for m in measures)
    assert fixes["repeat_end_to_double"] == 2 and fixes["repeat_start_removed"] == 1
    assert_no_repeats(score)


def test_double_barline_is_labelled_like_every_barline(tmp_path: Path) -> None:
    """CPM convention: a double barline is one barline-L1, so the dbl written for a repeat needs no new token."""
    score = _score(_measure(1, ' right="dbl"'))
    root = ET.Element(f"{{{MEI_NS}}}mei")
    body = ET.SubElement(ET.SubElement(ET.SubElement(root, f"{{{MEI_NS}}}music"), f"{{{MEI_NS}}}body"),
                         f"{{{MEI_NS}}}mdiv")
    body.append(score)
    path = tmp_path / "t.mei"
    ET.ElementTree(root).write(path, encoding="unicode")
    assert split_systems(convert_staff(path, "1", dialect="verovio"))[0][-1] == "barline-L1"


def test_volta_endings_are_refused() -> None:
    with pytest.raises(ValueError, match="volta"):
        _normalise_control_events(_score(_measure(1), extra=f'<ending n="1">{_measure(2)}</ending>'))


def test_assert_no_repeats_catches_barline_elements() -> None:
    with pytest.raises(ValueError, match="repeat barline"):
        assert_no_repeats(_score(_measure(1), extra='<barLine form="rptend"/>'))


def test_below_fermata_moved_above_and_open_tie_removed() -> None:
    score = _score(_measure(1, note_id="a") + _measure(2, note_id="b"),
                   extra='<fermata startid="#a" place="below" form="inv"/><tie startid="#b"/>')
    fixes = _normalise_control_events(score)
    fermata = next(score.iter(f"{{{MEI_NS}}}fermata"))
    assert (fermata.attrib["place"], fermata.attrib["form"]) == ("above", "norm")
    assert next(score.iter(f"{{{MEI_NS}}}tie"), None) is None
    assert fixes["fermatas_moved_above"] == 1 and fixes["open_ties_removed"] == 1


def test_tie_joining_two_staves_removed_same_staff_tie_kept() -> None:
    measures = ('<measure n="1"><staff n="1"><layer n="1"><note xml:id="s1" pname="c" oct="5" dur="1"/></layer></staff>'
                '<staff n="2"><layer n="1"><note xml:id="a1" pname="c" oct="5" dur="1"/></layer></staff></measure>'
                '<measure n="2"><staff n="1"><layer n="1"><note xml:id="s2" pname="c" oct="5" dur="1"/></layer></staff>'
                '<staff n="2"><layer n="1"><note xml:id="a2" pname="c" oct="5" dur="1"/></layer></staff></measure>')
    score = _score(measures, extra='<tie xml:id="cross" startid="#s1" endid="#a2"/>'
                                   '<tie xml:id="same" startid="#a1" endid="#a2"/>')
    fixes = _normalise_control_events(score)
    kept = [t.attrib.get("{http://www.w3.org/XML/1998/namespace}id") for t in score.iter(f"{{{MEI_NS}}}tie")]
    assert kept == ["same"]
    assert fixes["cross_staff_ties_removed"] == 1 and fixes["open_ties_removed"] == 0


def test_free_member_minor_natural_seventh_by_default() -> None:
    key = music21.key.Key("a")
    assert free_member(music21.pitch.Pitch("A4"), 7, -1, {}, key).nameWithOctave == "B3"
    assert free_member(music21.pitch.Pitch("A4"), 2, -1, {}, key).nameWithOctave == "G4"   # natural, no G#


def test_free_member_uses_raised_seventh_only_when_bar_has_it() -> None:
    key = music21.key.Key("a")
    assert free_member(music21.pitch.Pitch("A4"), 2, -1, {"G4": 1}, key).nameWithOctave == "G#4"


def test_free_member_after_key_change_follows_new_key() -> None:
    assert free_member(music21.pitch.Pitch("D5"), 3, -1, {}, music21.key.Key("D")).nameWithOctave == "B4"
    assert free_member(music21.pitch.Pitch("D5"), 3, -1, {}, music21.key.Key("F")).nameWithOctave == "B-4"


def test_free_member_seventh_only_when_minor() -> None:
    key = music21.key.Key("C")
    assert free_member(music21.pitch.Pitch("C4"), 7, 1, {}, key) is None            # B4 is a major 7th
    assert free_member(music21.pitch.Pitch("D4"), 7, 1, {}, key).nameWithOctave == "C5"


@pytest.mark.parametrize("pitches", [["C4", "C#4"], ["F4", "G#4"], ["F4", "B4"], ["B3", "F4"], ["C#4", "B-4"]])
def test_member_ok_rejects_forbidden_intervals(pitches: list[str]) -> None:
    assert not member_ok([music21.pitch.Pitch(p) for p in pitches], 0)


def test_member_ok_range_and_steps() -> None:
    assert member_ok([music21.pitch.Pitch("E4"), music21.pitch.Pitch("G4")], 0)
    assert not member_ok([music21.pitch.Pitch("A5"), music21.pitch.Pitch("C6")], 0)   # above A5 + 2 st
    assert not member_ok([music21.pitch.Pitch(p) for p in ("C4", "E4", "G4", "B4")], 0)   # 4 notes


def test_member_ok_rejects_generic_unison_and_wide_span() -> None:
    assert not member_ok([music21.pitch.Pitch("E4"), music21.pitch.Pitch("E4")], 0)
    assert not member_ok([music21.pitch.Pitch("C4"), music21.pitch.Pitch("E5")], 0)   # 16 semitones


def _bar_part() -> music21.stream.Part:
    part = music21.stream.Part()
    m = music21.stream.Measure(number=1)
    m.insert(0, music21.key.KeySignature(1))
    m.insert(0, music21.note.Note("C#5", quarterLength=1))
    m.insert(1, music21.note.Note("F4", quarterLength=1))
    part.append(m)
    return part


def test_bar_accidentals_reports_key_and_earlier_same_bar_only() -> None:
    part = _bar_part()
    early = bar_accidentals(0, 1.0, [part])
    assert early["C5"] == 1 and early["F4"] == 1 and early["F5"] == 1    # C#5 sounded earlier; F# from the key
    assert "G4" not in early
    assert bar_accidentals(0, 0.0, [part]).get("C5") is None            # not yet sounded at the downbeat


def test_bar_accidentals_reads_injected_chord_members() -> None:
    """An accidental on a member injected earlier in the bar is in force for later free members (ruling 4)."""
    part = music21.stream.Part()
    m = music21.stream.Measure(number=1)
    m.insert(0, music21.chord.Chord(["D4", "F#4"], quarterLength=1))
    m.insert(1, music21.note.Note("A4", quarterLength=1))
    part.append(m)
    assert bar_accidentals(0, 1.0, [part])["F4"] == 1


# A6 injection (docs/decisions/piya-106-divisi-a6-design.md section 4). Two-bar systems give one 10-bar chorale
# ~20 strips, so the per-strip draws are less noisy than with the real 4-5 bar layout.
FIXTURE_SYSTEM_BARS = 2


def _parts_of(source: "str | music21.stream.Score") -> list[music21.stream.Part]:
    score = music21.corpus.parse(f"bach/{source}") if isinstance(source, str) else source
    parts = _satb_order(score)
    assert parts is not None
    _normalise_clefs(parts)
    return parts


def run_inject(source: "str | music21.stream.Score", seed: str) -> dict[str, object]:
    parts = _parts_of(source)
    n = len(parts[0].getElementsByClass(music21.stream.Measure))
    systems = [list(range(i, min(i + FIXTURE_SYSTEM_BARS, n))) for i in range(0, n, FIXTURE_SYSTEM_BARS)]
    return inject_divisi(parts, systems, random.Random(seed))


def all_tied_fixture() -> music21.stream.Score:
    """Four voices whose every note is part of one tie chain, so no note is chord-capable."""
    score = music21.stream.Score()
    for name, pitch in (("Soprano", "C5"), ("Alto", "E4"), ("Tenor", "G3"), ("Bass", "C3")):
        part = music21.stream.Part()
        part.partName = name
        notes = []
        for i in range(8):
            m = music21.stream.Measure(number=i + 1)
            if i == 0:
                m.insert(0, music21.meter.TimeSignature("4/4"))
            for off in (0, 2):
                n = music21.note.Note(pitch, quarterLength=2)
                m.insert(off, n)
                notes.append(n)
            part.append(m)
        for i, n in enumerate(notes):
            n.tie = music21.tie.Tie("start" if i == 0 else "stop" if i == len(notes) - 1 else "continue")
        score.insert(0, part)
    return score


def build_divisi_fixture(seed: str) -> types.SimpleNamespace:
    path = Path(str(music21.corpus.getWork("bach/bwv66.6")))
    with tempfile.TemporaryDirectory() as tmp:
        plan, mei, _ = build_divisi(path, "bach", Path(tmp), inject_seed=seed)
    return types.SimpleNamespace(systems=plan.systems, pages=plan.pages, measure_n=plan.measure_n, mei=mei)


def test_a6_inject_chord_free_share_and_density():
    stats = run_inject("bwv66.6", seed="divisi")
    s = stats["strips"]; free = stats["chord_free_strips"]
    assert abs(free / s - 0.25) <= 0.15            # one piece: loose; corpus gate checks ±3 pp
    for dens in stats["density_per_strip"]:
        assert dens == 0 or 0.20 - 1e-9 <= dens <= 0.60 + 1e-9


def test_a6_chord_free_decision_is_per_voice_system():
    a = run_inject("bwv66.6", seed="divisi"); b = run_inject("bwv66.6", seed="divisi")
    assert a["chord_free_keys"] == b["chord_free_keys"]       # deterministic, font-independent


def test_a6_never_invents_accidentals_on_free_members():
    stats = run_inject("bwv66.6", seed="divisi")
    assert stats["free_new_accidentals"] == 0


def test_a6_strip_without_chordable_note_stays_plain():
    stats = run_inject(all_tied_fixture(), seed="divisi")
    assert stats["chords_total"] == 0 and stats["skipped"]["tie"] > 0


def test_a6_injection_seed_changes_chords_not_layout():
    p1 = build_divisi_fixture(seed="divisi"); p2 = build_divisi_fixture(seed="divisi-t1")
    assert (p1.systems, p1.pages, p1.measure_n) == (p2.systems, p2.pages, p2.measure_n)
    assert p1.mei != p2.mei


def test_a6_stats_shape_and_stems_per_chord_column() -> None:
    stats = run_inject("bwv66.6", seed="divisi")
    json.dumps(stats)                                  # written verbatim into plan.json / divisi_summary.json
    stems = stats["stems"]
    assert sum(len(v) for v in stems.values()) == stats["chords_total"] > 0
    assert all(d in ("up", "down", build_corpus.STEMLESS) for v in stems.values() for d in v)
    assert sum(v.count(build_corpus.STEMLESS) for v in stems.values()) == stats["duration"].get("whole", 0)
    assert sum(stats["duration"].values()) == stats["chords_total"]
    assert stats["ties"] == 0                          # TIES_ENABLED is off until G1b passes the tie case
    assert stats["crossing"] <= build_corpus.MAX_CROSSING * stats["chords_total"] + 1e-9


def test_a6_whole_note_merge_makes_whole_chords(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bach has almost no whole notes (Task 1), so whole-note chords come from merging a 4/4 bar."""
    monkeypatch.setattr(build_corpus, "A6_DURATIONS", {"whole": 1.0})
    monkeypatch.setattr(build_corpus, "P_CHORD_FREE_STRIP", 0.0)
    parts = _parts_of("bwv66.6")
    n = len(parts[0].getElementsByClass(music21.stream.Measure))
    stats = inject_divisi(parts, [list(range(i, min(i + 2, n))) for i in range(0, n, 2)], random.Random("divisi"))
    assert stats["merged_whole"] > 0 and stats["duration"].get("whole", 0) == stats["chords_total"]
    for part in parts:
        for m in part.getElementsByClass(music21.stream.Measure):
            assert m.duration.quarterLength <= 4.0     # never merged across a barline
            for c in m.getElementsByClass(music21.chord.Chord):
                assert c.duration.type == "whole" and c.offset == 0


def test_a6_tie_path_chords_both_sides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_corpus, "TIES_ENABLED", True)
    monkeypatch.setattr(build_corpus, "P_TIE_CHORD", 1.0)
    monkeypatch.setattr(build_corpus, "P_CHORD_FREE_STRIP", 0.0)
    score = all_tied_fixture()
    for part in score.parts:                           # one start->stop pair per bar, inside one system
        for m in part.getElementsByClass(music21.stream.Measure):
            first, second = m.getElementsByClass(music21.note.Note)
            first.tie, second.tie = music21.tie.Tie("start"), music21.tie.Tie("stop")
    stats = run_inject(score, seed="divisi")
    assert stats["ties"] > 0 and stats["skipped"].get("tie", 0) == 0
    for part in score.parts:
        for m in part.getElementsByClass(music21.stream.Measure):
            items = list(m.notes)
            if any(isinstance(x, music21.chord.Chord) for x in items):
                a, b = items
                assert isinstance(a, music21.chord.Chord) and isinstance(b, music21.chord.Chord)
                assert [p.nameWithOctave for p in a.pitches] == [p.nameWithOctave for p in b.pitches]
                assert all(n.tie.type == "start" for n in a.notes) and all(n.tie.type == "stop" for n in b.notes)


# (merge kind, duration class, enabling flag, a chorale offering several such pairs)
MERGE_CASES = [("whole", "whole", "MERGE_TO_WHOLE", "bwv66.6"), ("half", "half", "MERGE_TO_HALF", "bwv66.6"),
               ("dotted_half", "dotted", "MERGE_TO_DOTTED_HALF", "bwv17.7"),
               ("dotted_quarter", "dotted", "MERGE_TO_DOTTED_QUARTER", "bwv102.7")]


def _bar_lengths(parts: list[music21.stream.Part]) -> list[list[float]]:
    return [[sum(float(x.quarterLength) for x in m.notesAndRests) for m in part.getElementsByClass(
        music21.stream.Measure)] for part in parts]


@pytest.mark.parametrize("kind,cls,flag,piece", MERGE_CASES)
def test_a6_merge_kind_keeps_bars_and_labels(monkeypatch: pytest.MonkeyPatch, kind: str, cls: str, flag: str,
                                             piece: str) -> None:
    """Each merge kind alone: bar lengths and measure count unchanged, and the MEI still passes check_labels."""
    for _, _, other, _ in MERGE_CASES:
        monkeypatch.setattr(build_corpus, other, other == flag)
    monkeypatch.setattr(build_corpus, "A6_DURATIONS", {cls: 1.0})
    monkeypatch.setattr(build_corpus, "P_CHORD_FREE_STRIP", 0.0)
    parts = _parts_of(piece)
    before = _bar_lengths(parts)
    stats = inject_divisi(parts, [list(range(i, min(i + 2, len(before[0])))) for i in range(0, len(before[0]), 2)],
                          random.Random("divisi"))
    assert stats["merged"].get(kind, 0) > 0
    assert _bar_lengths(parts) == before
    path = Path(str(music21.corpus.getWork(f"bach/{piece}")))
    with tempfile.TemporaryDirectory() as tmp:
        plan, mei, built = build_divisi(path, "bach", Path(tmp), inject_seed="divisi")
        assert built["merged"].get(kind, 0) > 0
        mei_path = Path(tmp) / "piece.mei"
        mei_path.write_text(mei, encoding="utf-8")
        check_labels(mei_path, plan)


def test_a6_copied_candidates_cover_the_whole_span() -> None:
    """A pitch another voice reaches later while the chord still sounds is offered as a copied member."""
    P = music21.pitch.Pitch
    sounding = [[(0.0, 4.0, P("C5"))], [(0.0, 2.0, P("E4")), (2.0, 4.0, P("A4"))], [], []]
    names = lambda cands: {p.nameWithOctave for p in cands}           # noqa: E731
    def offered(t_end: float) -> set[str]:
        span = build_corpus._span_pitches(sounding, 0, 0.0, t_end)
        return names(build_corpus._divisi_candidates(P("C5"), [P("C5")], span, 0, frozenset({3})))
    assert "A4" in offered(4.0)               # reached at beat 3, inside the chord's span
    assert "A4" not in offered(2.0)           # the span ends before the alto reaches A4


def test_a6_merged_base_checked_over_the_span() -> None:
    """The merged note holds its first pitch; a later crossing or cross-relation in the span rejects the merge."""
    P = music21.pitch.Pitch
    crossing = [[(0.0, 2.0, P("E5")), (2.0, 4.0, P("B4"))], [], [], []]           # soprano drops below C5
    assert not build_corpus._base_conflicts(P("C5"), 1, 0.0, 2.0, crossing)
    assert build_corpus._base_conflicts(P("C5"), 1, 0.0, 4.0, crossing)
    relation = [[(0.0, 4.0, P("A5"))], [], [(0.0, 4.0, P("C4"))], [(2.0, 4.0, P("F#4"))]]   # bass F#4 vs F4
    assert build_corpus._base_conflicts(P("F4"), 1, 0.0, 4.0, relation)
