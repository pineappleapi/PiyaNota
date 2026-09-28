"""Hand-annotation aid (not pipeline code): rectify every staff of a page photo by tracking its 5 lines column
by column, then save straightened strips with blue staff-line ticks in the margin and dotted red ledger guides.
Generalised from gt/honneur_a_toi/rect.py (any piece, adaptive darkness threshold, larger staff spacing).
usage: python rect.py piece page out_dir"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageOps
piece, p, out_dir = sys.argv[1], int(sys.argv[2]), sys.argv[3]
os.makedirs(out_dir, exist_ok=True)
im = np.asarray(ImageOps.exif_transpose(Image.open(f"D:/PiyaNota/data/piyanota_dataset/{piece}_pg{p:02d}.jpg"))
                .convert("L"), dtype=float)
H, W = im.shape
BG = float(np.median(im))
DARK = BG - 45  # a staffline pixel is clearly darker than the paper


def runs(col, th):
    out, s = [], None
    for i, v in enumerate(col):
        if v < th and s is None: s = i
        if v >= th and s is not None: out.append((s, i - 1)); s = None
    return out


def staves_at(x):
    col = im[:, x - 2:x + 3].mean(1)
    r = [(a + b) / 2 for a, b in runs(col, DARK) if b - a <= 9]
    st, i = [], 0
    while i <= len(r) - 5:
        g = np.diff(r[i:i + 5])
        if g.min() > 12 and g.max() - g.min() < 0.18 * g.mean() + 3 and g.mean() < 70:
            st.append(r[i:i + 5]); i += 5
        else:
            i += 1
    return st


def track(lines0, x0, step):
    ys = np.array(lines0, float); out = {x0: ys.copy()}
    x = x0
    sp = np.diff(ys).mean()
    while 5 < x + step < W - 5:
        x += step
        col = im[:, x - 1:x + 2].mean(1)
        cand = []
        for y in ys:
            lo, hi = int(y - sp * 0.2), int(y + sp * 0.2) + 1
            seg = col[lo:hi]
            j = int(np.argmin(seg)); v = seg[j]
            w = int(sp * 0.25)
            ok = v < DARK + 10 and (col[max(lo + j - w, 0)] > v + 15 or col[min(lo + j + w, H - 1)] > v + 15)
            cand.append(lo + j - y if ok else np.nan)
        d = np.nanmedian(cand) if not np.all(np.isnan(cand)) else 0.0
        ys = ys + np.clip(d, -2, 2)
        out[x] = ys.copy()
    return out


tracks = []
for sx in (int(W * f) for f in (0.35, 0.5, 0.65, 0.8)):
    for s in staves_at(sx):
        tr = {**track(s, sx, -1), **track(s, sx, 1)}
        ref = W // 2
        if all(abs(t[ref][0] - tr[ref][0]) > 3 * np.diff(s).mean() for t in tracks):
            tracks.append(tr)
tracks.sort(key=lambda t: t[W // 2][0])
print(f"p{p}: {len(tracks)} staves at y", [round(t[W // 2][0]) for t in tracks])
for n, tr in enumerate(tracks):
    xs = sorted(tr)
    sp = np.mean([np.diff(tr[x]).mean() for x in xs])
    above, below = 4.5 * sp, 5 * sp
    hgt = int(above + 4 * sp + below)
    out = np.full((hgt, len(xs)), 255.0)
    for i, x in enumerate(xs):
        y0 = int(round(tr[x][0] - above))
        seg = im[max(y0, 0):min(y0 + hgt, H), x]
        out[max(0, -y0):max(0, -y0) + len(seg), i] = seg
    img = Image.fromarray(out.astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(img)
    for k in range(1, 5):  # ledger-line positions above and below
        for y in (above - k * sp, above + 4 * sp + k * sp):
            for xx in range(0, img.width, 16):
                d.line([(xx, y), (xx + 3, y)], fill=(255, 0, 0))
    for k in range(5):
        y = above + k * sp
        d.line([(0, y), (14, y)], fill=(0, 0, 255), width=3)
    img.save(os.path.join(out_dir, f"{piece}_p{p}_st{n}.png"))
