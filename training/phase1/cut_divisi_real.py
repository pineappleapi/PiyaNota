"""Real-engraving divisi training strips: PDF renders and camera photos of `data/chords_dataset` (PIYA-106 A7-data).

Why the deployment path: ml-cv-lead (2026-10-30) ruled that digital training strips must go through Stage 1 (grey
`strip_source`, `paper_fill`) and Stage 2's own box rules and crop, like camera pages and the eval_prelim digital path;
a custom crop would train on strips deployment never produces. The vector staff finder only aligns labels.

Two steps, because PyMuPDF and the pipeline (torch, ultralytics) live in different environments:
    <pymupdf python> -I training/phase1/cut_divisi_real.py render --pdf-root data/chords_dataset --out OUT
    <pipeline python> -I training/phase1/cut_divisi_real.py cut --labels labels_checked.jsonl --forms forms.json \
        --pdf-root data/chords_dataset --out OUT --holdout <Piece>

Label to staff alignment: a page's Stage 2 boxes, top to bottom, are its labelled PDF staves in (system, staff)
order. A page with a system the map does not label, or whose box count differs from its labelled staff count, is
skipped and logged; nothing is guessed.

Train eligibility (`train_ok`, else `exclude` says why), per strip:
- the head check (`verify_divisi_heads.py`) is `match`, or `unverified: raster` (raster pieces were checked
  visually by the choral-conductor); a vector-page mismatch or unverified alignment excludes it;
- every `chord_merge` bar is confirmed `chord` and every `layered_partial_rest` bar `rests_ok` in the PDF form check
  (`--forms`); unchecked bars exclude the strip (ml-cv-lead changes 3-4);
- `layered` strips (with `layer.split`) are for arm CL only; the training loader keeps them out of arm C (ruling F).
The split is by piece (ruling D): the `--holdout` piece is report-only and never used for selection.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAPS = Path(__file__).with_name("divisi_score_maps.json")
DIGITAL_DPI = 300              # = data/eval_prelim/inputs.py DIGITAL_DPI (the digital eval path)
CNN_WIDTH_STRIDE = 4           # = stage3_transcription.CNN_WIDTH_STRIDE: one CTC frame per 4 px of strip width
FRAME_BUDGET = 0.8             # A7 design 5.3: (tokens + repeats) / frames
YOLO_WEIGHTS = "D:/PiyaNota/staff_detector_files/weights/best.pt"
CAMERA_NAME = re.compile(r"^p(\d+)(?:_([a-z]))?$", re.IGNORECASE)
# Pieces whose photos are not named pNN: sorted file order = page order (user to confirm; IMG_5098 is absent).
CAMERA_PAGE_ORDER: dict[str, list[str]] = {
    "Vinea_mea_electa": ["IMG_5095", "IMG_5096", "IMG_5097", "IMG_5099"],
}
RASTER_OK = "unverified: raster or unknown font"


def render(pdf_root: Path, out: Path, pieces: list[str]) -> None:
    import fitz  # noqa: PLC0415 - only the render step needs PyMuPDF
    for piece in pieces:
        doc = fitz.open(next((pdf_root / piece).glob("*.pdf")))
        target = out / "pages" / piece
        target.mkdir(parents=True, exist_ok=True)
        for i, page in enumerate(doc, start=1):
            page.get_pixmap(dpi=DIGITAL_DPI, colorspace=fitz.csGRAY).save(target / f"pdf_p{i:02d}.png")
        print(f"{piece}: {len(doc)} pages rendered")


def camera_pages(piece_dir: Path) -> dict[int, Path]:
    """Page number -> photo. Multi-shot pages (p03_a, p03_b) are skipped: which systems each shot holds is unknown."""
    photos = sorted(p for p in (piece_dir / "camera").glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    order = CAMERA_PAGE_ORDER.get(piece_dir.name)
    if order is not None:
        by_stem = {p.stem: p for p in photos}
        return {i: by_stem[s] for i, s in enumerate(order, start=1) if s in by_stem}
    pages: dict[int, Path] = {}
    for p in photos:
        m = CAMERA_NAME.match(p.stem)
        if m and m.group(2) is None:
            pages[int(m.group(1))] = p
        else:
            print(f"  {piece_dir.name}: skip {p.name} (not pNN, or a multi-shot page)")
    return pages


def page_complete(spec: dict, page: int) -> bool:
    """Every system on the page is labelled (no null system, none left out before the first listed one)."""
    entries = [e for p, es in spec["pages"] if p == page for e in es]
    if not entries:
        return False
    sys_nos = [e.get("sys", k + 1) if isinstance(e, dict) else k + 1 for k, e in enumerate(entries)]
    return sys_nos == list(range(1, len(entries) + 1)) and all(
        not isinstance(e, dict) or e.get("staves", "") is not None for e in entries)


def page_slots(spec: dict, page: int, recs: list[dict]) -> list[dict | None]:
    """The page's printed staves top to bottom: its label record, or None for an unlabelled staff (the map's
    `extra_staves_below`, e.g. a piano part under every system)."""
    n_sys = sum(len(es) for p, es in spec["pages"] if p == page)
    extra = spec.get("extra_staves_below", 0)
    slots: list[dict | None] = []
    for k in range(1, n_sys + 1):
        slots += sorted((r for r in recs if r["sys"] == k), key=lambda r: r["staff"]) + [None] * extra
    return slots


def frame_ratio(tokens: list[str], width_px: int) -> float:
    repeats = sum(a == b for a, b in zip(tokens, tokens[1:]))   # CTC needs a blank frame between equal tokens
    return (len(tokens) + repeats) / max(1, width_px // CNN_WIDTH_STRIDE)


def eligibility(r: dict, forms: dict) -> list[str]:
    reasons: list[str] = []
    check = r.get("check", "")
    if check != "match" and check != RASTER_OK:
        reasons.append(f"head check: {check or 'missing'}")
    form = forms.get(r["piece"], {}).get("-".join(r["parts"]), {})
    for bar, flags in r.get("bar_flags", {}).items():
        if "chord_merge" in flags and bar not in form.get("chord", []):
            reasons.append(f"bar {bar}: chord form not confirmed in the PDF")
        if "layered_partial_rest" in flags and bar not in form.get("rests_ok", []):
            reasons.append(f"bar {bar}: layer-2 rest not confirmed in the PDF")
    return reasons


def cut(args: argparse.Namespace) -> None:
    import cv2  # noqa: PLC0415 - pipeline environment only
    sys.path.insert(0, str(REPO))
    import stage1_preprocessing as s1  # noqa: PLC0415
    import stage2_detection as s2  # noqa: PLC0415
    from ultralytics import YOLO  # noqa: PLC0415

    maps = {k: v for k, v in json.loads(MAPS.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    assert args.holdout in maps, f"--holdout {args.holdout!r} is not a mapped piece"
    records = [json.loads(line) for line in args.labels.read_text(encoding="utf-8").splitlines()]
    forms = json.loads(args.forms.read_text(encoding="utf-8")) if args.forms else {}
    by_page: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in records:
        by_page[(r["piece"], r["page"])].append(r)
    model = YOLO(args.weights)
    rows: list[dict] = []
    log: list[str] = []
    for piece in sorted({p for p, _ in by_page} & set(args.piece or maps)):
        sources = {"pdf": {n: args.out / "pages" / piece / f"pdf_p{n:02d}.png" for _, n in by_page if _ == piece}}
        sources["camera"] = camera_pages(args.pdf_root / piece)
        for source, pages in sources.items():
            for page_no, image in sorted(pages.items()):
                recs = sorted(by_page.get((piece, page_no), []), key=lambda r: (r["sys"], r["staff"]))
                if not recs:
                    continue
                if not image.exists():
                    log.append(f"{piece} {source} p{page_no}: missing {image} (run the render step)")
                    continue
                if not page_complete(maps[piece], page_no):
                    log.append(f"{piece} {source} p{page_no}: skipped, a system on the page is not labelled")
                    continue
                pre = s1.preprocess_score_page(str(image))
                page_bgr = cv2.cvtColor(pre.detect, cv2.COLOR_GRAY2BGR) if pre.detect.ndim == 2 else pre.detect
                boxes = s2.page_boxes(page_bgr, model, page_no)
                slots = page_slots(maps[piece], page_no, recs)
                if len(boxes) != len(slots):
                    log.append(f"{piece} {source} p{page_no}: skipped, {len(boxes)} boxes vs {len(slots)} printed staves")
                    continue
                for b in boxes:   # Stage 2 Rule 4: stafflines span the page
                    b["x1"], b["x2"] = 0, page_bgr.shape[1]
                target = args.out / "strips" / piece
                target.mkdir(parents=True, exist_ok=True)
                for i, (box, r) in enumerate(zip(boxes, slots)):
                    if r is None or r["tokens"] is None:
                        continue
                    strip = s2._crop_and_resize(page_bgr, box, s2.STRIP_HEIGHT, limits=s2._neighbor_limits(
                        boxes, i, page_bgr.shape[0]), source=pre.strip_source)
                    name = f"{source}_p{page_no:02d}_s{r['sys']:02d}_st{r['staff']}.png"
                    cv2.imwrite(str(target / name), strip)
                    reasons = eligibility(r, forms)
                    ratio = frame_ratio(r["tokens"], strip.shape[1])
                    if ratio > FRAME_BUDGET:
                        reasons.append(f"frame budget {ratio:.2f} > {FRAME_BUDGET}")
                    rows.append({
                        "file": f"strips/{piece}/{name}", "piece": piece, "page": page_no, "sys": r["sys"],
                        "staff": r["staff"], "parts": r["parts"], "source": source, "photo": image.name,
                        "split": "holdout" if piece == args.holdout else "train", "tokens": r["tokens"],
                        "layered": "layer.split" in r["tokens"], "flags": r["flags"], "check": r.get("check"),
                        "frame_ratio": round(ratio, 3), "strip_source": "native" if pre.strip_source is not None
                        else "fallback", "train_ok": not reasons, "exclude": reasons,
                    })
    split_of = defaultdict(set)
    for row in rows:
        split_of[row["piece"]].add(row["split"])
    assert all(len(s) == 1 for s in split_of.values()), "a piece on both sides of the split"
    (args.out / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (args.out / "cut_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    for piece in sorted(split_of):
        mine = [r for r in rows if r["piece"] == piece]
        c = Counter((r["source"], r["train_ok"], r["layered"]) for r in mine)
        print(f"{piece} [{mine[0]['split']}]: " + ", ".join(
            f"{s}{' ok' if ok else ' excluded'}{' layered' if lay else ''} {n}" for (s, ok, lay), n in sorted(c.items())))


def self_check() -> None:
    assert frame_ratio(["a", "a", "b"], 12) == 4 / 3
    spec = {"pages": [[1, ["1", "5"]], [2, [{"first": "9", "staves": None}, "12"]], [3, [{"first": "20", "sys": 2}]]]}
    assert page_complete(spec, 1) and not page_complete(spec, 2) and not page_complete(spec, 3)
    recs = [{"sys": 2, "staff": 1}, {"sys": 2, "staff": 0}]
    assert page_slots({**spec, "extra_staves_below": 1}, 1, recs) == [None, recs[1], recs[0], None]
    r = {"piece": "P", "parts": ["1", "2"], "check": "match", "bar_flags": {"4": ["chord_merge"]}}
    assert eligibility(r, {}) and not eligibility(r, {"P": {"1-2": {"chord": ["4"]}}})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)
    rp = sub.add_parser("render")
    cp = sub.add_parser("cut")
    for p in (rp, cp):
        p.add_argument("--pdf-root", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--piece", action="append")
    cp.add_argument("--labels", type=Path, required=True, help="labels_checked.jsonl (verify_divisi_heads.py)")
    cp.add_argument("--forms", type=Path, help="PDF form check JSON (see merge_divisi_parts.py --split-bars)")
    cp.add_argument("--holdout", required=True, help="the one report-only piece (ml-cv-lead ruling D)")
    cp.add_argument("--weights", default=YOLO_WEIGHTS)
    args = parser.parse_args()
    self_check()
    if args.step == "render":
        maps = [k for k in json.loads(MAPS.read_text(encoding="utf-8")) if not k.startswith("_")]
        render(args.pdf_root, args.out, args.piece or maps)
    else:
        cut(args)


if __name__ == "__main__":
    main()
