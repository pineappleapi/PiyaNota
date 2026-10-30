"""Divisi A7 generator helpers (build_corpus.py, design section 3): template shapes, ledger sites, A6 untouched."""

import sys
from pathlib import Path

import pytest

music21 = pytest.importorskip("music21")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "phase1"))
import build_corpus as bc  # noqa: E402

P = music21.pitch.Pitch
SOPRANO, ALTO, TENOR, BASS = range(4)


def test_a6_default_ignores_ledger_sites() -> None:
    assert bc.A7_ARM is None
    assert bc._ledger_sites_ok(P("A5"), [P("C6"), P("F5")], SOPRANO, cadence=False)
    assert bc._ledger_sites_ok(P("D4"), [P("A3")], TENOR, cadence=False)


def test_close_position() -> None:
    assert bc._close_position([P("E5"), P("G5"), P("C6")])          # 3 + 5 (first inversion)
    assert bc._close_position([P("C5"), P("E5"), P("G5")])          # 4 + 3
    assert not bc._close_position([P("C5"), P("G5"), P("E6")])      # open


def test_template_shapes_per_voice() -> None:
    c, e, g = 0, 4, 7
    assert bc._template_shape_ok([P("C5"), P("E5"), P("C6")], P("C6"), "Soprano", c, e, g)    # root-3rd-octave
    assert bc._template_shape_ok([P("C3"), P("G3"), P("C4")], P("C3"), "Bass", c, e, g)       # root-5th-octave
    assert not bc._template_shape_ok([P("C3"), P("E3"), P("G3")], P("C3"), "Bass", c, e, g)   # close bass
    assert not bc._template_shape_ok([P("E3"), P("G3"), P("C4")], P("E3"), "Bass", c, e, g)   # not on the root
    assert not bc._template_shape_ok([P("C3"), P("E3"), P("C4")], P("C3"), "Bass", c, e, g)   # 3rd under E3
    assert not bc._template_shape_ok([P("G4"), P("C5"), P("E5")], P("G4"), "Tenor", c, e, g)  # over G4
    assert bc._template_shape_ok([P("G3"), P("C4"), P("E4")], P("G3"), "Alto", c, e, g)       # a 6th, in G3..C5
    assert not bc._template_shape_ok([P("E3"), P("G3"), P("C4")], P("E3"), "Alto", c, e, g)   # under G3


def test_ledger_sites_under_a7(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bc, "A7_ARM", "C")
    assert bc._ledger_sites_ok(P("A5"), [P("C6")], SOPRANO, cadence=False)           # C6 on top
    assert not bc._ledger_sites_ok(P("E5"), [P("C6"), P("D6")], SOPRANO, cadence=False)  # D6 is not a site
    assert not bc._ledger_sites_ok(P("E4"), [P("A3")], ALTO, cadence=False)          # alto low only at a cadence
    assert bc._ledger_sites_ok(P("E4"), [P("A3")], ALTO, cadence=True)               # 5th above A3
    assert bc._ledger_sites_ok(P("C3"), [P("C2")], BASS, cadence=False)              # low octave
    assert not bc._ledger_sites_ok(P("D3"), [P("C2")], BASS, cadence=False)          # C2 under a 9th
    assert bc._ledger_sites_ok(P("C4"), [P("E4")], BASS, cadence=False)              # E4 a 3rd above
    assert not bc._ledger_sites_ok(P("C4"), [P("F4")], BASS, cadence=False)          # F4 is not a site


def test_ledger_site_pitch_matches_the_drawn_interval() -> None:
    assert bc._ledger_site_pitch(P("E5"), 6, SOPRANO, False, {}, 0).nameWithOctave == "C6"
    assert bc._ledger_site_pitch(P("E5"), 5, SOPRANO, False, {}, 0) is None
    assert bc._ledger_site_pitch(P("C3"), 8, BASS, False, {}, 0).nameWithOctave == "C2"
    assert bc._ledger_site_pitch(P("E5"), 6, SOPRANO, False, {"C6": 1}, 0) is None      # C#6 in force: no site
    assert bc._ledger_site_pitch(P("D4"), 5, ALTO, False, {}, 0) is None                # not a cadence
