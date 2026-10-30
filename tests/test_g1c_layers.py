"""G1c: two-layer bars in the MEI -> agnostic converter (divisi A7 design section 5.1, Verovio dialect).

Treble clef positions used below: E4 L1, F4 S1, G4 L2, A4 S2, B4 L3, C5 S3, D5 L4, E5 S4, F5 L5, G5 S5.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from music_to_agnostic import ConversionError, convert_staff  # noqa: E402

HEAD = ('<?xml version="1.0" encoding="UTF-8"?><mei xmlns="http://www.music-encoding.org/ns/mei" '
        'xmlns:xml="http://www.w3.org/XML/1998/namespace"><music><body><mdiv><score><scoreDef><staffGrp>'
        '<staffDef n="1" lines="5" clef.shape="G" clef.line="2" key.sig="0" meter.count="4" meter.unit="4"/>'
        '</staffGrp></scoreDef><section>')
TAIL = "</section></score></mdiv></body></music></mei>"


def bar(n: int, *layers: str, extra: str = "") -> str:
    body = "".join(f'<layer n="{i}">{content}</layer>' for i, content in enumerate(layers, start=1))
    return f'<measure n="{n}" right="single"><staff n="1">{body}</staff>{extra}</measure>'


def note(nid: str, pname: str, octave: int, dur: str, **attrs: str) -> str:
    more = "".join(f' {k.replace("_", ".")}="{v}"' for k, v in attrs.items())
    return f'<note xml:id="{nid}" pname="{pname}" oct="{octave}" dur="{dur}"{more}/>'


def bodies(tmp_path: Path, *bars: str) -> list[list[str]]:
    path = tmp_path / "t.mei"
    path.write_text(HEAD + "".join(bars) + TAIL, encoding="utf-8")
    return [m.body for m in convert_staff(path, "1", dialect="verovio")]


def test_different_rhythms_interleave_by_onset(tmp_path: Path) -> None:
    upper = note("a", "c", 5, "2") + note("b", "d", 5, "2")
    lower = note("c", "a", 4, "4") + note("d", "g", 4, "4") + note("e", "f", 4, "4") + note("f", "e", 4, "4")
    assert bodies(tmp_path, bar(1, upper, lower))[0] == [
        "layer.split", "note.half-S3", "note.quarter.l2-S2", "note.quarter.l2-L2",
        "note.half-L4", "note.quarter.l2-S1", "note.quarter.l2-L1", "barline-L1"]


def test_layer2_beams_keep_their_roles(tmp_path: Path) -> None:
    lower = ('<beam>' + note("a", "g", 4, "8") + note("b", "f", 4, "8") + '</beam>'
             + note("c", "e", 4, "4") + note("d", "e", 4, "2"))
    body = bodies(tmp_path, bar(1, note("u", "c", 5, "1"), lower))[0]
    assert body[:4] == ["layer.split", "note.whole-S3", "note.beamedRight1.l2-L2", "note.beamedLeft1.l2-S1"]


def test_same_rhythm_split_stems_are_a_split_bar(tmp_path: Path) -> None:
    body = bodies(tmp_path, bar(1, note("a", "d", 5, "1"), note("b", "g", 4, "1")))[0]
    assert body == ["layer.split", "note.whole-L4", "note.whole.l2-L2", "barline-L1"]


def test_layer2_rests_and_mid_bar_entry(tmp_path: Path) -> None:
    upper = note("a", "c", 5, "2") + note("b", "c", 5, "2")
    lower = '<space dur="2"/>' + note("c", "a", 4, "4") + '<rest dur="4"/>'
    assert bodies(tmp_path, bar(1, upper, lower))[0] == [
        "layer.split", "note.half-S3", "note.half-S3", "note.quarter.l2-S2", "rest.quarter.l2-L3", "barline-L1"]


def test_unison_across_layers_keeps_both_heads(tmp_path: Path) -> None:
    body = bodies(tmp_path, bar(1, note("a", "c", 5, "1"), note("b", "c", 5, "1")))[0]
    assert body == ["layer.split", "note.whole-S3", "note.whole.l2-S3", "barline-L1"]


def test_chordnotes_inside_layer2_follow_their_head(tmp_path: Path) -> None:
    lower = '<chord dur="1">' + note("b", "e", 4, "1") + note("c", "g", 4, "1") + "</chord>"
    body = bodies(tmp_path, bar(1, note("a", "d", 5, "1"), lower))[0]
    assert body == ["layer.split", "note.whole-L4", "note.whole.l2-L1", "chordnote-L2", "barline-L1"]


def test_accidental_in_one_layer_only(tmp_path: Path) -> None:
    upper = note("a", "f", 4, "2", accid="s") + note("b", "f", 4, "2", accid_ges="s")
    lower = note("c", "f", 4, "2", accid_ges="s") + note("d", "f", 4, "2", accid="n")
    assert bodies(tmp_path, bar(1, upper, lower))[0] == [
        "layer.split", "accidental.sharp-S1", "note.half-S1", "note.half.l2-S1",
        "note.half-S1", "accidental.natural-S1", "note.half.l2-S1", "barline-L1"]


def test_tie_from_layer2_into_one_layer_bar(tmp_path: Path) -> None:
    lower = note("c", "g", 4, "2") + note("d", "e", 4, "2")
    first = bar(1, note("a", "c", 5, "1"), lower, extra='<tie startid="#d" endid="#e"/>')
    second = bar(2, note("e", "e", 4, "1"))
    b1, b2 = bodies(tmp_path, first, second)
    assert b1[-3:] == ["note.half.l2-L1", "slur.start-L1", "barline-L1"]
    assert b2 == ["slur.end-L1", "note.whole-L1", "barline-L1"]


def test_tie_within_a_layer(tmp_path: Path) -> None:
    lower = note("c", "g", 4, "2") + note("d", "g", 4, "2")
    body = bodies(tmp_path, bar(1, note("a", "c", 5, "1"), lower, extra='<tie startid="#c" endid="#d"/>'))[0]
    assert body == ["layer.split", "note.whole-S3", "note.half.l2-L2", "slur.start-L2",
                    "slur.end-L2", "note.half.l2-L2", "barline-L1"]


def test_tied_template_triad_ties_every_head(tmp_path: Path) -> None:
    chord1 = '<chord dur="1">' + note("a", "e", 4, "1") + note("b", "g", 4, "1") + note("c", "c", 5, "1") + "</chord>"
    chord2 = '<chord dur="1">' + note("d", "e", 4, "1") + note("e", "g", 4, "1") + note("f", "c", 5, "1") + "</chord>"
    ties = "".join(f'<tie startid="#{a}" endid="#{b}"/>' for a, b in ("ad", "be", "cf"))
    b1, b2 = bodies(tmp_path, bar(1, chord1, extra=ties), bar(2, chord2))
    assert b1 == ["note.whole-L1", "chordnote-L2", "chordnote-S3",
                  "slur.start-L1", "slur.start-L2", "slur.start-S3", "barline-L1"]
    assert b2[:3] == ["slur.end-L1", "slur.end-L2", "slur.end-S3"]


def test_spacer_only_layer_is_not_a_layer(tmp_path: Path) -> None:
    one = bodies(tmp_path, bar(1, note("a", "c", 5, "1")))[0]
    assert bodies(tmp_path, bar(1, note("a", "c", 5, "1"), '<mSpace/>'))[0] == one
    assert "layer.split" not in one


def test_three_layers_refused(tmp_path: Path) -> None:
    with pytest.raises(ConversionError, match="3 layers"):
        bodies(tmp_path, bar(1, note("a", "c", 5, "1"), note("b", "a", 4, "1"), note("c", "f", 4, "1")))


def test_grace_note_in_layer2_refused(tmp_path: Path) -> None:
    lower = note("g", "f", 4, "8", grace="acc") + note("b", "g", 4, "1")
    with pytest.raises(ConversionError, match="grace"):
        bodies(tmp_path, bar(1, note("a", "c", 5, "1"), lower))


def test_layer_tokens_are_in_the_a7_vocab(tmp_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import music_to_agnostic as conv
    import stage3_transcription as s3
    assert (conv.LAYER_SPLIT, conv.LAYER2_TAG) == (s3.LAYER_SPLIT_TOKEN, s3.LAYER2_TAG)
    assert s3.VOCAB_EXT_A7[:len(s3.VOCAB_EXT_CHORD_TUPLET)] == s3.VOCAB_EXT_CHORD_TUPLET
    assert len(set(s3.VOCAB_EXT_A7)) == len(s3.VOCAB_EXT_A7)
    upper = note("a", "c", 5, "2") + note("b", "d", 5, "2")
    lower = '<space dur="4"/>' + note("c", "a", 4, "4") + '<rest dur="2"/>'
    vocab = set(s3.VOCAB_EXT_A7)
    assert all(t in vocab for t in bodies(tmp_path, bar(1, upper, lower))[0])
