"""usage: python view.py page staff x0 x1 [scale] -> crops/v_<page>_<staff>_<x0>.png (rectified strip slice)"""
import sys
from PIL import Image
p, s, x0, x1 = (int(v) for v in sys.argv[1:5]); sc = float(sys.argv[5]) if len(sys.argv) > 5 else 1.5
im = Image.open(f"crops/rect_p{p}_st{s}.png").crop((x0, 0, x1, None if False else Image.open(f"crops/rect_p{p}_st{s}.png").height))
im = im.resize((int(im.width * sc), int(im.height * sc)), Image.LANCZOS)
out = f"crops/v_{p}_{s}_{x0}.png"; im.save(out); print(out, im.size)
