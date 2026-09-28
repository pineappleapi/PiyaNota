"""Hand-annotation aid: stack rectified staves (from rect.py) of one system, cut into `parts` horizontal pieces,
each piece's staves stacked in order, downscaled by `scale`.
usage: python show.py rect_dir piece page first_staff n_staves parts scale out_prefix [x0frac x1frac]"""
import sys
from PIL import Image
d, piece, p, f, n, parts, sc, pre = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]), float(sys.argv[7]), sys.argv[8]
fx0, fx1 = (float(sys.argv[9]), float(sys.argv[10])) if len(sys.argv) > 10 else (0.0, 1.0)
ims = [Image.open(f"{d}/{piece}_p{p}_st{s}.png") for s in range(f, f + n)]
W = ims[0].width; a0, a1 = int(W * fx0), int(W * fx1); step = (a1 - a0) / parts
for k in range(parts):
    x0, x1 = int(a0 + k * step) - 30, int(a0 + (k + 1) * step) + 30
    cs = [im.crop((max(x0, 0), 0, min(x1, im.width), im.height)) for im in ims]
    c = Image.new("RGB", (max(i.width for i in cs), sum(i.height for i in cs)), "white"); y = 0
    for i in cs: c.paste(i, (0, y)); y += i.height
    c = c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS); c.save(f"{pre}_{k}.png"); print(f"{pre}_{k}.png", c.size)
off = 0
for s, im in zip(range(f, f + n), ims):  # rect.py layout: 4.5 spacings above the top line, 13.5 spacings in all
    sp = im.height / 13.5
    print(f"staff {s}: lines at y", [round((off + (4.5 + k) * sp) * sc) for k in range(5)], "spacing", round(sp * sc, 1))
    off += im.height
