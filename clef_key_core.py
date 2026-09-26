"""Clef and key-signature crop classifier: the shared crop contract and the network.

This file is the single source of truth for BOTH training (the Kaggle notebook
training/piyanota-clef-keysig-kaggle.ipynb writes this exact text to
/kaggle/working/clef_key_core.py) and inference (Stage 3 must import this file
unchanged). The crop is defined in staff spaces, so it does not depend on image
resolution. Changing any constant below changes what the network sees and
invalidates trained weights: bump CROP_SPEC_VERSION when you do.
The local script training/train_clef_key.py imports this file directly (no copy).

Input contract (decided 2026-09-26, see docs/decisions/piya-106-clef-keysig-detector-plan.md):
the page passed to make_input() is BINARY, ink = 0 and paper = 255, produced the
way Stage 1 builds its native strip source (adaptive Gaussian threshold at native
resolution) but taken BEFORE the non-staff-ink mask. The mask keeps only ink
attached to the staff, and the small "8" under a treble-8vb clef is not attached,
so the masked page can lose exactly the detail this model exists to see.

The network input is a fixed INPUT_H x INPUT_W image, so there is no padding and
the batch composition cannot change a prediction (BatchNorm runs in eval mode).
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn

CROP_SPEC_VERSION: int = 1

# Geometry of the crop, in staff spaces (sp = distance between two staff lines).
PX_PER_SPACE: int = 8            # output resolution; the "8" of treble-8vb is ~1.2 sp tall -> ~10 px
CROP_LEFT_SPACES: float = 1.0    # context left of the first staff-line column (bracket, barline)
CROP_RIGHT_SPACES: float = 15.0  # clef (~3 sp) + up to 7 key accidentals (~1 sp each) + slack
CROP_ABOVE_SPACES: float = 4.0   # a G clef rises ~2 sp above the top line
CROP_BELOW_SPACES: float = 4.0   # the treble-8vb "8" sits ~1.5-3 sp below the bottom line
STAFF_SPACES: float = 4.0        # five lines = four spaces
INPUT_W: int = int(round((CROP_LEFT_SPACES + CROP_RIGHT_SPACES) * PX_PER_SPACE))                  # 128
INPUT_H: int = int(round((CROP_ABOVE_SPACES + STAFF_SPACES + CROP_BELOW_SPACES) * PX_PER_SPACE))  # 96

# Gaussian pre-blur before down-sampling, as a fraction of the down-scale factor, so thin
# strokes are area-averaged instead of aliased away (same idea as Stage 1's strip source blur).
ANTIALIAS_SIGMA_PER_DOWNSCALE: float = 0.4

# staff_left_edge(): a column is "inside the staff" once at least EDGE_MIN_LINES of the five
# lines carry uninterrupted ink for EDGE_MIN_RUN_SPACES staff spaces to its right.
EDGE_MIN_RUN_SPACES: float = 2.0
EDGE_MIN_LINES: int = 3
EDGE_LINE_TOL_SPACES: float = 0.15

CLEF_CLASSES: Tuple[str, ...] = ("G", "G8vb", "F", "other")
KEY_MIN: int = -7   # 7 flats
KEY_MAX: int = 7    # 7 sharps
KEY_CLASSES: Tuple[int, ...] = tuple(range(KEY_MIN, KEY_MAX + 1))
KEY_IGNORE_INDEX: int = -100


def key_to_index(key: int) -> int:
    """Signed key (-7 = 7 flats ... +7 = 7 sharps) to class index."""
    if not KEY_MIN <= key <= KEY_MAX:
        raise ValueError(f"key {key} outside [{KEY_MIN}, {KEY_MAX}]")
    return key - KEY_MIN


def index_to_key(index: int) -> int:
    """Class index to signed key."""
    return int(index) + KEY_MIN


def staff_left_edge(binary: np.ndarray, top_line_y: float, bottom_line_y: float,
                    search_from_x: int = 0) -> Optional[int]:
    """Finds the first column of the staff lines (where the clef zone starts).

    Args:
        binary: Page, ink < 128.
        top_line_y: Centre row of the top staff line.
        bottom_line_y: Centre row of the bottom staff line.
        search_from_x: Ignore columns left of this.

    Returns:
        Column index, or None if no column has enough continuous line ink.
    """
    ink = binary < 128
    h, w = ink.shape
    sp = (bottom_line_y - top_line_y) / STAFF_SPACES
    if sp <= 0:
        raise ValueError("bottom_line_y must be below top_line_y")
    run = max(2, int(round(EDGE_MIN_RUN_SPACES * sp)))
    tol = max(1, int(round(EDGE_LINE_TOL_SPACES * sp)))
    if run >= w:
        return None
    hits = np.zeros(w - run + 1, dtype=np.int32)
    for k in range(5):
        y = int(round(top_line_y + k * sp))
        lo, hi = max(0, y - tol), min(h, y + tol + 1)
        if lo >= hi:
            continue
        row = ink[lo:hi].any(axis=0).astype(np.int32)
        cs = np.concatenate([[0], np.cumsum(row)])
        hits += ((cs[run:] - cs[:-run]) == run).astype(np.int32)
    cand = np.nonzero(hits[search_from_x:] >= EDGE_MIN_LINES)[0]
    return int(cand[0] + search_from_x) if len(cand) else None


def warp_staff_region(img: np.ndarray, x0: float, top_line_y: float, bottom_line_y: float,
                      px_per_space: float, left_sp: float, right_sp: float,
                      above_sp: float, below_sp: float, *, dx_spaces: float = 0.0,
                      dy_spaces: float = 0.0, scale: float = 1.0,
                      angle_deg: float = 0.0) -> np.ndarray:
    """Resamples a staff-aligned window of a uint8 image (paper = 255) to px_per_space.

    The window is anchored at (x0, staff centre) and measured in staff spaces. dx/dy/scale/
    angle perturb the window (training augmentation and robustness to geometry error);
    at inference they are all neutral.

    Returns:
        uint8 array (round((above+4+below)*pps), round((left+right)*pps)).
    """
    sp = (bottom_line_y - top_line_y) / STAFF_SPACES
    if sp <= 0:
        raise ValueError("bottom_line_y must be below top_line_y")
    out_w = int(round((left_sp + right_sp) * px_per_space))
    out_h = int(round((above_sp + STAFF_SPACES + below_sp) * px_per_space))
    sp_eff = sp * scale
    s = sp_eff / px_per_space                      # source px per output px
    ax = x0 + dx_spaces * sp
    ay = 0.5 * (top_line_y + bottom_line_y) + dy_spaces * sp
    ox0 = -left_sp * sp_eff + 0.5 * s
    oy0 = -(above_sp + STAFF_SPACES / 2.0) * sp_eff + 0.5 * s
    th = math.radians(angle_deg)
    c, sn = math.cos(th), math.sin(th)
    m = np.array([[c * s, -sn * s, ax + c * ox0 - sn * oy0],
                  [sn * s, c * s, ay + sn * ox0 + c * oy0]], dtype=np.float64)

    # Work on the bounding region only (pages are up to 4032 px), padded for the blur.
    corners = np.array([[0, 0, 1], [out_w, 0, 1], [0, out_h, 1], [out_w, out_h, 1]], dtype=np.float64)
    src = corners @ m.T
    sigma = ANTIALIAS_SIGMA_PER_DOWNSCALE * s if s > 1.0 else 0.0
    pad = int(math.ceil(3 * sigma)) + 2
    rx0 = int(math.floor(src[:, 0].min())) - pad
    ry0 = int(math.floor(src[:, 1].min())) - pad
    rx1 = int(math.ceil(src[:, 0].max())) + pad
    ry1 = int(math.ceil(src[:, 1].max())) + pad
    h, w = img.shape[:2]
    region = np.full((ry1 - ry0, rx1 - rx0), 255, dtype=np.uint8)
    sx0, sy0, sx1, sy1 = max(0, rx0), max(0, ry0), min(w, rx1), min(h, ry1)
    if sx0 < sx1 and sy0 < sy1:
        region[sy0 - ry0:sy1 - ry0, sx0 - rx0:sx1 - rx0] = img[sy0:sy1, sx0:sx1]
    if sigma > 0:
        region = cv2.GaussianBlur(region, (0, 0), sigma)
    m_local = m.copy()
    m_local[0, 2] -= rx0
    m_local[1, 2] -= ry0
    return cv2.warpAffine(region, m_local, (out_w, out_h),
                          flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def make_input(binary_page: np.ndarray, x0: float, top_line_y: float, bottom_line_y: float, *,
               dx_spaces: float = 0.0, dy_spaces: float = 0.0, scale: float = 1.0,
               angle_deg: float = 0.0) -> np.ndarray:
    """The network input for one staff: float32 (INPUT_H, INPUT_W) in [0, 1], ink = 1.

    Args:
        binary_page: Binary page, ink = 0, paper = 255 (see module docstring: UNMASKED).
        x0: First column of the staff lines (staff_left_edge()).
        top_line_y, bottom_line_y: Centre rows of the outer staff lines.
    """
    if binary_page.ndim != 2 or binary_page.dtype != np.uint8:
        raise ValueError("binary_page must be a 2-D uint8 array")
    crop = warp_staff_region(binary_page, x0, top_line_y, bottom_line_y, PX_PER_SPACE,
                             CROP_LEFT_SPACES, CROP_RIGHT_SPACES, CROP_ABOVE_SPACES,
                             CROP_BELOW_SPACES, dx_spaces=dx_spaces, dy_spaces=dy_spaces,
                             scale=scale, angle_deg=angle_deg)
    return (255.0 - crop.astype(np.float32)) / 255.0


def _conv_block(c_in: int, c_out: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(c_in, c_out, 3, padding=1, bias=False), nn.BatchNorm2d(c_out), nn.ReLU(inplace=True),
        nn.Conv2d(c_out, c_out, 3, padding=1, bias=False), nn.BatchNorm2d(c_out), nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
    )


class ClefKeyNet(nn.Module):
    """Small two-head CNN: clef class and signed key-signature count.

    The flattened 6x8 map (not a global average pool) keeps horizontal position, which the
    key head needs to count accidentals and to separate the key signature from the first
    note's accidentals.
    """

    def __init__(self, width: int = 32, dropout: float = 0.3) -> None:
        super().__init__()
        self.features = nn.Sequential(
            _conv_block(1, width), _conv_block(width, 2 * width),
            _conv_block(2 * width, 4 * width), _conv_block(4 * width, 4 * width),
        )
        self.reduce = nn.Sequential(nn.Conv2d(4 * width, 64, 1, bias=False),
                                    nn.BatchNorm2d(64), nn.ReLU(inplace=True))
        flat = 64 * (INPUT_H // 16) * (INPUT_W // 16)
        self.trunk = nn.Sequential(nn.Flatten(), nn.Dropout(dropout), nn.Linear(flat, 256),
                                   nn.ReLU(inplace=True), nn.Dropout(dropout))
        self.clef_head = nn.Linear(256, len(CLEF_CLASSES))
        self.key_head = nn.Linear(256, len(KEY_CLASSES))

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        f = self.trunk(self.reduce(self.features(x)))
        return self.clef_head(f), self.key_head(f)


@torch.no_grad()
def predict_probs(model: ClefKeyNet, inputs: np.ndarray, clef_temperature: float,
                  key_temperature: float, device: Optional[torch.device] = None
                  ) -> Tuple[np.ndarray, np.ndarray]:
    """Temperature-scaled class probabilities for a batch of make_input() arrays (N, H, W)."""
    device = device or next(model.parameters()).device
    model.eval()
    x = torch.from_numpy(np.ascontiguousarray(inputs, dtype=np.float32)).unsqueeze(1).to(device)
    clef_logits, key_logits = model(x)
    return (torch.softmax(clef_logits / clef_temperature, dim=1).cpu().numpy(),
            torch.softmax(key_logits / key_temperature, dim=1).cpu().numpy())
