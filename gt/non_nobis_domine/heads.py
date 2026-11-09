"""Viewing aid for hand annotation only (not pipeline code): lists note-head blobs in a region of the page
overview (1500x2000 coords) and names their written pitch from the five staff lines measured at each head's x.
Pitch names are suggestions for the annotator; the final reading is always checked against the image.
usage: python heads.py page clef(G|F) x0 y0 x1 y1"""
import sys

import cv2
import numpy as np
from PIL import Image, ImageOps

EXPECTED_SPACING = 11.5  # overview px between staff lines on these photos (measured, pages 1-2)
L1_INDEX = {"G": 4 * 7 + 2, "F": 2 * 7 + 4}  # diatonic index (octave*7 + letter) of the bottom line: E4 / G2
LETTERS = "CDEFGAB"

p, clef = int(sys.argv[1]), sys.argv[2]
x0, y0, x1, y1 = (float(v) for v in sys.argv[3:7])
im = ImageOps.exif_transpose(Image.open(f"D:/PiyaNota/data/piyanota_dataset/non_nobis_domine_pg0{p}.jpg")).convert("L")
f = im.width / 1500
a = np.asarray(im.crop((int(x0 * f), int(y0 * f), int(x1 * f), int(y1 * f))), dtype=float)
ink = a < a.mean() - 40


def staff_lines(cx: int) -> list[float] | None:
    """Five consecutive line rows near column cx whose gaps all match the expected spacing."""
    half = int(80 * f)
    prof = ink[:, max(0, cx - half):cx + half].mean(axis=1)
    peaks = [i for i in range(1, len(prof) - 1) if prof[i] > 0.45 and prof[i] >= prof[i - 1] and prof[i] >= prof[i + 1]]
    merged: list[list[int]] = []
    for r in peaks:
        if merged and r - merged[-1][-1] <= 3:
            merged[-1].append(r)
        else:
            merged.append([r])
    ys = [sum(m) / len(m) for m in merged]
    strength = {y: prof[int(round(y))] for y in ys}
    sp = EXPECTED_SPACING * f
    best: tuple[float, list[float]] | None = None
    for i in range(len(ys)):  # every chain of 5 rows spaced ~sp apart; beams/extenders are weaker than real lines
        chain = [ys[i]]
        for y in ys[i + 1:]:
            if abs(y - chain[-1] - sp) < 0.3 * sp:
                chain.append(y)
            if len(chain) == 5:
                score = sum(strength[c] for c in chain)
                if best is None or score > best[0]:
                    best = (score, chain)
                break
    return best[1] if best else None


u8 = ink.astype(np.uint8) * 255
cnts, _ = cv2.findContours(u8, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
filled = u8.copy()
cv2.drawContours(filled, cnts, -1, 255, thickness=cv2.FILLED)
k = int(3.5 * f)
body = cv2.morphologyEx(filled, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
n, lab, st, cen = cv2.connectedComponentsWithStats(body)
rows = []
for i in range(1, n):
    x, y, w, h, area = st[i]
    if not (5 * f < h < 26 * f and 6 * f < w < 22 * f):
        continue
    cx = x + w / 2
    L = staff_lines(int(cx))
    if L is None:
        continue
    sp = (L[-1] - L[0]) / 4
    # tall blobs are stacked chord heads (a third apart): report top and bottom head centres
    centres = [y + h / 2] if h < 13 * f else [y + 0.27 * sp * 2, y + h - 0.27 * sp * 2]
    names = []
    for cy in centres:
        step = (L[-1] - cy) / sp * 2
        idx = L1_INDEX[clef] + round(step)
        names.append(f"{LETTERS[idx % 7]}{idx // 7}({step:+.2f})")
    rows.append((x0 + cx / f, y0 + (y + h / 2) / f, w / f, h / f, " ".join(names)))
for r in sorted(rows):
    print(f"x={r[0]:7.1f} y={r[1]:7.1f} size={r[2]:4.1f}x{r[3]:4.1f}  {r[4]}")
