"""Synthetic regression tests for Stage 1 staff tracking/dewarp/non-staff-ink mask and Stage 2 crop handling.

Run with ``python -m pytest tests`` (or ``python tests/test_staff_tracking.py``).
Synthetic pages keep these fast and independent of the private camera test set.
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage1_preprocessing as s1  # noqa: E402
import stage2_detection as s2  # noqa: E402

PAGE_W = 1200
PAGE_H = 800
SPACING_PX = 12
STAFF_CENTERS = (200, 450)
SLOPE_PX_PER_COL = 0.03  # ~36 px drift over the page: well above DEWARP_MIN_DRIFT_PX


def _synthetic_page(slope: float) -> np.ndarray:
    """White page with black 5-line staves; ``slope`` tilts the lines (px per column)."""
    page = np.full((PAGE_H, PAGE_W), 255, dtype=np.uint8)
    for center in STAFF_CENTERS:
        for line in range(-2, 3):
            for x in range(PAGE_W):
                y = int(round(center + line * SPACING_PX + slope * (x - PAGE_W / 2)))
                page[y - 1:y + 1, x] = 0
    return page


def test_tracker_finds_every_staff_on_tilted_page() -> None:
    curves = s1.track_staff_curves(_synthetic_page(SLOPE_PX_PER_COL))
    assert len(curves) == len(STAFF_CENTERS)


def test_dewarp_straightens_and_is_identity_when_straight() -> None:
    tilted = _synthetic_page(SLOPE_PX_PER_COL)
    curves = s1.track_staff_curves(tilted)
    assert s1.needs_dewarp(curves)
    flat = s1.dewarp_to_staff_grid(tilted, curves)
    assert flat.shape == tilted.shape
    assert not s1.needs_dewarp(s1.track_staff_curves(flat))

    straight = _synthetic_page(0.0)
    assert not s1.needs_dewarp(s1.track_staff_curves(straight))


def test_neighbor_limits_stop_at_midpoints() -> None:
    boxes = [{"y1": 100, "y2": 140}, {"y1": 200, "y2": 240}, {"y1": 300, "y2": 340}]
    top, bottom = s2._neighbor_limits(boxes, 1, PAGE_H)
    assert top == (140 + 200) // 2 and bottom == (240 + 300) // 2
    assert s2._neighbor_limits(boxes, 0, PAGE_H)[0] == 0


def test_strip_height_matches_stage3() -> None:
    """Stage 2 must emit strips at the height Stage 3's CRNN was trained on.

    Cross-checks against the actual default on stage3_transcription.transcribe_voice_sequences
    (the Stage 2 -> 3 entry point) via introspection, not a second hardcoded literal, so this
    catches real drift between the files rather than just guarding stage2's own former
    duplicate-STRIP_HEIGHT definition (see d374c2b).
    """
    import inspect

    import stage3_transcription as s3

    stage3_default = inspect.signature(s3.transcribe_voice_sequences).parameters["img_height"].default
    assert s2.STRIP_HEIGHT == stage3_default == 64


CENTER = STAFF_CENTERS[0]
BAND = [s1.StaffBand(center=float(c), spacing=float(SPACING_PX)) for c in STAFF_CENTERS]
DARK = 128  # ink threshold on the synthetic grey pages


def _removed(page: np.ndarray) -> np.ndarray:
    """Ink pixels the Stage 1 non-staff-ink mask would erase on ``page``."""
    return s1.non_staff_ink_mask(page, BAND)


def _draw_note_and_lyric(page: np.ndarray) -> None:
    cv2.ellipse(page, (300, CENTER + SPACING_PX // 2), (7, 5), 0, 0, 360, 0, -1)  # notehead
    page[CENTER - 3 * SPACING_PX:CENTER + SPACING_PX // 2, 306:308] = 0  # stem up
    for k in range(6):  # lyric-like word blobs 1.5 spacings below the bottom line
        page[CENTER + 3 * SPACING_PX + 2:CENTER + 3 * SPACING_PX + 10, 500 + k * 12:500 + k * 12 + 8] = 0


def test_mask_removes_lyric_blob_and_keeps_note() -> None:
    page = _synthetic_page(0.0)
    _draw_note_and_lyric(page)
    removed, ink = _removed(page), page < DARK
    lyric = np.zeros_like(ink)
    lyric[CENTER + 3 * SPACING_PX + 2:CENTER + 3 * SPACING_PX + 10, 500:572] = True
    assert ink[lyric].any() and removed[ink & lyric].all(), "lyric blob was kept"
    kept_zone = np.zeros_like(ink)
    kept_zone[:, 290:315] = True  # notehead + stem
    assert not (removed & kept_zone).any(), "attached note or stem was erased"
    staff_rows = np.abs(np.arange(PAGE_H)[:, None] - CENTER) <= 2 * SPACING_PX
    assert not (removed & staff_rows & (np.arange(PAGE_W) < 250)).any(), "staff lines were erased"


def test_mask_keeps_ledger_line_note() -> None:
    page = _synthetic_page(0.0)
    y = CENTER - 3 * SPACING_PX  # first ledger line above the staff
    page[y - 1:y + 1, 380:420] = 0
    cv2.ellipse(page, (400, y), (8, 5), 0, 0, 360, 0, 2)  # open whole note on it
    assert not _removed(page).any()


def _draw_ledger_note(page: np.ndarray, ledger: int, below: bool = False, hollow: bool = True) -> None:
    """Stemless note on the ``ledger``-th ledger line, with every ledger line up to it drawn."""
    sign = 1 if below else -1
    for k in range(1, ledger + 1):
        y = CENTER + sign * (2 + k) * SPACING_PX
        page[y - 1:y + 1, 388:412] = 0
    y = CENTER + sign * (2 + ledger) * SPACING_PX
    cv2.ellipse(page, (400, y), (9, 5), 0, 0, 360, 0, 2 if hollow else -1)


def test_mask_keeps_high_and_low_ledger_notes() -> None:
    """F1 (senior-reviewer 2036dd2): notes on the 2nd-4th ledger line and their lone lines survive."""
    for ledger in (1, 2, 3, 4):
        for below in (False, True):
            for hollow in (True, False):
                page = _synthetic_page(0.0)
                _draw_ledger_note(page, ledger, below, hollow)
                zone = np.zeros(page.shape, dtype=bool)
                zone[:, 380:420] = True
                zone[CENTER - 2 * SPACING_PX - 1:CENTER + 2 * SPACING_PX + 1] = False  # staff itself
                assert not (_removed(page) & zone).any(), f"ledger={ledger} below={below} hollow={hollow}"


def test_mask_still_removes_underscore_off_ledger_rows() -> None:
    """A lyric extender that is not on a ledger row 1..4 spacings out stays erased."""
    page = _synthetic_page(0.0)
    y = CENTER + 2 * SPACING_PX + int(1.5 * SPACING_PX)
    page[y - 1:y + 1, 388:412] = 0
    assert _removed(page)[y - 1:y + 1, 388:412].all()


def _draw_tie(page: np.ndarray) -> int:
    """Draws two noteheads joined by a long flat tie above the staff; returns the tie's y."""
    head_y = CENTER - SPACING_PX
    for x in (300, 500):
        cv2.ellipse(page, (x, head_y), (7, 5), 0, 0, 360, 0, -1)
    tie_y = CENTER - 3 * SPACING_PX + 2  # 1+ spacing above the top line: off the band
    cv2.polylines(page, [np.array([(300, head_y - 5), (306, tie_y + 8), (316, tie_y),
                                   (484, tie_y), (494, tie_y + 8), (500, head_y - 5)], np.int32)],
                  False, 0, 2)
    return tie_y


