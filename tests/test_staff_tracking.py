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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
