"""Viewing aid for hand annotation only (not pipeline code). Coords are in the 1500x2000 page overview.
usage: python crop.py page x0 y0 x1 y1 scale out_name"""
import sys
from PIL import Image, ImageOps
p = int(sys.argv[1]); x0, y0, x1, y1 = (float(v) for v in sys.argv[2:6]); sc = float(sys.argv[6])
im = ImageOps.exif_transpose(Image.open(f"D:/PiyaNota/data/piyanota_dataset/non_nobis_domine_pg0{p}.jpg")).convert("L")
f = im.width / 1500
c = im.crop((int(x0 * f), int(y0 * f), int(x1 * f), int(y1 * f)))
c = c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS)
c.save(f"D:/PiyaNota-training/gt/non_nobis_domine/crops/{sys.argv[7]}.png"); print(c.size)
