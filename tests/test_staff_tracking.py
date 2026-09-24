"""Synthetic regression tests for Stage 1 staff tracking/dewarp and Stage 2 crop clamping.

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
    assert s2.STRIP_HEIGHT == 64


def _masked_pair(draw) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (page, unmasked strip, masked strip) for the first synthetic staff."""
    page = _synthetic_page(0.0)
    draw(page)
    box = {"x1": 0, "x2": PAGE_W, "y1": 200 - 2 * SPACING_PX, "y2": 200 + 2 * SPACING_PX}
    off = s2._crop_and_resize(page, box, s2.STRIP_HEIGHT, mask_lyrics=False)
    on = s2._crop_and_resize(page, box, s2.STRIP_HEIGHT, mask_lyrics=True)
    return page, off, on


def _draw_note_and_lyric(page: np.ndarray) -> None:
    cv2.ellipse(page, (300, 200 + SPACING_PX // 2), (7, 5), 0, 0, 360, 0, -1)  # notehead
    page[200 - 3 * SPACING_PX:200 + SPACING_PX // 2, 306:308] = 0  # stem up
    for k in range(6):  # lyric-like word blobs 1.5 spacings below the bottom line
        page[200 + 3 * SPACING_PX + 2:200 + 3 * SPACING_PX + 10, 500 + k * 12:500 + k * 12 + 8] = 0


def test_mask_removes_lyric_blob_below_staff() -> None:
    _, off, on = _masked_pair(_draw_note_and_lyric)
    assert (off < 128).sum() > (on < 128).sum()
    lyric_cols = slice(int(500 * on.shape[1] / PAGE_W), int(575 * on.shape[1] / PAGE_W))
    lyric_rows = slice(int(on.shape[0] * 0.8), on.shape[0])
    assert (on[lyric_rows, lyric_cols] < 128).sum() == 0
    assert (off[lyric_rows, lyric_cols] < 128).sum() > 0


def test_mask_keeps_attached_note_and_staff() -> None:
    _, off, on = _masked_pair(_draw_note_and_lyric)
    col = int(300 * on.shape[1] / PAGE_W)
    window = (slice(0, on.shape[0]), slice(col - 6, col + 6))
    assert (on[window] < 128).sum() == (off[window] < 128).sum()
    # Every staff pixel of the unmasked strip is still ink in the masked one.
    mid = on.shape[0] // 2
    assert np.array_equal(on[mid - 3:mid + 3, :int(200 * on.shape[1] / PAGE_W)],
                          off[mid - 3:mid + 3, :int(200 * on.shape[1] / PAGE_W)])


def test_mask_keeps_ledger_line_note() -> None:
    def draw(page: np.ndarray) -> None:
        y = 200 - 3 * SPACING_PX  # first ledger line above the staff
        page[y - 1:y + 1, 380:420] = 0
        cv2.ellipse(page, (400, y), (8, 5), 0, 0, 360, 0, 2)  # open whole note on it
    _, off, on = _masked_pair(draw)
    assert (on < 128).sum() == (off < 128).sum()


def test_mask_off_reproduces_unmasked_crop() -> None:
    page, off, _ = _masked_pair(_draw_note_and_lyric)
    box = {"x1": 0, "x2": PAGE_W, "y1": 200 - 2 * SPACING_PX, "y2": 200 + 2 * SPACING_PX}
    again = s2._crop_and_resize(page, box, s2.STRIP_HEIGHT, mask_lyrics=False)
    assert np.array_equal(off, again)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
