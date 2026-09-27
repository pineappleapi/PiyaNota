"""usage: python stack.py page first_staff n x0 x1 out [scale]  -- stack rectified staves vertically"""
import sys
from PIL import Image
p, f, n, x0, x1 = (int(v) for v in sys.argv[1:6]); out = sys.argv[6]; sc = float(sys.argv[7]) if len(sys.argv) > 7 else 1.0
ims = []
for s in range(f, f + n):
    im = Image.open(f"crops/rect{__import__("os").environ.get("RTAG","")}_p{p}_st{s}.png"); ims.append(im.crop((x0, 0, x1, im.height)))
c = Image.new("RGB", (x1 - x0, sum(i.height for i in ims)), "white"); y = 0
for i in ims: c.paste(i, (0, y)); y += i.height
c = c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS); c.save(out); print(out, c.size)
