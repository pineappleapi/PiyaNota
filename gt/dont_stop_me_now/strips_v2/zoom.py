import sys
from PIL import Image
Image.MAX_IMAGE_PIXELS=None
# usage: zoom.py page ymin_det ymax_det xmin_det xmax_det scale out
p,y0,y1,x0,x1,sc,out=int(sys.argv[1]),*map(float,sys.argv[2:6]),float(sys.argv[6]),sys.argv[7]
S=3024/1200
im=Image.open(f'stage12/preprocessed/page_00{p}_strip_source.png').convert('L').crop((int(x0*S),int(y0*S),int(x1*S),int(y1*S)))
im=im.resize((int(im.width*sc),int(im.height*sc)),Image.LANCZOS); im.save(out); print(im.size)