def test_mask_keeps_long_tie_but_removes_neighbor_line_and_lyric() -> None:
    """A tie survives; an isolated neighbouring staff line and a lyric blob do not.

    Regression for BUG-015: the tie's flat middle is thin and off the band and used to be
    blanked as a "neighbour staff line". It is joined to noteheads that sit on the staff, so it
    must stay; a line touching nothing attached must go.
    """
    page = _synthetic_page(0.0)
    tie_y = _draw_tie(page)
    neighbor_y = CENTER + 4 * SPACING_PX  # a stray line below, clear of the staff band
    page[neighbor_y - 1:neighbor_y + 1, 60:1140] = 0
    lyric_top = neighbor_y + 7
    for k in range(6):
        page[lyric_top:lyric_top + 8, 700 + k * 12:700 + k * 12 + 8] = 0
    removed, ink = _removed(page), page < DARK

    tie_zone = np.zeros_like(ink)
    tie_zone[tie_y - 3:tie_y + 9, 296:504] = True
    assert (ink & tie_zone).sum() > 0
    assert not (removed & tie_zone).any(), "tie was deleted"
    line_zone = np.zeros_like(ink)
    line_zone[neighbor_y - 1:neighbor_y + 1, 100:1100] = True
    assert removed[ink & line_zone].all(), "neighbour staff line was kept"
    lyric_zone = np.zeros_like(ink)
    lyric_zone[lyric_top:lyric_top + 8, 700:772] = True
    assert removed[ink & lyric_zone].all(), "lyric blob was kept"


