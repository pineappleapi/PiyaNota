"""Rule tests for the MEI -> agnostic converter (PIYA-106 Phase 1 step 1).

Each case pins one labelling rule read off Camera-PrIMuS gold or checked against a Verovio render. They do not
replace gate G1 (training/g1_converter_gate.py on the CPM corpus) or the G1b human spot-check.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from music_to_agnostic import (ConversionError, convert_file, convert_staff, position_suffix,  # noqa: E402
                               split_systems)

HEAD = ('<?xml version="1.0" encoding="UTF-8"?><mei xmlns="http://www.music-encoding.org/ns/mei" '
        'xmlns:xml="http://www.w3.org/XML/1998/namespace"><music><body><mdiv><score>')
TAIL = "</score></mdiv></body></music></mei>"


def _mei(tmp_path: Path, score_def: str, measures: str) -> Path:
    path = tmp_path / "t.mei"
    path.write_text(HEAD + score_def + f"<section>{measures}</section>" + TAIL, encoding="utf-8")
    return path


def _measure(layer: str, right: str = "single", extra: str = "") -> str:
    return f'<measure right="{right}"><staff n="1"><layer n="1">{layer}</layer></staff>{extra}</measure>'


def _treble(key: str = "0", meter: str = 'meter.count="4" meter.unit="4"') -> str:
    return (f'<scoreDef key.sig="{key}" {meter}><staffGrp>'
            '<staffDef n="1" lines="5" clef.shape="G" clef.line="2"/></staffGrp></scoreDef>')


def test_position_suffix_round_trip() -> None:
    assert [position_suffix(p) for p in (-4, -2, -1, 0, 1, 8, 11)] == ["L-1", "L0", "S0", "L1", "S1", "L5", "S6"]


def test_header_key_and_meter(tmp_path: Path) -> None:
    mei = _mei(tmp_path, _treble("2f", 'meter.sym="cut"'), _measure('<note pname="b" oct="4" dur="1"/>'))
    assert convert_file(mei) == ["clef.G-L2", "accidental.flat-L3", "accidental.flat-S4", "metersign.C/-L3",
                                 "note.whole-L3", "barline-L1"]


def test_primus_restates_key_flat_after_natural(tmp_path: Path) -> None:
    # PrIMuS MEI gives an unmarked B its key alteration (B-flat), so the flat must be drawn again.
    layer = '<note pname="b" oct="4" dur="4"><accid accid="n"/></note><note pname="b" oct="4" dur="4"/>'
    mei = _mei(tmp_path, _treble("1f"), _measure(layer))
    assert convert_file(mei)[-5:] == ["accidental.natural-L3", "note.quarter-L3", "accidental.flat-L3",
                                      "note.quarter-L3", "barline-L1"]


def test_courtesy_accidental_is_drawn(tmp_path: Path) -> None:
    layer = '<note pname="b" oct="4" dur="4"><accid accid="f"/></note>'
    mei = _mei(tmp_path, _treble("1f"), _measure(layer))
    assert "accidental.flat-L3" in convert_file(mei)[2:]


def test_tie_across_barline_and_different_pitch_tie(tmp_path: Path) -> None:
    same = (_measure('<note pname="g" oct="4" dur="1" tie="i"/>')
            + _measure('<note pname="g" oct="4" dur="1" tie="t"/>'))
    assert convert_file(_mei(tmp_path, _treble(), same))[3:] == [
        "note.whole-L2", "slur.start-L2", "barline-L1", "slur.end-L2", "note.whole-L2", "barline-L1"]
    different = (_measure('<note pname="g" oct="4" dur="1" tie="i"/>')
                 + _measure('<note pname="a" oct="4" dur="1" tie="t"/>'))
    assert not any(t.startswith("slur") for t in convert_file(_mei(tmp_path, _treble(), different)))


def test_beam_uses_own_flag_count_and_dot_goes_up_from_line(tmp_path: Path) -> None:
    layer = '<beam><note pname="g" oct="4" dur="8" dots="1"/><note pname="a" oct="4" dur="16"/></beam>'
    assert convert_file(_mei(tmp_path, _treble(), _measure(layer, "invis")))[3:] == [
        "note.beamedRight1-L2", "dot-S2", "note.beamedLeft2-S2"]


def test_multirest_digits_split(tmp_path: Path) -> None:
    mei = _mei(tmp_path, _treble(), _measure('<multiRest num="24"/>'))
    assert convert_file(mei)[3:] == ["digit.2-S5", "digit.4-S5", "multirest-L3", "barline-L1"]


def test_verovio_dialect_draws_only_written_accidentals(tmp_path: Path) -> None:
    # accid.ges is sounding-only; the second F-sharp in the bar has no glyph.
    layer = ('<note pname="f" oct="4" dur="4"><accid accid="s"/></note>'
             '<note pname="f" oct="4" dur="4"><accid accid.ges="s"/></note>')
    mei = _mei(tmp_path, _treble(), _measure(layer))
    assert convert_file(mei, dialect="verovio")[3:] == ["accidental.sharp-S1", "note.quarter-S1",
                                                        "note.quarter-S1", "barline-L1"]


def test_verovio_control_event_tie_and_fermata(tmp_path: Path) -> None:
    m1 = _measure('<note xml:id="n1" pname="g" oct="4" dur="1"/>',
                  extra='<tie startid="#n1" endid="#n2"/><fermata startid="#n2" place="above"/>')
    m2 = _measure('<note xml:id="n2" pname="g" oct="4" dur="1"/>')
    assert convert_file(_mei(tmp_path, _treble(), m1 + m2), dialect="verovio")[3:] == [
        "note.whole-L2", "slur.start-L2", "barline-L1", "fermata.above-S6", "slur.end-L2", "note.whole-L2",
        "barline-L1"]


def test_continuation_system_header_has_clef_and_key_but_no_meter(tmp_path: Path) -> None:
    measures = (_measure('<note pname="g" oct="4" dur="1"/>') + "<sb/>"
                + _measure('<note pname="a" oct="4" dur="1"/>'))
    systems = split_systems(convert_staff(_mei(tmp_path, _treble("1s"), measures), dialect="verovio"))
    assert systems == [["clef.G-L2", "accidental.sharp-L5", "digit.4-L4", "digit.4-L2", "note.whole-L2",
                        "barline-L1"],
                       ["clef.G-L2", "accidental.sharp-L5", "note.whole-S2", "barline-L1"]]


def test_chord_is_refused(tmp_path: Path) -> None:
    layer = '<chord dur="4"><note pname="g" oct="4"/><note pname="b" oct="4"/></chord>'
    with pytest.raises(ConversionError):
        convert_file(_mei(tmp_path, _treble(), _measure(layer)))


def test_treble_8vb_positions_follow_the_drawn_clef(tmp_path: Path) -> None:
    # Verovio keeps @oct sounding and draws C4 under a G-8vb clef where a treble clef draws C5 (third space).
    score_def = ('<scoreDef key.sig="0" meter.count="4" meter.unit="4"><staffGrp><staffDef n="1" lines="5" '
                 'clef.shape="G" clef.line="2" clef.dis="8" clef.dis.place="below"/></staffGrp></scoreDef>')
    mei = _mei(tmp_path, score_def, _measure('<note pname="c" oct="4" dur="1"/>'))
    assert convert_file(mei, dialect="verovio") == ["clef.G-L2", "digit.4-L4", "digit.4-L2", "note.whole-S3",
                                                    "barline-L1"]


def test_verovio_key_change_to_no_key_draws_naturals(tmp_path: Path) -> None:
    measures = (_measure('<note pname="g" oct="4" dur="1"/>') + '<scoreDef key.sig="0"/>'
                + _measure('<note pname="g" oct="4" dur="1"/>'))
    mei = _mei(tmp_path, _treble("2s"), measures)
    assert convert_file(mei, dialect="verovio")[7:10] == ["accidental.natural-L5", "accidental.natural-S3",
                                                          "note.whole-L2"]


def test_key_and_meter_change_at_break_get_courtesy_signature(tmp_path: Path) -> None:
    measures = (_measure('<note pname="g" oct="4" dur="1"/>') + '<sb/><scoreDef key.sig="1f" meter.sym="cut"/>'
                + _measure('<note pname="g" oct="4" dur="1"/>'))
    systems = split_systems(convert_staff(_mei(tmp_path, _treble("1s"), measures), dialect="verovio"))
    assert systems == [["clef.G-L2", "accidental.sharp-L5", "digit.4-L4", "digit.4-L2", "note.whole-L2",
                        "barline-L1", "accidental.flat-L3", "metersign.C/-L3"],
                       ["clef.G-L2", "accidental.flat-L3", "metersign.C/-L3", "note.whole-L2", "barline-L1"]]


def test_whole_bar_rest_follows_bar_length_in_verovio_dialect(tmp_path: Path) -> None:
    """Verovio draws <mRest> as a breve rest in a bar of two whole notes or more (Palestrina's 4/2); PrIMuS never."""
    mrest = _measure("<mRest/>")
    breve_bar = _mei(tmp_path, _treble(meter='meter.count="4" meter.unit="2"'), mrest)
    assert convert_file(breve_bar, dialect="verovio")[-2] == "rest.double_whole-L3"
    assert convert_file(breve_bar, dialect="primus")[-2] == "rest.whole-L4"
    three_two = _mei(tmp_path, _treble(meter='meter.count="3" meter.unit="2"'), mrest)
    assert convert_file(three_two, dialect="verovio")[-2] == "rest.whole-L4"
    # An inline change to 2/1 switches the glyph for the rest after it.
    change = _measure('<meterSig count="2" unit="1"/><mRest/>')
    assert convert_file(_mei(tmp_path, _treble(), change), dialect="verovio")[-2] == "rest.double_whole-L3"
