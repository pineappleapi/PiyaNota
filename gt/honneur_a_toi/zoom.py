"""Crop helper for hand annotation. Coords are in the /3 overview (crops/pg<p>_small.jpg) pixels.
usage: python zoom.py page x0 y0 x1 y1 scale out"""
import sys
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
p = int(sys.argv[1]); x0, y0, x1, y1 = (float(v) * 3 for v in sys.argv[2:6]); sc = float(sys.argv[6]); out = sys.argv[7]
im = Image.open(f"crops/pg{p}_full.png").convert("L").crop((int(x0), int(y0), int(x1), int(y1)))
im = im.resize((int(im.width * sc), int(im.height * sc)), Image.LANCZOS); im.save(out); print(im.size)