def test_thick_beam_between_stems_is_never_removed() -> None:
    """A heavy horizontal beam above the staff, joined by two stems, must survive."""
    page = _synthetic_page(0.0)
    beam_y = CENTER - 4 * SPACING_PX  # well above the band: only the stems attach it
    for x in (300, 420):
        cv2.ellipse(page, (x, CENTER + SPACING_PX // 2), (7, 5), 0, 0, 360, 0, -1)
        page[beam_y:CENTER + SPACING_PX // 2, x + 6:x + 8] = 0
    page[beam_y:beam_y + 5, 300:428] = 0  # 5 px ~ 0.4 spacing, the usual beam weight
    beam = np.zeros(page.shape, dtype=bool)
    beam[beam_y:beam_y + 5, 300:428] = True
    assert not (_removed(page) & beam).any(), "beam ink was removed"


def _draw_quarter_rest(page: np.ndarray) -> None:
    s = SPACING_PX
    pts = np.array([(400, CENTER - s), (410, CENTER - s // 2), (402, CENTER),
                    (411, CENTER + s // 2), (404, CENTER + s)], np.int32)
    cv2.polylines(page, [pts], False, 0, 2)


def _draw_eighth_rest(page: np.ndarray) -> None:
    cv2.circle(page, (500, CENTER - SPACING_PX // 2), 3, 0, -1)
    cv2.line(page, (503, CENTER - SPACING_PX // 2), (496, CENTER + SPACING_PX), 0, 2)


def _draw_half_rest(page: np.ndarray) -> None:
    page[CENTER - 5:CENTER, 600:620] = 0  # sits on the middle line


def _draw_whole_rest(page: np.ndarray) -> None:
    page[CENTER - SPACING_PX:CENTER - SPACING_PX + 5, 700:720] = 0  # hangs from the second line


REST_DRAWERS = {"quarter": _draw_quarter_rest, "eighth": _draw_eighth_rest,
                "half": _draw_half_rest, "whole": _draw_whole_rest}


def test_thin_rest_glyphs_survive_mask_and_crop() -> None:
    """Rests are the thinnest glyphs; neither the mask nor the strip crop may erase them.

    Rests carry no stem, so they survive the mask only by lying inside the staff band; that is
    the property under test (a rest must never be mistaken for text or a neighbour line). The
    crop is exercised through the native-source path with a 2x source, which is what Stage 2
    now feeds it, and must still show the rest's ink.
    """
    lines_only = _synthetic_page(0.0) < DARK
    box = {"x1": 0, "x2": PAGE_W, "y1": CENTER - 2 * SPACING_PX, "y2": CENTER + 2 * SPACING_PX}
    bare = cv2.resize(_synthetic_page(0.0), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    bare_strip = s2._crop_and_resize(_synthetic_page(0.0), box, s2.STRIP_HEIGHT, source=bare)
    for name, draw in REST_DRAWERS.items():
        page = _synthetic_page(0.0)
        draw(page)
        glyph = (page < DARK) & ~lines_only
        assert glyph.any(), name
        assert not (_removed(page) & glyph).any(), f"{name} rest erased by mask"
        native = cv2.resize(page, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        strip = s2._crop_and_resize(page, box, s2.STRIP_HEIGHT, source=native)
        assert strip.shape == bare_strip.shape
        gain = int((strip < 200).sum()) - int((bare_strip < 200).sum())
        assert gain > 0, f"{name} rest vanished from the strip"


def test_crop_from_native_source_maps_geometry() -> None:
    """A 2x source cropped through the detection-page box lands on the same content, area-shrunk."""
    page = _synthetic_page(0.0)
    _draw_note_and_lyric(page)
    native = cv2.resize(page, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    box = {"x1": 0, "x2": PAGE_W, "y1": CENTER - 2 * SPACING_PX, "y2": CENTER + 2 * SPACING_PX}
    a = s2._crop_and_resize(page, box, s2.STRIP_HEIGHT)
    b = s2._crop_and_resize(page, box, s2.STRIP_HEIGHT, source=native)
    assert abs(a.shape[1] - b.shape[1]) <= 2
    w = min(a.shape[1], b.shape[1])
    assert abs(float(a[:, :w].mean()) - float(b[:, :w].mean())) < 3.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
