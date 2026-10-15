"""Chord head x-order audit (divisi freeze A3): bottom-to-top label order vs left-to-right drawn order."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase1"))

from chord_xorder_audit import chord_order_mismatches  # noqa: E402

HEAD = ('<g class="note"><g class="notehead"><use xlink:href="#E0A4" transform="translate({x}, {y}) scale(0.72, 0.72)"/>'
        '</g></g>')


def svg(*chords: list[tuple[int, int]]) -> str:
    body = "".join('<g data-id="c%d" class="chord">%s</g>' % (i, "".join(HEAD.format(x=x, y=y) for x, y in heads))
                   for i, heads in enumerate(chords))
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">%s</svg>' % body)


def test_stacked_third_is_in_order() -> None:
    assert chord_order_mismatches(svg([(100, 800), (100, 700)])) == []


def test_second_upper_head_right_is_in_order() -> None:
    # SVG y grows downward: (100, 800) is the lower head, drawn left.
    assert chord_order_mismatches(svg([(100, 800), (130, 750)])) == []


def test_second_upper_head_left_is_a_mismatch() -> None:
    out = chord_order_mismatches(svg([(130, 800), (100, 750)]))
    assert len(out) == 1 and out[0]["chord_id"] == "c0" and out[0]["heads"] == [(130.0, 800.0), (100.0, 750.0)]


def test_cluster_middle_head_displaced_right_is_a_mismatch() -> None:
    out = chord_order_mismatches(svg([(100, 800), (130, 750), (100, 700)]))
    assert [m["chord_id"] for m in out] == ["c0"]


def test_member_order_in_svg_does_not_matter() -> None:
    assert chord_order_mismatches(svg([(130, 750), (100, 800)])) == []
