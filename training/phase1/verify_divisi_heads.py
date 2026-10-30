"""Check merged divisi labels against vector PDFs by notehead count per staff (PIYA-106 A7 data).

Why: the score-to-PDF merge (`merge_divisi_parts.py`) and the hand system map can both be wrong in ways the converter
cannot see (a part on the wrong staff, a bar in the wrong system, a printed edition that differs from the score). The
vector PDFs carry every notehead as a font glyph, so the head count of each PDF staff band must equal the label's
`note`/`gracenote`/`chordnote` count. A strip that does not match is marked and must not be trained on. Raster PDFs
cannot be checked this way and are marked `unverified`; they need the user's visual spot check.

Equal counts do not prove equal pitches or rhythm; they catch missing/extra bars, wrong staves and lost chord heads.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz  # pymupdf

sys.path.insert(0, str(Path(__file__).parent))  # python -I does not add the script dir
import accid_check  # noqa: E402

# Notehead glyphs by font. Maestro/Helsinki use MacRoman positions (0xCF black = U+0153, 0xFA half = U+02D9,
# 0xBB whole = U+03D6), read from a glyph contact sheet of For Good.
# TTkStava heads (with stems) read from a glyph contact sheet and band listing of Moonriver.
HEAD_GLYPHS: dict[str, frozenset[str]] = {
    "Leland": frozenset(""),
    "Maestro": frozenset("œ˙ϖ"),
    "HelsinkiStd": frozenset("œ˙w"),  # U+03D6 is not a head in Helsinki (Handog counts broke)
    "TTkStava": frozenset("')*0"),  # + and , are flags drawn over a ) head, . is a natural
}
STAFF_LINE_MIN_WIDTH = 250     # pt of horizontal ink per y, summed over segments (some engravers draw a staff line per
                               # bar); ledger lines, beams and hairpins stay below it
STAFF_SEGMENT_MIN = 30         # pt; ledger lines (~10 pt) must not add up into a staff line
STAFF_LINE_GAP_MAX = 7         # pt between lines of one staff (spaces here are 4-4.5 pt; extenders sit ~11 pt below)
SYSTEM_LINE_X_TOL = 3          # pt from the staff left edge for the system barline
END_BAND = 30                  # pt above the top / below the bottom staff of a system for ledger notes


def staves_and_systems(page: fitz.Page) -> tuple[list[list[float]], list[list[int]]]:
    """Five-line staves (line y's) and their grouping into systems by the left system barline."""
    segs: list[tuple[float, float, float]] = []   # (y, left x, length)
    vs: list[tuple[float, float, float]] = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 0.5 and abs(a.x - b.x) > STAFF_SEGMENT_MIN:
                    segs.append((a.y, min(a.x, b.x), abs(a.x - b.x)))
                elif abs(a.x - b.x) < 0.5 and abs(a.y - b.y) > 5:
                    vs.append((a.x, min(a.y, b.y), max(a.y, b.y)))
            elif it[0] == "re":
                r = it[1]
                if r.height < 1.2 and r.width > STAFF_SEGMENT_MIN:
                    segs.append((r.y0 + r.height / 2, r.x0, r.width))
                elif r.width < 2.5 and r.height > 5:
                    vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
    hs: dict[float, list[float]] = {}   # line y -> [total length, left x]; segments within 0.6 pt are one line
    last = -1e9
    for y, x0, length in sorted(segs):
        if y - last > 0.6:
            hs[y] = [0.0, x0]
            key = y
        hs[key][0] += length
        hs[key][1] = min(hs[key][1], x0)
        last = y
    hs = {y: v for y, v in hs.items() if v[0] > STAFF_LINE_MIN_WIDTH}
    if not hs:
        return [], []
    staves: list[list[float]] = []
    cur: list[float] = []
    for y in sorted(hs):
        if cur and y - cur[-1] > STAFF_LINE_GAP_MAX:
            staves.append(cur)
            cur = []
        if not cur or y - cur[-1] > 0.6:
            cur.append(y)
    staves.append(cur)
    staves = [s for s in staves if len(s) == 5]
    left = min(v[1] for v in hs.values())
    systems: list[list[int]] = []
    used: set[int] = set()
    for v in sorted((v for v in vs if abs(v[0] - left) < SYSTEM_LINE_X_TOL), key=lambda v: v[1]):
        members = [i for i, s in enumerate(staves) if s[0] >= v[1] - 2 and s[4] <= v[2] + 2 and i not in used]
        if members:
            systems.append(members)
            used |= set(members)
    systems += [[i] for i in range(len(staves)) if i not in used]
    systems.sort(key=lambda m: staves[m[0]][0])
    return staves, systems


def head_ys(page: fitz.Page) -> list[float] | None:
    """Baseline y of every notehead glyph (the head sits on it; the bbox is the whole font em box), or None when the
    page has no known music font (raster or unknown)."""
    ys: list[float] = []
    known = False
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                glyphs = HEAD_GLYPHS.get(span["font"])
                if glyphs is None:
                    continue
                known = True
                ys += [c["origin"][1] for c in span["chars"] if c["c"] in glyphs]
    return ys if known else None


def band_counts(staves: list[list[float]], members: list[int], ys: list[float]) -> list[int]:
    """Heads per staff of one system; each staff owns the space halfway to its neighbours."""
    centres = [(staves[i][0] + staves[i][4]) / 2 for i in members]
    edges = [staves[members[0]][0] - END_BAND]
    edges += [(staves[a][4] + staves[b][0]) / 2 for a, b in zip(members, members[1:])]
    edges.append(staves[members[-1]][4] + END_BAND)
    assert len(edges) == len(centres) + 1
    return [sum(lo <= y < hi for y in ys) for lo, hi in zip(edges, edges[1:])]


def _check_accidentals(r: dict, staves: list[list[float]], members: list[int], pts: list[tuple[float, float]],
                       vs: list[tuple[float, float, float]]) -> None:
    """Fill the accid_* fields of one strip: PDF vs label accidental count (header included on both sides), per bar
    when the PDF barlines give the same bar count as the label, else the strip total only."""
    lo_hi = _band_edges(staves, members)[r["staff"]]
    xs = [x for x, y in pts if lo_hi[0] <= y < lo_hi[1]]
    label_bars = accid_check.label_bar_counts(r["tokens"])
    r["pdf_accidentals"], r["label_accidentals"] = len(xs), sum(label_bars)
    r["accid_check"] = "match" if len(xs) == sum(label_bars) else "mismatch"
    bl = accid_check.consensus_barlines([accid_check.staff_barlines(vs, staves[i]) for i in members])
    r["accid_bars_mismatch"] = None
    if len(bl) >= 2:
        bad = accid_check.compare_bars(label_bars, accid_check.pdf_bar_counts(xs, bl, bl[0], bl[-1]))
        if bad is not None:
            first = int(r["bars"][0]) if str(r["bars"][0]).lstrip("-").isdigit() else 1
            r["accid_bars_mismatch"] = [first + i for i in bad]
            if bad and r["accid_check"] == "match":
                r["accid_check"] = "mismatch"   # totals agree but a bar differs: a glyph moved between bars


def _band_edges(staves: list[list[float]], members: list[int]) -> list[tuple[float, float]]:
    """(top, bottom) y of the band each staff owns, as in band_counts."""
    edges = [staves[members[0]][0] - END_BAND]
    edges += [(staves[a][4] + staves[b][0]) / 2 for a, b in zip(members, members[1:])]
    edges.append(staves[members[-1]][4] + END_BAND)
    return list(zip(edges, edges[1:]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, required=True, help="labels.jsonl from merge_divisi_parts.py")
    parser.add_argument("--pdf-root", type=Path, required=True, help="data/chords_dataset (one PDF per piece folder)")
    parser.add_argument("--maps", type=Path, default=Path(__file__).with_name("divisi_score_maps.json"))
    parser.add_argument("--accid", action="store_true", help="also count accidental glyphs per strip and bar")
    parser.add_argument("--out", type=Path, default=None, help="output file (default: labels_checked.jsonl next to labels)")
    args = parser.parse_args()
    records = [json.loads(line) for line in args.labels.read_text(encoding="utf-8").splitlines()]
    maps = json.loads(args.maps.read_text(encoding="utf-8"))
    by_page: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in records:
        by_page[(r["piece"], r["page"])].append(r)
    docs: dict[str, fitz.Document] = {}
    for (piece, page_no), recs in by_page.items():
        if piece not in docs:
            docs[piece] = fitz.open(next((args.pdf_root / piece).glob("*.pdf")))
        page = docs[piece][page_no - 1]
        ys = head_ys(page)
        staves, systems = staves_and_systems(page)
        n_map = sum(len(entries) for p, entries in maps[piece]["pages"] if p == page_no)
        # Every system of the page is labelled and the staff total agrees: assign staves top-down by strip count
        # (the system-barline grouping misses systems in several engravings).
        per_sys = Counter(r["sys"] for r in recs)
        extra = maps[piece].get("extra_staves_below", 0)   # unlabelled (piano) staves under every system
        if extra and n_map * extra + sum(per_sys.values()) == len(staves):
            it = iter(range(len(staves)))
            systems_by_no = {}
            for s in range(1, n_map + 1):
                systems_by_no[s] = [next(it) for _ in range(per_sys.get(s, 0))]
                for _ in range(extra):
                    next(it)
            systems = list(systems_by_no.values())
        elif len(per_sys) == n_map and sum(per_sys.values()) == len(staves):
            it = iter(range(len(staves)))
            systems = [[next(it) for _ in range(per_sys[s])] for s in sorted(per_sys)]
            systems_by_no = dict(zip(sorted(per_sys), systems))
        else:
            systems_by_no = {k + 1: m for k, m in enumerate(systems)}
        acc_pts = accid_check.accidental_points(page) if args.accid else None
        acc_vs = accid_check.vertical_segments(page) if args.accid else []
        page_status = ("unverified: raster or unknown font" if ys is None
                       else f"unverified: {len(systems)} PDF systems vs {n_map} mapped" if len(systems) != n_map
                       else "")
        for r in recs:
            r["pdf_heads"] = None
            if args.accid:
                r.update(pdf_accidentals=None, label_accidentals=None, accid_check="unverified: no accidental glyphs known",
                         accid_bars_mismatch=None)
            if page_status:
                r["check"] = page_status
                if args.accid:
                    r["accid_check"] = page_status
                continue
            members = systems_by_no[r["sys"]]
            n_strips = sum(1 for x in recs if x["sys"] == r["sys"])
            if len(members) != n_strips:
                r["check"] = f"unverified: {len(members)} PDF staves vs {n_strips} strips"
                if args.accid:
                    r["accid_check"] = r["check"]
                continue
            if args.accid and acc_pts is not None and r["tokens"] is not None:
                _check_accidentals(r, staves, members, acc_pts, acc_vs)
            r["pdf_heads"] = band_counts(staves, members, ys)[r["staff"]]
            r["check"] = "match" if r["pdf_heads"] == r["heads"] else "mismatch"
    out = args.out or args.labels.with_name("labels_checked.jsonl")
    out.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    for piece in sorted({r["piece"] for r in records}):
        kept = [r for r in records if r["piece"] == piece and r["tokens"] is not None]
        status = Counter(r["check"].split(":")[0] for r in kept)
        print(f"{piece}: kept {len(kept)} {dict(status)}")


if __name__ == "__main__":
    main()
