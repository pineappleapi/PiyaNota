"""Viewing aid for hand annotation only (not pipeline code): zoomed crop of the page overview (1500x2000
coords) with measured staff lines drawn red and the spaces between them drawn green, so head centres can be
read against real line positions instead of by eye. Lines are re-measured per 40 px column band (pages curl).
usage: python overlay.py page x0 y0 x1 y1 scale out_name"""
import sys
import numpy as np
from PIL import Image, ImageOps, ImageDraw
p = int(sys.argv[1]); x0, y0, x1, y1 = (float(v) for v in sys.argv[2:6]); sc = float(sys.argv[6])
im = ImageOps.exif_transpose(Image.open(f"D:/PiyaNota/data/piyanota_dataset/non_nobis_domine_pg0{p}.jpg")).convert("L")
f = im.width / 1500
c = im.crop((int(x0 * f), int(y0 * f), int(x1 * f), int(y1 * f)))
a = np.asarray(c, dtype=float)
out = c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS).convert("RGB")
d = ImageDraw.Draw(out)
band = int(40 * f)
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
        d.line([(bx * sc, y * sc), ((bx + band) * sc, y * sc)], fill=(255, 0, 0), width=1)
    for u, v in zip(ys, ys[1:]):
        if v - u < 25 * f:
            d.line([(bx * sc, (u + v) / 2 * sc), ((bx + band) * sc, (u + v) / 2 * sc)], fill=(0, 170, 0), width=1)
out.save(f"crops/{sys.argv[7]}.png"); print(out.size)
