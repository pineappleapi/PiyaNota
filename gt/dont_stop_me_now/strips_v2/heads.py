import sys,json,numpy as np,cv2
cv2.setNumThreads(1)
# usage: heads.py page sys Voice [x0 x1]  -> prints filled-head blobs with staff step (0=bottom line, 1=first space...)
p,s,v=int(sys.argv[1]),int(sys.argv[2]),sys.argv[3]
S=3024/1200
m=[e for e in json.load(open('stage12/strips/manifest.json')) if e['page']==p and e['system']==s and e['voice']==v][0]['box']
img=cv2.imread(f'stage12/preprocessed/page_00{p}_strip_source.png',0)
Y0=int((m['y1']-40)*S);Y1=int((m['y2']+40)*S)
c=img[Y0:Y1,:]
b=(c<128).astype(np.uint8)
# staff lines: rows where long horizontal run present (use middle x band)
x0=int(float(sys.argv[4])*S) if len(sys.argv)>4 else 0
x1=int(float(sys.argv[5])*S) if len(sys.argv)>5 else b.shape[1]
proj=b[:,300:2700].sum(1).astype(float)
rows=np.where(proj>0.6*proj.max())[0]
# cluster
cl=[];cur=[rows[0]]
for r in rows[1:]:
    if r-cur[-1]<=3: cur.append(r)
    else: cl.append(np.mean(cur));cur=[r]
cl.append(np.mean(cur))
print('lines(y native):',[round(x) for x in cl])
if len(cl)>5:
    import itertools
    best=min(itertools.combinations(cl,5),key=lambda c:np.var(np.diff(c)))
    cl=list(best); print('picked 5 of >5:',[round(x) for x in cl])
if len(cl)!=5: print('WARN line count',len(cl))
cl=sorted(cl); yb=cl[-1]; d=(cl[-1]-cl[0])/4
k=int(d*0.75)|1
ker=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(k,k))
o=cv2.morphologyEx(b,cv2.MORPH_OPEN,ker)
n,lab,st,cen=cv2.connectedComponentsWithStats(o)
out=[]
for i in range(1,n):
    x,y,w,h,a=st[i]
    if a<0.4*d*d or w>2.2*d or h>2.0*d: continue
    cx,cy=cen[i]
    if not(x0<=cx<=x1): continue
    step=(yb-cy)/(d/2)
    out.append((cx/S,step,w/d,h/d))
print(' '.join(f'{cx:.0f}:{step:.1f}' for cx,step,w,h in sorted(out) if w>=1.0 and cx>140))
