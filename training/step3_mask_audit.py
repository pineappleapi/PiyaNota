"""PIYA-121 / BUG-015 audit: what the Stage 1 non-staff-ink mask and the native-resolution strip
source do to ties, beams, staff-band ink and thin glyphs. Runs NO Stage 3/CRNN.

Why this exists: BUG-015's first numbers came from an eyeballed montage and a "bridging" flag
that only detected a removed run touching kept ink at both ends. This replaces it with checks
that are measured on the ink itself. Every check is independent of the mask's own rules (it
does not reuse ``non_staff_ink_mask``), so it can disagree with the mask.

Modes (one per invocation; ``old`` needs the pre-PIYA-121 modules, see --old-src):
    new     current code. Per page: tie/slur survival, beam removal, staff-band ink removal,
            thin-glyph fidelity, and the final 64 px strips (classical-tracker boxes, no YOLO).
    old     pre-PIYA-121 pipeline (1600 px page + Stage 2 strip mask) on the same pages, for the
            before/after tie survival and thin-glyph fidelity.
    report  merges the JSON of both modes by split (tuning / frozen / seen) and prints tables.

What the tie check does: on the UNMASKED native page it removes staff lines (thin horizontal
runs), stems/barlines (long vertical runs) and filled noteheads (opening by a 0.62-spacing disk),
then keeps curved thin arcs whose BOTH ends lie within 0.35 spacing of a filled notehead. Level
ends (<= 0.7 spacing apart) = tie candidate, otherwise slur candidate (optional, reported apart).
A candidate "survives" if >= SURVIVE_MIN of its pixels are still ink on the masked page.

What it does NOT verify:
  * Hollow noteheads (half/whole) are not detected, so ties between them are not counted.
  * Ties fused with a staff line, ties touching a beam/flag, and one-ended ties (l.v., across a
    system break) are not counted. Recall is over DETECTOR-FOUND ties only, not over all ties.
  * Survival is ink presence, not legibility: it does not show the CRNN can read the tie.
  * A candidate the detector wrongly calls a tie (a curved clef part, accent...) counts too.

Usage (repo root, PYTHONPATH=.):
    python training/step3_mask_audit.py --mode new --out data/audit
    python training/step3_mask_audit.py --mode old --old-src data/scratch_mask/old --out data/audit
    python training/step3_mask_audit.py --mode report --out data/audit
Page sets: the piyanota_dataset photos (split in training/step3_mask_split.json), BSN raw
(D:/PiyaNota/data/raw/Raw IMG_1081-1084,1086-1088) and DSMN (data/step3_testset/raw).
"""

import argparse
import csv
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
DATASET = Path("D:/PiyaNota/data/piyanota_dataset")
BSN_RAW = Path("D:/PiyaNota/data/raw/Raw")
BSN_FILES = [f"IMG_{n}.JPG" for n in (1081, 1082, 1083, 1084, 1086, 1087, 1088)]
DSMN_RAW = REPO / "data" / "step3_testset" / "raw"
SPLIT_FILE = REPO / "training" / "step3_mask_split.json"

LINE_RUN_SPACINGS = 6.0        # horizontal runs this long are staff lines, not ties
LINE_FRINGE_PX = 2             # rows either side of a line core that still count as the line
VERT_THICK_SPACINGS = 0.45     # ink columns thicker than this are not a thin line/arc
STEM_RUN_SPACINGS = 1.6        # vertical runs this long are stems/barlines
HEAD_DIAM_SPACINGS = 0.62      # opening disk that keeps filled noteheads and drops beams/lines
HEAD_GAP_SPACINGS = 0.8        # a tie end must lie this close to a notehead (ties start ~0.5 off it, measured)
LINE_ROW_TOL_SPACINGS = 0.25   # rows this close to a tracked line can hold that line's ink
TIE_MIN_WIDTH_SPACINGS = 1.2
TIE_MAX_HEIGHT_SPACINGS = 1.8
SLUR_MAX_HEIGHT_SPACINGS = 3.5
ARC_MAX_THICK_SPACINGS = 0.5   # median ink thickness of the arc
ARC_MIN_SAG_SPACINGS = 0.1     # middle vs ends: a straight dash is not a tie
TIE_LEVEL_SPACINGS = 0.7       # end-to-end height difference of a same-pitch tie
END_FRAC = 0.08                # fraction of the width forming each end
SURVIVE_MIN = 0.95             # candidate pixels that must remain for "survived"
BEAM_HEIGHT_SPACINGS = 0.36    # opening kernel: thicker than a staff line
BEAM_WIDTH_SPACINGS = 1.5
BEAM_REMOVED_MIN_PX = 6        # removed pixels on a beam shape that get listed for viewing
BAND_HALF_SPACINGS = 2.0       # the five lines span +/- 2 spacings from the centre
BEAM_REACH_SPACINGS = 4.5      # a beam lies within this many spacings of a staff's lines (stem reach)
BEAM_STEM_TOUCH_PX = 2         # a beam must touch a stem within this many px
STRIP_HEIGHT = 64
MIN_CAND_AREA_PX = 6
FIDELITY_BAND_SPACINGS = 2.5   # rows compared for thin-glyph fidelity, around the staff centre


