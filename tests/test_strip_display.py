"""strip_display: lyrics-kept app view must match strip_source geometry and not change Stage 2-3 inputs."""
from pathlib import Path

import numpy as np
import pytest

import stage1_preprocessing as s1

# Real phone photo; outside the repo (data/ is untracked), so the test skips on a fresh checkout.
PHOTO = Path("D:/PiyaNota/data/chords_dataset/Moonriver/Moonriver/p01.JPG")
# strip_source paints erased lyrics/ink paper-grey; the display page must keep them dark.
MIN_KEPT_INK_PX = 50_000


@pytest.mark.skipif(not PHOTO.exists(), reason="Moonriver photo not available")
def test_strip_display_keeps_lyrics_with_same_geometry() -> None:
    page = s1.preprocess_score_page(str(PHOTO), keep_display=True)
    assert page.strip_source is not None and page.strip_display is not None
    assert page.strip_display.shape == page.strip_source.shape  # highlights are scaled to this size
    assert page.strip_display.dtype == np.uint8
    extra_ink = int(((page.strip_display < 128) & (page.strip_source >= 128)).sum())
    assert extra_ink > MIN_KEPT_INK_PX
    # Nothing the strips use is darker than the display page, so the display only ever adds ink.
    assert int(((page.strip_source < 128) & (page.strip_display >= 128)).sum()) == 0
