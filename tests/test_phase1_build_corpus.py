"""Tests for the Phase 1 corpus normalisation (PIYA-106): what reaches Verovio must be describable by the labels.

Repeats are a known limitation (docs/bug-tracker.md): no repeat token exists, so no rpt* barline may be rendered.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "phase1"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
import music21  # noqa: E402
from build_corpus import (MEI_NS, _normalise_control_events, assert_no_repeats, bar_accidentals,  # noqa: E402
                          free_member, member_ok)
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
