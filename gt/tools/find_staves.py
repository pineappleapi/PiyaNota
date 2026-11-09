"""Viewing aid for hand annotation only. Prints staff y-ranges (1500-wide overview coords) per page, from the
row-darkness projection of the middle 60% of the page width (stafflines are the only long horizontal ink).
usage: python find_staves.py piece n_pages"""
import sys
import numpy as np
from PIL import Image, ImageOps
piece, n = sys.argv[1], int(sys.argv[2])
for p in range(1, n + 1):
    im = ImageOps.exif_transpose(Image.open(f"D:/PiyaNota/data/piyanota_dataset/{piece}_pg{p:02d}.jpg")).convert("L")
    im = im.resize((1500, int(im.height * 1500 / im.width)))
    a = np.asarray(im, dtype=float)[:, 300:1200]
    thr = a.mean(axis=1, keepdims=True) - 35
    dark = (a < np.minimum(thr, 150)).mean(axis=1)
    rows = np.where(dark > 0.35)[0]
    lines = []
    for r in rows:
        if lines and r - lines[-1][-1] <= 2: lines[-1].append(r)
        else: lines.append([r])
    ys = [float(np.mean(l)) for l in lines]
    staves, cur = [], []
    for y in ys:
        if cur and y - cur[-1] > 22: staves.append(cur); cur = []
        cur.append(y)
    if cur: staves.append(cur)
    staves = [s for s in staves if len(s) >= 4]
    print(f"p{p} h={im.height} staves={len(staves)}: " + " ".join(f"{s[0]:.0f}-{s[-1]:.0f}" for s in staves))
