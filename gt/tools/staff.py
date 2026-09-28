"""Viewing aid for hand annotation only (not pipeline code). One staff band of a page overview (1500x2000 coords)
at `scale`, split into two halves stacked vertically, with staff-line (red) / space (green) overlay.
usage: python staff.py piece page x0 x1 y0 y1 scale out_png [--split X]"""
import subprocess, sys
from PIL import Image
piece, p = sys.argv[1], sys.argv[2]
x0, x1, y0, y1 = (float(v) for v in sys.argv[3:7]); sc = sys.argv[7]; out = sys.argv[8]
xm = float(sys.argv[sys.argv.index("--split") + 1]) if "--split" in sys.argv else (x0 + x1) / 2
parts = []
for i, (a, b) in enumerate([(x0, xm + 15), (xm - 15, x1)]):
    tmp = out.replace(".png", f"_h{i}.png")
    subprocess.run([sys.executable, __file__.replace("staff.py", "view.py"), piece, p, str(a), str(y0), str(b), str(y1), sc, tmp, "--overlay"], check=True, capture_output=True)
    parts.append(Image.open(tmp))
w = max(im.width for im in parts); h = sum(im.height for im in parts) + 6
c = Image.new("RGB", (w, h), (255, 255, 255)); y = 0
for im in parts:
    c.paste(im, (0, y)); y += im.height + 6
c.save(out); print(c.size)
