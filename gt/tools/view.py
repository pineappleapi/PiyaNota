"""Viewing aid for hand annotation only (not pipeline code). Zoomed crop of a page overview (1500x2000 coords),
optionally with measured staff lines (red) and spaces (green) re-measured per 40 px column band (pages curl).
usage: python view.py piece page x0 y0 x1 y1 scale out_png [--overlay]"""
import sys
import numpy as np
from PIL import Image, ImageOps, ImageDraw
piece, p = sys.argv[1], int(sys.argv[2])
x0, y0, x1, y1 = (float(v) for v in sys.argv[3:7]); sc = float(sys.argv[7]); out_png = sys.argv[8]
im = ImageOps.exif_transpose(Image.open(f"D:/PiyaNota/data/piyanota_dataset/{piece}_pg{p:02d}.jpg")).convert("L")
f = im.width / 1500
c = im.crop((int(x0 * f), int(y0 * f), int(x1 * f), int(y1 * f)))
a = np.asarray(c, dtype=float)
out = c.resize((int(c.width / f * sc), int(c.height / f * sc)), Image.LANCZOS).convert("RGB")
if "--overlay" in sys.argv:
    d = ImageDraw.Draw(out)
    band = int(40 * f); k = sc / f
    for bx in range(0, a.shape[1], band):
        sub = a[:, bx:bx + band]
        dark = (sub < sub.mean() - 40).mean(axis=1)
        rows = [i for i in range(1, len(dark) - 1) if dark[i] > 0.6 and dark[i] >= dark[i - 1] and dark[i] >= dark[i + 1]]
        merged = []
        for r in rows:
            if merged and r - merged[-1][-1] <= 3: merged[-1].append(r)
            else: merged.append([r])
        ys = [sum(m) / len(m) for m in merged]
        for y in ys:
            d.line([(bx * k, y * k), ((bx + band) * k, y * k)], fill=(255, 0, 0), width=1)
        for u, v in zip(ys, ys[1:]):
            if v - u < 25 * f:
                d.line([(bx * k, (u + v) / 2 * k), ((bx + band) * k, (u + v) / 2 * k)], fill=(0, 170, 0), width=1)
out.save(out_png); print(out.size)
