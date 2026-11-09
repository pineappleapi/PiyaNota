"""Print dark runs in a vertical column band of a full-res page (for locating staff lines/noteheads).
usage: python prof.py page x ystart yend [halfwidth] [thresh]"""
import sys
import numpy as np
from PIL import Image
p, x, y0, y1 = (int(v) for v in sys.argv[1:5])
hw = int(sys.argv[5]) if len(sys.argv) > 5 else 2
th = int(sys.argv[6]) if len(sys.argv) > 6 else 110
im = np.array(Image.open(f"crops/pg{p}_full.png").convert("L")).astype(int)
col = im[y0:y1, x - hw:x + hw + 1].mean(1)
runs, start = [], None
for i, v in enumerate(col):
    if v < th and start is None: start = i
    if v >= th and start is not None: runs.append((start + y0, i - 1 + y0)); start = None
if start is not None: runs.append((start + y0, y1))
print(x, [(a, b) if b > a else a for a, b in runs])
