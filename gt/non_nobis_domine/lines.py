"""Viewing aid for hand annotation only (not pipeline code): staff-line rows in a column band of the page
overview (1500x2000 coords), so note-head centres can be measured against real line positions.
usage: python lines.py page x0 y0 x1 y1"""
import sys
import numpy as np
from PIL import Image, ImageOps
p = int(sys.argv[1]); x0, y0, x1, y1 = (float(v) for v in sys.argv[2:6])
im = ImageOps.exif_transpose(Image.open(f"D:/PiyaNota/data/piyanota_dataset/non_nobis_domine_pg0{p}.jpg")).convert("L")
f = im.width / 1500
a = np.asarray(im.crop((int(x0 * f), int(y0 * f), int(x1 * f), int(y1 * f))), dtype=float)
dark = (a < a.mean() - 40).mean(axis=1)
rows = [i for i in range(1, len(dark) - 1) if dark[i] > 0.5 and dark[i] >= dark[i - 1] and dark[i] >= dark[i + 1]]
print("line rows (overview y):", [round(y0 + r / f, 1) for r in rows])
