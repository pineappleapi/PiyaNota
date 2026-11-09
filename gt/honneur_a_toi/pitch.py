"""Semi-automatic pitch helper for hand annotation (diagnostic aid only; every result is eyeball-checked).
usage: python pitch.py page clef(G|F) crop_origin_small_x crop_origin_small_y factor  dx,dy [dx,dy ...]
factor = display_factor/scale; full = origin*3 + d*factor.
For each head: finds the 5 staff lines in clean columns beside it, the head centre, and the diatonic step."""
import sys
import numpy as np
from PIL import Image
LET = "CDEFGAB"
BOTTOM = {"G": 4 * 7 + 2, "F": 2 * 7 + 4}  # E4 / G2
p, clef = int(sys.argv[1]), sys.argv[2]
ox, oy, fac = float(sys.argv[3]) * 3, float(sys.argv[4]) * 3, float(sys.argv[5])
im = np.array(Image.open(f"crops/pg{p}_full.png").convert("L")).astype(int)


def runs(col, th):
    out, s = [], None
    for i, v in enumerate(col):
        if v < th and s is None: s = i
        if v >= th and s is not None: out.append((s, i - 1)); s = None
    return out


def five(x, y):
    col = im[y - 110:y + 110, x - 1:x + 2].mean(1)
    r = [(a + b) / 2 + y - 110 for a, b in runs(col, 165) if b - a <= 6]
    best = None
    for i in range(len(r) - 4):
        g = np.diff(r[i:i + 5])
        if g.min() > 12 and g.max() - g.min() < 4:
            c = (abs(np.mean(r[i:i + 5]) - y), r[i:i + 5])
            if best is None or c[0] < best[0]: best = c
    return best[1] if best else None


def lines_at(x, y):
    # symmetric pairs so that staff slope/curvature cancels by linear interpolation
    for off in (18, 25, 32, 40, 50, 60, 75):
        a, b = five(x - off, y), five(x + off, y)
        if a and b and abs(a[-1] - b[-1]) < 20:
            return (0, [(u + v) / 2 for u, v in zip(a, b)], off)
    for off in (18, 25, 32, 40):
        for o in (-off, off):
            a = five(x + o, y)
            if a: return (0, a, o)
    return None


for arg in sys.argv[6:]:
    dx, dy = (float(v) for v in arg.split(","))
    x, y = int(ox + dx * fac), int(oy + dy * fac)
    L = lines_at(x, y)
    col = im[y - 30:y + 30, x - 3:x + 4].mean(1)
    heads = [((a + b) / 2 + y - 30, b - a) for a, b in runs(col, 120) if b - a >= 9]
    if not L or not heads:
        print(arg, (x, y), "FAIL", L, heads); continue
    hc = min(heads, key=lambda h: abs(h[0] - y))[0]
    ls = L[1]; sp = (ls[-1] - ls[0]) / 4
    step = round((ls[-1] - hc) / (sp / 2))
    d = BOTTOM[clef] + step
    print(arg, (x, y), f"{LET[d % 7]}{d // 7}", f"step={step} sp={sp:.1f} head={hc:.0f} bottom={ls[-1]:.0f} off={L[2]}")
