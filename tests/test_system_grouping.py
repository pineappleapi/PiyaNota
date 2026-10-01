"""BUG-042: staves joined by a system line across a 4-staff boundary are rejected, not re-chunked.

Run with ``python -m pytest tests``. Synthetic pages only (no photos, no YOLO).
"""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage1_preprocessing as s1  # noqa: E402
import stage2_detection as s2  # noqa: E402

SPACING_PX = 12
STAFF_PITCH_PX = 120      # staff center to staff center inside a system
SYSTEM_GAP_PX = 60        # extra space between systems
STAFF_X0, STAFF_X1 = 100, 1100
SYSTEM_LINE_X = 98        # just left of the staff start, as engraved
PAGE_W = 1200


def _page(systems: list[int], linked: bool = True) -> tuple[np.ndarray, list[s1.StaffBand], list[float]]:
    """Draws systems of the given staff counts; each system's staves are joined by one system line."""
    centers: list[float] = []
    y = 80.0
    for n in systems:
        for _ in range(n):
            centers.append(y)
            y += STAFF_PITCH_PX
        y += SYSTEM_GAP_PX
    page = np.full((int(y) + 80, PAGE_W), 255, dtype=np.uint8)
    for c in centers:
        for k in range(-2, 3):
            page[int(c + k * SPACING_PX), STAFF_X0:STAFF_X1] = 0
    if linked:
        i = 0
        for n in systems:
            top = int(centers[i] - 2 * SPACING_PX)
            bot = int(centers[i + n - 1] + 2 * SPACING_PX)
            page[top:bot + 1, SYSTEM_LINE_X:SYSTEM_LINE_X + 3] = 0
            i += n
    staves = [s1.StaffBand(center=c, spacing=float(SPACING_PX)) for c in centers]
    return page, staves, [float(STAFF_X0)] * len(centers)


def test_links_follow_system_lines() -> None:
    page, staves, xs = _page([4, 4])
    assert s1.staff_system_links(page, staves, xs) == [True, True, True, False, True, True, True]


def test_eight_staff_system_is_linked_across_the_chunk_boundary() -> None:
    page, staves, xs = _page([8])
    assert s1.staff_system_links(page, staves, xs) == [True] * 7


def test_wide_blob_in_gap_is_not_a_link() -> None:
    """A page-edge shadow fills the gap rows but is wider than a connector."""
    page, staves, xs = _page([4, 4], linked=False)
    top, bot = int(staves[3].center), int(staves[4].center)
    page[top:bot, 60:60 + 4 * SPACING_PX] = 0
    assert s1.staff_system_links(page, staves, xs)[3] is False


def test_grouping_check_rejects_eight_staff_system() -> None:
    with pytest.raises(ValueError, match="unsupported_staff_layout"):
        s2._check_system_grouping([True] * 7, page_index=1, status="checked")


def test_grouping_check_accepts_satb_and_missing_links_inside_a_system() -> None:
    s2._check_system_grouping([True, True, True, False, True, True, True], page_index=1, status="checked")
    # A faint bracket (False or None inside a system of 4) must not reject.
    s2._check_system_grouping([True, None, True, False, True, False, True], page_index=1, status="checked")


def test_grouping_check_rejects_satb_plus_piano() -> None:
    """Two 6-staff systems (SATB + piano) total 12 staves, so only the links can catch them."""
    with pytest.raises(ValueError, match="unsupported_staff_layout"):
        s2._check_system_grouping([True] * 5 + [False] + [True] * 5, page_index=1, status="checked")


def _stage1(centers: list[float], links: list[bool | None]) -> s1.PreprocessedPage:
    staves = [s1.StaffBand(center=c, spacing=float(SPACING_PX)) for c in centers]
    return s1.PreprocessedPage(detect=np.zeros((1, 1), np.uint8), strip_source=None, angle=0.0,
                               mask_applied=False, removed_px=0, staff_links=links,
                               link_staves=staves)


def _boxes(centers: list[float]) -> list[dict]:
    return [{"cy": c} for c in centers]


def test_links_mapped_by_position() -> None:
    centers = [100.0 + 120.0 * k for k in range(8)]
    page = _stage1(centers, [True] * 7)
    links, status = s2._staff_links_for(_boxes([c + 5 for c in centers]), page, 1)
    assert links == [True] * 7 and status == "checked"


def test_staff_missed_by_stage1_blanks_only_its_gaps() -> None:
    """Stage 1 missed staff 6 of 8: gaps 5-6 and 6-7 are unknown, the others keep their links."""
    centers = [100.0 + 120.0 * k for k in range(8)]
    tracked = centers[:5] + centers[6:]
    page = _stage1(tracked, [True, True, True, True, False, True])
    links, status = s2._staff_links_for(_boxes(centers), page, 1)
    assert links == [True, True, True, True, None, None, True]
    assert status == "checked"  # the 4/5 boundary is measured, so the 8-staff system is caught
    with pytest.raises(ValueError, match="unsupported_staff_layout"):
        s2._check_system_grouping(links, 1, status="checked")


def test_unmeasured_boundary_is_partial() -> None:
    centers = [100.0 + 120.0 * k for k in range(8)]
    page = _stage1(centers, [True, True, True, None, True, True, True])
    assert s2._staff_links_for(_boxes(centers), page, 1)[1] == "partial"


def test_no_stage1_page_is_unchecked() -> None:
    assert s2._staff_links_for(_boxes([100.0, 220.0]), _stage1([], []), 1) == (None, "no_tracked_staves")


def test_stage1_fills_links_before_blanking(tmp_path: Path) -> None:
    """Wiring: preprocess_score_page measures the bracket before border/lyric blanking erases it."""
    page, _, _ = _page([4, 4])
    path = tmp_path / "two_systems.png"
    cv2.imwrite(str(path), page)
    result = s1.preprocess_score_page(str(path), build_strip_source=False)
    assert result.staff_links == [True, True, True, False, True, True, True]
    assert result.link_staves is not None and len(result.link_staves) == 8


@pytest.mark.parametrize("status", ["partial", "no_tracked_staves"])
def test_unverified_grouping_rejected(status: str) -> None:
    """User ruling 2026-10-01: a page whose 4-staff boundaries were not all measured is rejected, not passed."""
    links = None if status == "no_tracked_staves" else [True, True, True, None, True, True, True]
    with pytest.raises(ValueError, match="unsupported_staff_layout"):
        s2._check_system_grouping(links, page_index=1, status=status)


def test_short_tuple_is_a_caller_error() -> None:
    """A 3-tuple caller fails before YOLO loads, instead of every page looking like a layout reject."""
    with pytest.raises(TypeError, match="PreprocessedPage"):
        s2.detect_staff_regions([(np.zeros((8, 8), np.uint8), 1, None)], model_weights="unused.pt",
                                save_strips=False)
