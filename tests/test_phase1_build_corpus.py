"""Tests for the Phase 1 corpus normalisation (PIYA-106): what reaches Verovio must be describable by the labels.

Repeats are a known limitation (docs/bug-tracker.md): no repeat token exists, so no rpt* barline may be rendered.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "phase1"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from build_corpus import MEI_NS, _normalise_control_events, assert_no_repeats  # noqa: E402
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