def _rect(rows: int, cols: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_RECT, (max(cols, 1), max(rows, 1)))


def _open(mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    return cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)


def line_row_mask(height: int, staves: list[tuple[float, float, float]], y0: int = 0) -> np.ndarray:
    """Bool per row (of a window starting at page row ``y0``) within tolerance of a staff line.

    Args:
        staves: (centre, spacing, slack) per tracked staff in page pixels.
    """
    rows = np.zeros(height, dtype=bool)
    for centre, spacing, slack in staves:
        tol = LINE_ROW_TOL_SPACINGS * spacing + slack
        for k in range(-2, 3):
            y = centre + k * spacing - y0
            rows[max(0, int(np.floor(y - tol))):max(0, min(height, int(np.ceil(y + tol)) + 1))] = True
    return rows


def thin_line_pixels(ink: np.ndarray, spacing: float, line_rows: np.ndarray) -> np.ndarray:
    """Pixels of staff lines: long thin horizontal runs lying on a tracked line's row.

    The row restriction matters: a long flat tie in a space is also a thin horizontal run and
    must not be classed as a staff line.
    """
    long_h = _open(ink, _rect(1, int(LINE_RUN_SPACINGS * spacing)))
    thick_v = _open(ink, _rect(max(int(round(VERT_THICK_SPACINGS * spacing)), 2), 1))
    # The opening keeps the line's core; ink one row either side (slightly sloped or bolded
    # line edges) is the same line and would otherwise survive as 1 px "arcs".
    fringe = cv2.dilate(long_h.astype(np.uint8), _rect(2 * LINE_FRINGE_PX + 1, 1)).astype(bool)
    return fringe & ink & ~thick_v & line_rows[:, None]


def beam_pixels(ink: np.ndarray, spacing: float, line_rows: np.ndarray) -> np.ndarray:
    """Thick horizontal-ish runs (beams): opening taller than a staff line, wider than a head."""
    beams = _open(ink, _rect(max(int(round(BEAM_HEIGHT_SPACINGS * spacing)), 2),
                             int(BEAM_WIDTH_SPACINGS * spacing)))
    return beams & ~thin_line_pixels(ink, spacing, line_rows)


