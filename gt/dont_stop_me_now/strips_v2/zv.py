import sys,json
from PIL import Image
Image.MAX_IMAGE_PIXELS=None
# usage: zv.py page sys Voice x0 x1 scale out   (det coords x; strip box y +-28)
p,s,v,x0,x1,sc,out=int(sys.argv[1]),int(sys.argv[2]),sys.argv[3],float(sys.argv[4]),float(sys.argv[5]),float(sys.argv[6]),sys.argv[7]
S=3024/1200
m=[e for e in json.load(open('stage12/strips/manifest.json')) if e['page']==p and e['system']==s and e['voice']==v][0]['box']
im=Image.open(f'stage12/preprocessed/page_00{p}_strip_source.png').convert('L').crop((int(x0*S),int((m['y1']-28)*S),int(x1*S),int((m['y2']+28)*S)))
im=im.resize((int(im.width*sc),int(im.height*sc)),Image.LANCZOS); im.save(out); print(im.size)
