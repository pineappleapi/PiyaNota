"""A7 real-stream draw (train_phase2.RealDraw): views per printed staff-system are capped per epoch and per run."""

import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "phase2"))
import train_phase2 as tp  # noqa: E402


def test_caps_bind_and_lower_the_draw() -> None:
    draw = tp.RealDraw([[10, 11], [12]], per_epoch=2, total=3, pieces=["A", "B"])
    gen = torch.Generator().manual_seed(0)
    first = draw.draw(10, gen)
    assert len(first) == 4                                  # 2 groups x 2 per epoch
    assert set(first) <= {10, 11, 12}
    second = draw.draw(10, gen)
    assert len(second) == 2 and draw.at_cap() == 2          # each group stops at 3 views over the run
    assert draw.draw(10, gen) == [] and draw.last_epoch == 0
    assert draw.views_by_piece() == {"A": 0.5, "B": 0.5}


def test_pdf_and_camera_strips_share_one_budget() -> None:
    draw = tp.RealDraw([[0, 1, 2]], per_epoch=5, total=5)   # one staff: PDF strip + two camera strips
    assert len(draw.draw(20, torch.Generator().manual_seed(1))) == 5
