"""Hand-annotation aid: rectify each staff of a page photo by tracking its 5 lines column by column,
then save straightened strips with dotted ledger-position guides.  Diagnostic viewing only.
usage: python rect.py page seed_x"""
import sys
import numpy as np
from PIL import Image, ImageDraw
p = int(sys.argv[1]); seeds = [int(v) for v in sys.argv[2:]]
im = np.array(Image.open(f"crops/pg{p}_full.png").convert("L")).astype(float)
H, W = im.shape


def runs(col, th):
    out, s = [], None
    for i, v in enumerate(col):
        if v < th and s is None: s = i
        if v >= th and s is not None: out.append((s, i - 1)); s = None
    return out


def staves_at(x):
    col = im[:, x - 1:x + 2].mean(1)
    r = [(a + b) / 2 for a, b in runs(col, 165) if b - a <= 6]
    st, i = [], 0
    while i <= len(r) - 5:
        g = np.diff(r[i:i + 5])
        if g.min() > 10 and g.max() - g.min() < 4 and g.mean() < 35:
            st.append(r[i:i + 5]); i += 5
        else:
            i += 1
    return st


def track(lines0, x0, step):
    ys = np.array(lines0, float); out = {x0: ys.copy()}
    x = x0
    while 5 < x + step < W - 5:
        x += step
        col = im[:, x - 1:x + 2].mean(1)
        cand = []
        for k, y in enumerate(ys):
            lo, hi = int(y - 4), int(y + 5)
            seg = col[lo:hi]
            j = int(np.argmin(seg)); v = seg[j]
            # only accept thin dark minima (a staff line), else keep predicted position
            ok = v < 170 and (col[max(lo + j - 6, 0)] > v + 15 or col[min(lo + j + 6, H - 1)] > v + 15)
            cand.append(lo + j - y if ok else np.nan)
        d = np.nanmedian(cand) if not np.all(np.isnan(cand)) else 0.0
        ys = ys + np.clip(d, -2, 2)
        out[x] = ys.copy()
    return out


tracks = []
for sx in seeds:
    for s in staves_at(sx):
        tr = {**track(s, sx, -1), **track(s, sx, 1)}
        ref = min(tr, key=lambda x: abs(x - W // 2))
        if all(abs(t[ref][0] - tr[ref][0]) > 40 for t in tracks):
            tracks.append(tr)
tracks.sort(key=lambda t: t[min(t, key=lambda x: abs(x - W // 2))][0])
print("staves:", [round(t[min(t, key=lambda x: abs(x - W // 2))][0]) for t in tracks])
for n, tr in enumerate(tracks):
    xs = sorted(tr)
    sp = np.mean([np.diff(tr[x]).mean() for x in xs])
    above, below = 5 * sp, 6 * sp
    hgt = int(above + 4 * sp + below)
    out = np.full((hgt, len(xs)), 255.0)
    for i, x in enumerate(xs):
        top = tr[x][0]
        y0 = int(round(top - above))
        seg = im[max(y0, 0):min(y0 + hgt, H), x]
        out[max(0, -y0):max(0, -y0) + len(seg), i] = seg
    img = Image.fromarray(out.astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(img)
    for k in range(1, 6):  # ledger-line positions above and below
        for y in (above - k * sp, above + 4 * sp + k * sp):
            for xx in range(0, img.width, 14):
                d.line([(xx, y), (xx + 3, y)], fill=(255, 0, 0))
    for k in range(5):  # mark staff-line positions in margin
        y = above + k * sp
        d.line([(0, y), (12, y)], fill=(0, 0, 255), width=2)
    img = img.resize((img.width, img.height), Image.LANCZOS)
    img.save(f"crops/rect{__import__("os").environ.get("RTAG","")}_p{p}_st{n}.png"); print(n, img.size, round(sp, 1))
