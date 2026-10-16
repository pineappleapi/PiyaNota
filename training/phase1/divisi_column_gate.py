"""Divisi corpus gates from chord vocabulary plan 10.5: column collapse and whole-sequence feasibility.

    python training/phase1/divisi_column_gate.py <divisi build folder>

Column collapse: per drawn chord, the column runs from the leftmost accidental to the rightmost head/dot edge; its
frames at T = W/4 (W = strip width at height 64, times the smallest augment scale 0.9) are compared with the labels
it needs (drawn accidentals + heads + dots; no blanks, since no two of these share a token inside one chord).
shortcut: SVG x maps linearly to strip x via the page width (Stage 2 stretches strips to full page width); augmented
perspective bends this slightly, so this is the clean-render estimate the plan asks for.
"""
import collections, json, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import cv2

B = Path(sys.argv[1])   # divisi build folder: manifest/, out/, renders_svg/renders/
SVG = "{http://www.w3.org/2000/svg}"
TR = re.compile(r"translate\(\s*([-\d.]+)[ ,]+([-\d.]+)")
PAGE_W, MARGIN = 21000.0, 500.0
HEAD_W = 1.18 * 180      # Bravura-style black head width in SVG units (1.18 staff spaces, 180 units each)
ACCID_W = 0.9 * 180
SCALE_MIN, STRIDE, H = 0.9, 4, 64

def cls(e): return e.attrib.get("class", "").split(" ")[0]

def chords_by_staff(svg_path):
    """{(system_on_page, staff_n): [(x0, x1, n_labels, n_heads)]} in SVG units, page-margin applied."""
    root = ET.parse(svg_path).getroot()
    out = collections.defaultdict(list)
    for si, sysg in enumerate(e for e in root.iter(f"{SVG}g") if cls(e) == "system"):
        for st in (e for e in sysg.iter(f"{SVG}g") if cls(e) == "staff"):
            for ch in (e for e in st.iter(f"{SVG}g") if cls(e) == "chord"):
                xs0, xs1, labels, heads = [], [], 0, 0
                for e in ch.iter(f"{SVG}g"):
                    c = cls(e)
                    use = e.find(f"{SVG}use")
                    m = TR.search(use.attrib.get("transform", "")) if use is not None else None
                    if c == "notehead" and m:
                        x = float(m.group(1)); xs0.append(x); xs1.append(x + HEAD_W); labels += 1; heads += 1
                    elif c == "accid" and m:
                        x = float(m.group(1)); xs0.append(x); xs1.append(x + ACCID_W); labels += 1
                    elif c == "dots":
                        for el in e.iter(f"{SVG}ellipse"):
                            cx, rx = float(el.attrib["cx"]), float(el.attrib["rx"])
                            xs0.append(cx - rx); xs1.append(cx + rx); labels += 1
                if heads >= 2:
                    out[(si, st.attrib.get("data-n"))].append((min(xs0) + MARGIN, max(xs1) + MARGIN, labels, heads))
    return out

rows = [json.loads(l) for l in (B / "manifest/phase2_manifest.jsonl").open(encoding="utf-8")]
train = [r for r in rows if r["split"] == "train" and any(t.startswith("chordnote") for t in r["tokens"])]
labels_cache, svg_cache = {}, {}
need_minus_have = collections.Counter(); cols = bad = 0; by_heads = collections.Counter(); bad_heads = collections.Counter()
infeasible = 0; slack = []
for r in train:
    key = (r["font"], r["piece"])
    if key not in labels_cache:
        labels_cache[key] = json.loads((B / "renders_svg/renders" / r["font"] / r["piece"] / "labels.json").read_text(encoding="utf-8"))
    lab = [s for s in labels_cache[key] if s["page"] == r["page"] and s["system"] == r["system"] and s["voice"] == r["voice"]]
    if len(lab) != 1:
        sys.exit(f"label match {len(lab)} for {r['path']}")
    lab = lab[0]
    img = cv2.imread(str(B / "out" / r["path"]), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    W = int(int(w * H / h) * SCALE_MIN)
    toks = r["tokens"]
    need = len(toks) + sum(a == b for a, b in zip(toks, toks[1:]))
    slack.append(W // STRIDE - need)
    if need > W // STRIDE:
        infeasible += 1
    sk = (r["font"], r["piece"], r["page"])
    if sk not in svg_cache:
        svg_cache[sk] = chords_by_staff(B / "renders_svg/renders" / r["font"] / r["piece"] / f"page_{r['page']}.svg")
    px = W / PAGE_W
    for x0, x1, nl, nh in svg_cache[sk].get((lab["system_on_page"], lab["staff_n"]), []):
        frames = int(x1 * px) // STRIDE - int(x0 * px) // STRIDE + 1
        cols += 1; by_heads[nh] += 1
        if nl > frames:
            bad += 1; bad_heads[nh] += 1
        need_minus_have[max(-3, min(3, nl - frames))] += 1
slack.sort()
print(json.dumps({"train_chord_strips": len(train),
                  "feasibility": {"infeasible": infeasible, "rate": round(infeasible / len(train), 4),
                                  "slack_p1_p50": [slack[len(slack) // 100], slack[len(slack) // 2]]},
                  "column_collapse": {"chord_columns": cols, "infeasible": bad, "rate": round(bad / cols, 4) if cols else None,
                                      "by_heads": dict(by_heads), "infeasible_by_heads": dict(bad_heads),
                                      "labels_minus_frames_hist": dict(sorted(need_minus_have.items()))}}, indent=1))