def tie_candidates(ink: np.ndarray, spacing: float, line_rows: np.ndarray) -> list[dict[str, Any]]:
    """Finds tie/slur candidates on an ink window (see module docstring for the rules)."""
    lines = thin_line_pixels(ink, spacing, line_rows)
    resid = ink & ~lines
    head_d = max(int(round(HEAD_DIAM_SPACINGS * spacing)), 3)
    core = _open(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (head_d, head_d)))
    stems = _open(resid, _rect(max(int(STEM_RUN_SPACINGS * spacing), 3), 1))
    stems = cv2.dilate(stems.astype(np.uint8), _rect(1, 3)).astype(bool)
    arcs = resid & ~cv2.dilate(core.astype(np.uint8), _rect(3, 3)).astype(bool) & ~stems
    gap = max(int(round(HEAD_GAP_SPACINGS * spacing)), 2)
    near_head = cv2.dilate(core.astype(np.uint8),
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * gap + 1, 2 * gap + 1))
                           ).astype(bool)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(arcs.astype(np.uint8), connectivity=8)
    found: list[dict[str, Any]] = []
    for i in range(1, count):
        left, top, w, h, area = (int(v) for v in stats[i])
        if area < MIN_CAND_AREA_PX or w < TIE_MIN_WIDTH_SPACINGS * spacing:
            continue
        if h > SLUR_MAX_HEIGHT_SPACINGS * spacing:
            continue
        sub = labels[top:top + h, left:left + w] == i
        col = sub.sum(axis=0)
        if float(np.median(col[col > 0])) > ARC_MAX_THICK_SPACINGS * spacing:
            continue
        rows = np.arange(h, dtype=np.float64)[:, None]
        ymean = np.where(col > 0, (sub * rows).sum(axis=0) / np.maximum(col, 1), np.nan)
        end = max(2, int(END_FRAC * w))
        y_l, y_r = np.nanmean(ymean[:end]), np.nanmean(ymean[-end:])
        mid = slice(max(w // 2 - max(w // 10, 1), 0), w // 2 + max(w // 10, 1) + 1)
        sag = float(np.nanmean(ymean[mid]) - (y_l + y_r) / 2.0)
        if abs(sag) < ARC_MIN_SAG_SPACINGS * spacing:
            continue
        head_zone = near_head[top:top + h, left:left + w]
        if not (sub[:, :end] & head_zone[:, :end]).any() or not (sub[:, -end:] & head_zone[:, -end:]).any():
            continue
        level = abs(float(y_l - y_r)) <= TIE_LEVEL_SPACINGS * spacing
        kind = "tie" if level and h <= TIE_MAX_HEIGHT_SPACINGS * spacing else "slur"
        found.append({"x": left, "y": top, "w": w, "h": h, "kind": kind, "sub": sub})
    return found


def survival(cands: list[dict[str, Any]], masked_ink: np.ndarray, y0: int = 0, x0: int = 0) -> None:
    """Adds the surviving-pixel fraction (against ``masked_ink``) to each candidate in place."""
    for c in cands:
        win = masked_ink[y0 + c["y"]:y0 + c["y"] + c["h"], x0 + c["x"]:x0 + c["x"] + c["w"]]
        c["survival"] = float((c["sub"] & win).sum() / max(int(c["sub"].sum()), 1))


def _windows(detect_bgr: np.ndarray, s2: Any) -> list[tuple[dict, int, int]]:
    """(box, y1, y2) crop rows on the detection page for each classical-tracker staff."""
    boxes, _ = s2._classical_boxes(detect_bgr)
    out = []
    for i, box in enumerate(boxes):
        y1, y2 = s2._content_extent(detect_bgr, box, s2._neighbor_limits(boxes, i, detect_bgr.shape[0]))
        out.append((box, y1, y2))
    return out


def _cand_record(c: dict[str, Any], page_id: str, y_off: int, x_off: int, scale: float) -> dict[str, Any]:
    return {"page": page_id, "kind": c["kind"], "x": c["x"] + x_off, "y": c["y"] + y_off,
            "w": c["w"], "h": c["h"], "survival": round(c["survival"], 3), "scale": round(scale, 3)}


def _density_strip(gray: np.ndarray, y1: int, y2: int, ky: float) -> np.ndarray:
    crop = gray[int(round(y1 * ky)):int(round(y2 * ky))]
    new_w = int(crop.shape[1] * (STRIP_HEIGHT / crop.shape[0]))
    small = cv2.resize(crop, (new_w, STRIP_HEIGHT), interpolation=cv2.INTER_AREA)
    return ((255 - small.astype(np.float32)) / 255.0)


def audit_new(path: str, page_id: str, out: str) -> dict[str, Any]:
    """Audits one page with the current code."""
    sys.path.insert(0, str(REPO))
    import stage1_preprocessing as s1
    import stage2_detection as s2
    page = s1.preprocess_score_page(path, keep_unmasked=True)
    res: dict[str, Any] = {"page": page_id, "mode": "new", "mask_applied": page.mask_applied}
    if page.strip_binary is None or page.strip_unmasked is None:
        res["error"] = "no strip source (mask not applied)"
        return res
    detect_bgr = cv2.cvtColor(page.detect, cv2.COLOR_GRAY2BGR)
    raw_ink = page.strip_unmasked < 128
    # strip_source is gray since PIYA-106 Phase 0b; the mask verdict lives on the binary page.
    kept_ink = page.strip_binary < 128
    removed = raw_ink & ~kept_ink
    hi_h, hi_w = raw_ink.shape
    ky, kx = hi_h / page.detect.shape[0], hi_w / page.detect.shape[1]
    spacing = float(np.median([s.spacing for s in page.strip_staves]))
    res.update(staves=len(page.strip_staves), spacing_px=round(spacing, 2), removed_px=int(removed.sum()))

    hi_staff_tuples = [(s.center, s.spacing, s.slack) for s in page.strip_staves]

    # staff-band ink removed: rows within the five-line span (+ the un-dewarped wander) of a staff
    band = np.zeros(hi_h, dtype=bool)
    for s in page.strip_staves:
        reach = BAND_HALF_SPACINGS * s.spacing + s.slack
        band[max(0, int(np.floor(s.center - reach))):min(hi_h, int(np.ceil(s.center + reach)) + 1)] = True
    res["band_ink_removed_px"] = int(removed[band].sum())

    # beams: thick horizontal runs on the raw page that touch a stem and sit within stem reach of a
    # staff (so lyric words and title letters, which have neither, are not counted as beams), then
    # any overlap with removed ink is listed for viewing
    near = np.zeros(hi_h, dtype=bool)
    for s in page.strip_staves:
        reach = (BAND_HALF_SPACINGS + BEAM_REACH_SPACINGS) * s.spacing + s.slack
        near[max(0, int(np.floor(s.center - reach))):min(hi_h, int(np.ceil(s.center + reach)) + 1)] = True
    stems_raw = _open(raw_ink, _rect(max(int(STEM_RUN_SPACINGS * spacing), 3), 1))
    stems_raw = cv2.dilate(stems_raw.astype(np.uint8), _rect(2 * BEAM_STEM_TOUCH_PX + 1, 2 * BEAM_STEM_TOUCH_PX + 1)).astype(bool)
    beams = beam_pixels(raw_ink, spacing, line_row_mask(hi_h, hi_staff_tuples)) & near[:, None]
    n_lab, lab, st, _ = cv2.connectedComponentsWithStats(beams.astype(np.uint8), connectivity=8)
    has_stem = np.zeros(n_lab, dtype=bool)
    has_stem[np.unique(lab[stems_raw & beams])] = True
    has_stem[0] = False
    beams &= has_stem[lab]
    hit = beams & removed
    flagged = []
    for i in np.unique(lab[hit]):
        if i == 0:
            continue
        px = int((hit & (lab == i)).sum())
        if px >= BEAM_REMOVED_MIN_PX:
            flagged.append({"x": int(st[i, 0]), "y": int(st[i, 1]), "w": int(st[i, 2]), "h": int(st[i, 3]),
                            "removed_px": px})
    res["beam_shapes"] = int(has_stem.sum())
    res["beam_removed_flags"] = flagged

    # ties/slurs inside each staff's crop window (the rows a strip is cut from)
    cands: list[dict[str, Any]] = []
    strips_dir = Path(out) / "new" / "strips"
    ref_dir = Path(out) / "new" / "ref"
    strips_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)
    for idx, (box, y1, y2) in enumerate(_windows(detect_bgr, s2), start=1):
        ny1, ny2 = int(round(y1 * ky)), int(round(y2 * ky))
        win_raw = raw_ink[ny1:ny2]
        found = tie_candidates(win_raw, spacing, line_row_mask(ny2 - ny1, hi_staff_tuples, ny1))
        survival(found, kept_ink, ny1, 0)
        cands += [_cand_record(c, page_id, ny1, 0, ky) for c in found]
        strip = s2._crop_and_resize(detect_bgr, box, STRIP_HEIGHT, limits=s2._neighbor_limits(
            s2._classical_boxes(detect_bgr)[0], idx - 1, detect_bgr.shape[0]), source=page.strip_source)
        cv2.imwrite(str(strips_dir / f"{page_id}_s{idx:02d}.png"), strip)
        ref = _density_strip(page.strip_gray, y1, y2, ky)
        cv2.imwrite(str(ref_dir / f"{page_id}_s{idx:02d}.png"), np.clip(ref * 255, 0, 255).astype(np.uint8))
    res["cands"] = cands
    del page
    return res


def audit_old(path: str, page_id: str, out: str, old_src: str) -> dict[str, Any]:
    """Audits one page with the pre-PIYA-121 pipeline (module dir given by ``old_src``)."""
    sys.path.insert(0, str(Path(old_src).resolve()))
    import stage1_preprocessing as s1  # the OLD one, first on sys.path in this process
    import stage2_detection as s2
    binary, _ = s1.preprocess_score_image(path)
    bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    res: dict[str, Any] = {"page": page_id, "mode": "old"}
    boxes, _ = s2._classical_boxes(bgr)
    res["staves"] = len(boxes)
    if not boxes:
        return res
    spacing = float(np.median([b["spacing"] for b in boxes]))
    ink = binary < 128
    old_staves = [(b["cy"], b["spacing"], 0.0) for b in boxes]
    cands = []
    strips_dir = Path(out) / "old" / "strips"
    strips_dir.mkdir(parents=True, exist_ok=True)
    for idx, box in enumerate(boxes, start=1):
        limits = s2._neighbor_limits(boxes, idx - 1, bgr.shape[0])
        y1, y2 = s2._content_extent(bgr, box, limits)
        after = s2._crop_and_resize(bgr, box, y2 - y1, limits=limits, mask_lyrics=True)
        after_ink = np.zeros_like(ink)
        after_ink[y1:y2] = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY) < 128
        found = tie_candidates(ink[y1:y2], spacing, line_row_mask(y2 - y1, old_staves, y1))
        survival(found, after_ink, y1, 0)
        cands += [_cand_record(c, page_id, y1, 0, 1.0) for c in found]
        strip = s2._crop_and_resize(bgr, box, STRIP_HEIGHT, limits=limits, mask_lyrics=True)
        cv2.imwrite(str(strips_dir / f"{page_id}_s{idx:02d}.png"), strip)
    res["cands"] = cands
    return res


