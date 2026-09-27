"""Diagnostic aid: find notehead blobs in a rectified staff strip and report their staff step.
usage: python heads.py rectfile x0 x1 clef(G|F) [thresh]"""
import sys
import numpy as np
import cv2
f, x0, x1, clef = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
th = int(sys.argv[5]) if len(sys.argv) > 5 else 120
im = cv2.imread(f)
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)[:, x0:x1]
# red guides are colored; mask them out by using min channel? guides are red (255,0,0): gray ~76 -> suppress
red = (im[:, x0:x1, 2] > 200) & (im[:, x0:x1, 1] < 80)
g = g.copy(); g[red] = 255
# local staff lines: rows darkest by median across columns
prof = np.median(g, axis=1)
rows = [y for y in range(2, len(prof) - 2) if prof[y] < 175 and prof[y] <= prof[y-1] and prof[y] <= prof[y+1]]
# merge close rows
lines = []
for y in rows:
    if lines and y - lines[-1][-1] <= 3: lines[-1].append(y)
    else: lines.append([y])
lines = [float(np.mean(l)) for l in lines]
# pick 5 evenly spaced
best = None
for i in range(len(lines) - 4):
    d = np.diff(lines[i:i+5])
    if d.min() > 8 and d.max() - d.min() < 5:
        best = lines[i:i+5]; break
if best is None:
    print("lines?", [round(l) for l in lines]); sys.exit(1)
sp = np.mean(np.diff(best)); bot = best[4]
print("lines", [round(l, 1) for l in best], "sp", round(sp, 1))
m = (g < th).astype(np.uint8)
# fill small enclosed holes so hollow (half/whole) heads survive the opening
nb, lb, sb, _ = cv2.connectedComponentsWithStats(1 - m, connectivity=4)
for j in range(1, nb):
    if sb[j][4] < sp * sp * 0.6 and sb[j][2] < sp * 1.6 and sb[j][3] < sp * 1.1:
        m[lb == j] = 1
k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(sp * 0.7) | 1, int(sp * 0.55) | 1))
o = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
n, lab, st, cen = cv2.connectedComponentsWithStats(o)
names_G = "C D E F G A B".split()
for i in sorted(range(1, n), key=lambda i: cen[i][0]):
    x, y = cen[i]; a = st[i][4]
    if a < sp * sp * 0.3 or st[i][2] > 2.5 * sp: continue
    step = (bot - y) / (sp / 2)  # 0 = bottom line
    s = int(round(step))
    base = (2, 4) if clef == "G" else (4, 2)  # (letter index, octave) of bottom line: E4 / G2
    idx = base[0] + s; octv = base[1] + idx // 7; nm = names_G[idx % 7]
    print(f"x={x0 + x:6.0f} y={y:6.1f} step={step:5.2f} -> {nm}{octv}  area={a} w={st[i][2]} h={st[i][3]}")