def page_list() -> list[tuple[str, str, str]]:
    """(page_id, path, set) for every page in the audit: dataset by split, BSN and DSMN as 'seen'."""
    split = json.loads(SPLIT_FILE.read_text(encoding="utf-8"))
    frozen, tuning = set(split["frozen"]), set(split["tuning"])
    pages = []
    with open(DATASET / "dataset_manifest.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            piece = row["piece"]
            if piece in frozen:
                group = "frozen"
            elif piece in tuning:
                group = "tuning"
            else:
                continue
            pages.append((Path(row["filename"]).stem, str(DATASET / row["filename"]), group))
    for name in BSN_FILES:
        pages.append((f"bsn_{Path(name).stem}", str(BSN_RAW / name), "seen_bsn"))
    for p in sorted(DSMN_RAW.glob("*.jpg")):
        pages.append((p.stem, str(p), "seen_dsmn"))
    return pages


def _run_one(args: tuple) -> dict[str, Any]:
    mode, page_id, path, group, out, old_src = args
    try:
        res = audit_new(path, page_id, out) if mode == "new" else audit_old(path, page_id, out, old_src)
    except Exception as exc:  # noqa: BLE001  one bad photo must not stop a 100-page audit; it is recorded
        res = {"page": page_id, "mode": mode, "error": f"{type(exc).__name__}: {exc}"}
    res["group"] = group
    (Path(out) / mode).mkdir(parents=True, exist_ok=True)
    (Path(out) / mode / f"{page_id}.json").write_text(json.dumps(res, default=int), encoding="utf-8")
    return {k: v for k, v in res.items() if k not in ("cands",)}


def fidelity(out: Path) -> dict[str, dict[str, float]]:
    """Thin-glyph fidelity of old vs new strips against the analog native reference strip.

    Compares the staff-band rows of each 64 px strip with the same crop of the native gray,
    area-shrunk to 64 px (no threshold). Only strips whose old and new widths agree within 2 px
    (same crop) are paired; the rest are counted as skipped.
    """
    stats: dict[str, dict[str, list[float]]] = {}
    skipped = 0
    for ref_path in sorted((out / "new" / "ref").glob("*.png")):
        name = ref_path.name
        old_path, new_path = out / "old" / "strips" / name, out / "new" / "strips" / name
        if not old_path.exists():
            continue
        ref = cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
        old = cv2.imread(str(old_path), cv2.IMREAD_GRAYSCALE)
        new = cv2.imread(str(new_path), cv2.IMREAD_GRAYSCALE)
        if abs(old.shape[1] - new.shape[1]) > 2 or abs(ref.shape[1] - new.shape[1]) > 2:
            skipped += 1
            continue
        w = min(old.shape[1], new.shape[1], ref.shape[1])
        row0, row1 = int(STRIP_HEIGHT * 0.2), int(STRIP_HEIGHT * 0.8)  # staff band of a strip
        r = ref[row0:row1, :w]
        page_id = name.rsplit("_s", 1)[0]
        group = json.loads((out / "new" / f"{page_id}.json").read_text(encoding="utf-8")).get("group", "?")
        for label, img in (("old", old), ("new", new)):
            d = (255 - img[row0:row1, :w].astype(np.float32)) / 255.0
            slot = stats.setdefault(f"{group}/{label}", {"mass": [], "corr": []})
            slot["mass"].append(float(d.sum() / max(r.sum(), 1e-6)))
            slot["corr"].append(float(np.corrcoef(d.ravel(), r.ravel())[0, 1]))
    summary = {k: {"n": len(v["mass"]), "mass_median": float(np.median(v["mass"])),
                   "corr_median": float(np.median(v["corr"]))} for k, v in stats.items()}
    summary["_skipped_pairs"] = {"n": skipped}
    return summary


def report(out: Path) -> None:
    """Prints tie survival, beam, band-ink and fidelity tables split by set."""
    groups = ["tuning", "frozen", "seen_bsn", "seen_dsmn"]
    for mode in ("old", "new"):
        print(f"\n=== tie/slur survival, {mode} pipeline (survival >= {SURVIVE_MIN}) ===")
        for g in groups:
            files = [json.loads(p.read_text(encoding="utf-8")) for p in (out / mode).glob("*.json")]
            files = [f for f in files if f.get("group") == g]
            errs = [f["page"] for f in files if "error" in f]
            for kind in ("tie", "slur"):
                cs = [c for f in files for c in f.get("cands", []) if c["kind"] == kind]
                ok = sum(c["survival"] >= SURVIVE_MIN for c in cs)
                print(f"  {g:10s} {kind:5s} pages={len(files) - len(errs):3d} candidates={len(cs):5d} "
                      f"survived={ok:5d} recall={ok / max(len(cs), 1):.4f} lost={len(cs) - ok}")
            if errs:
                print(f"  {g:10s} pages with errors: {errs}")
    print("\n=== new pipeline: staff-band ink / beams ===")
    for g in groups:
        files = [json.loads(p.read_text(encoding="utf-8")) for p in (out / "new").glob("*.json")]
        files = [f for f in files if f.get("group") == g and "error" not in f]
        band = sum(f["band_ink_removed_px"] for f in files)
        shapes = sum(f["beam_shapes"] for f in files)
        flags = [(f["page"], b) for f in files for b in f["beam_removed_flags"]]
        print(f"  {g:10s} pages={len(files):3d} staves={sum(f['staves'] for f in files):4d} "
              f"band_ink_removed_px={band} beam_shapes={shapes} beam_removal_flags={len(flags)}")
    print("\n=== thin-glyph fidelity (band rows of 64 px strips vs analog reference) ===")
    for k, v in sorted(fidelity(out).items()):
        print(f"  {k:22s} {v}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["new", "old", "report"], required=True)
    parser.add_argument("--out", default="data/audit")
    parser.add_argument("--old-src", default="data/scratch_mask/old",
                        help="dir holding the pre-PIYA-121 stage1_preprocessing.py / stage2_detection.py")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--only", nargs="*", help="page ids to run (default: all)")
    args = parser.parse_args()
    out = Path(args.out)
    if args.mode == "report":
        report(out)
        return
    pages = [p for p in page_list() if not args.only or p[0] in args.only]
    jobs = [(args.mode, pid, path, group, str(out), args.old_src) for pid, path, group in pages]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for res in pool.map(_run_one, jobs):
            print(res["page"], {k: v for k, v in res.items() if k not in ("page", "mode")})


if __name__ == "__main__":
    main()
