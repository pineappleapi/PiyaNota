"""PIYA-121 / BUG-015: pixel-level audit of Stage 2 lyric masking on the Step 3 set.

Why: the BUG-015 numbers were first produced by a one-off scratch script and a residual
list eyeballed from downscaled montages, which misread correctly-masked strips. This
regenerates every strip twice straight from ``_crop_and_resize`` (``mask_lyrics=False`` vs
``True``) at native resolution (target height == crop height, so no resampling) and reports
per-strip ink counts plus the 80-strip aggregate. It runs NO Stage 3/CRNN and changes no
masking threshold: Step 3 is a held-out test set.

"Leftover out-of-band ink" is a listing heuristic for human review, not a classifier:
ink remaining after masking whose rows lie outside the staff band (+ tolerance) and which
is not a thin stem-like sliver. Attached stems/ties legitimately reach out of the band, so
a flagged strip is a candidate for full-resolution inspection, not a confirmed residual.

Usage (run from repo root so stage2_detection imports; set PYTHONPATH=. if needed):
    python training/step3_mask_audit.py --prep data/step3_testset/preprocessed_v2 \
        --manifest data/step3_testset/strips/manifest.json [--viz-dir DIR] [--only ID ...]
"""

import argparse
import glob
import json
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

import stage2_detection as s2

INK_THRESHOLD = 127          # pages are binary; ink is dark
LEFTOVER_MIN_AREA_PX = 12    # ignore specks when listing leftover out-of-band pieces
LEFTOVER_STEM_MAX_WIDTH_PX = 3  # narrower than this = stem sliver, not text
LEFTOVER_LINE_MAX_HEIGHT_PX = 4  # shorter than this = tie/line sliver, not text
LEFTOVER_FLAG_PX = 600       # strip is listed for inspection above this many leftover px
CUT_MIN_DIST_PX = 4          # removed pieces closer than this to the band are line-fringe trim
BRIDGE_MIN_WIDTH_PX = 30     # a removed piece this wide, touching kept ink at BOTH ends...
BRIDGE_END_PX = 6            # ...within this many columns of either end = a bridged gap (tie/slur)
CUT_MIN_AREA_PX = 8          # ignore specks when counting cuts
CUT_VIZ_PAD_PX = 20          # context around a cut piece in the cut review image
CUT_VIZ_MAX_PIECES = 6       # largest N pieces per strip go into the cut review image
VIZ_SCALE = 3                # integer upscale for saved review images
VIZ_TILE_WIDTH_PX = 1500     # saved images are split into tiles no wider than this
PAGE_RE = re.compile(r"page_(\d+)_preprocessed\.png$")


def load_pages(prep_dir: str) -> dict[int, np.ndarray]:
    """Loads Stage 1 pages as BGR, keyed by page number, the way Stage 2 sees them."""
    pages: dict[int, np.ndarray] = {}
    for path in sorted(glob.glob(str(Path(prep_dir) / "page_*_preprocessed.png"))):
        match = PAGE_RE.search(path.replace("\\", "/").split("/")[-1])
        if match is None:
            continue
        gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        pages[int(match.group(1))] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return pages


def leftover_pieces(after_ink: np.ndarray, band_top: int, band_bottom: int,
                    tol: int) -> tuple[int, int]:
    """Counts out-of-band ink pieces left after masking (candidates for lyric residue).

    Returns:
        (pieces, pixels) of connected pieces of ink outside the band that are larger than
        a speck and wider than a stem.
    """
    outside = after_ink.copy()
    outside[max(band_top - tol, 0):band_bottom + tol + 1] = False
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        outside.astype(np.uint8), connectivity=8)
    pieces = pixels = 0
    for i in range(1, count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if (area < LEFTOVER_MIN_AREA_PX
                or stats[i, cv2.CC_STAT_WIDTH] <= LEFTOVER_STEM_MAX_WIDTH_PX
                or stats[i, cv2.CC_STAT_HEIGHT] <= LEFTOVER_LINE_MAX_HEIGHT_PX):
            continue
        pieces += 1
        pixels += area
    return pieces, pixels


def audit_strip(image: np.ndarray, entry: dict[str, Any],
                limits: tuple[int, int]) -> dict[str, Any]:
    """Regenerates one strip with and without masking and measures the difference."""
    box = dict(entry["box"])
    y1, y2 = s2._content_extent(image, box, limits)
    height = y2 - y1
    kwargs = dict(strip_id=entry["strip_id"], limits=limits)
    before = s2._crop_and_resize(image, box, height, mask_lyrics=False, **kwargs)
    after = s2._crop_and_resize(image, box, height, mask_lyrics=True, **kwargs)
    if before.shape != after.shape:
        raise ValueError(f"{entry['strip_id']}: shape changed {before.shape} vs {after.shape}")
    before_g, after_g = before[..., 0], after[..., 0]
    ink_before, ink_after = before_g < INK_THRESHOLD, after_g < INK_THRESHOLD
    removed = ink_before & ~ink_after
    added = ~ink_before & ink_after

    band_top, band_bottom = box["y1"] - y1, box["y2"] - y1
    spacing = (box["y2"] - box["y1"]) / s2.CROP_STAFF_SPACINGS
    tol = int(round(spacing * s2.MASK_ATTACH_TOL_SPACINGS))
    slack = int(round(spacing * s2.MASK_LINE_BAND_SPACINGS))
    in_band = np.zeros_like(ink_before)
    in_band[max(band_top, 0):band_bottom + 1] = True
    near_band = np.zeros_like(ink_before)
    near_band[max(band_top - slack, 0):band_bottom + slack + 1] = True
    pieces, piece_px = leftover_pieces(ink_after, band_top, band_bottom, tol)

    # A removed piece that touches ink the mask KEPT and lies clear of the staff band was
    # cut off something (a tie, stem or glyph), which is worse than a leftover lyric. Pieces
    # hugging the band are 1-2 px trims of a wobbly outer staff line and are not counted.
    # Neighbour-staff line fragments can also land here, so a count is a lead, not a verdict.
    kept_zone = cv2.dilate(ink_after.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        removed.astype(np.uint8), connectivity=8)
    cut_pieces = cut_px = 0
    cut_boxes: list[tuple[int, int, int, int]] = []
    bridges = 0
    for i in range(1, count):
        top = int(stats[i, cv2.CC_STAT_TOP])
        bottom = top + int(stats[i, cv2.CC_STAT_HEIGHT]) - 1
        dist = max(band_top - bottom, top - band_bottom, 0)
        if (stats[i, cv2.CC_STAT_AREA] >= CUT_MIN_AREA_PX and dist >= CUT_MIN_DIST_PX
                and kept_zone[labels == i].any()):
            cut_pieces += 1
            cut_px += int(stats[i, cv2.CC_STAT_AREA])
            left, width = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_WIDTH])
            piece = labels == i
            if width >= BRIDGE_MIN_WIDTH_PX:
                near_left = kept_zone[:, left:left + BRIDGE_END_PX] & piece[:, left:left + BRIDGE_END_PX]
                right_start = left + width - BRIDGE_END_PX
                near_right = (kept_zone[:, right_start:left + width]
                              & piece[:, right_start:left + width])
                bridges += int(near_left.any() and near_right.any())
            cut_boxes.append((int(stats[i, cv2.CC_STAT_LEFT]), top,
                              int(stats[i, cv2.CC_STAT_WIDTH]), bottom - top + 1))

    return {
        "strip_id": entry["strip_id"], "before": before, "after": after,
        "removed_mask": removed, "added_px": int(added.sum()),
        "ink_before": int(ink_before.sum()), "ink_after": int(ink_after.sum()),
        "removed_px": int(removed.sum()),
        "band_removed_px": int((removed & in_band).sum()),
        "near_band_removed_px": int((removed & near_band).sum()),
        "cut_pieces": cut_pieces, "cut_px": cut_px, "cut_boxes": cut_boxes, "bridges": bridges,
        "oob_before": int((ink_before & ~near_band).sum()),
        "oob_after": int((ink_after & ~near_band).sum()),
        "leftover_pieces": pieces, "leftover_px": piece_px,
    }


def save_viz(result: dict[str, Any], out_dir: Path) -> None:
    """Writes before / after / removed-ink stacks, upscaled and tiled for full-res viewing.

    Rows of each tile: before, after, removed ink in red. Wide strips are split into
    tiles so an image viewer does not downscale them.
    """
    before, after = result["before"], result["after"]
    diff = np.full_like(before, 255)
    diff[result["removed_mask"]] = (0, 0, 255)
    sep = np.full((2, before.shape[1], 3), 128, np.uint8)
    stacked = np.vstack([before, sep, after, sep, diff])
    stacked = cv2.resize(stacked, None, fx=VIZ_SCALE, fy=VIZ_SCALE,
                         interpolation=cv2.INTER_NEAREST)
    out_dir.mkdir(parents=True, exist_ok=True)
    for tile, x in enumerate(range(0, stacked.shape[1], VIZ_TILE_WIDTH_PX)):
        cv2.imwrite(str(out_dir / f"{result['strip_id']}_t{tile}.png"),
                    stacked[:, x:x + VIZ_TILE_WIDTH_PX])


def save_cut_viz(result: dict[str, Any], out_dir: Path) -> None:
    """Writes one image per strip: for each cut candidate, before | after side by side."""
    rows = []
    h, w = result["before"].shape[:2]
    biggest = sorted(result["cut_boxes"], key=lambda b: -b[2] * b[3])[:CUT_VIZ_MAX_PIECES]
    for x, y, bw, bh in biggest:
        x0, x1 = max(x - CUT_VIZ_PAD_PX, 0), min(x + bw + CUT_VIZ_PAD_PX, w)
        y0, y1 = max(y - CUT_VIZ_PAD_PX, 0), min(y + bh + CUT_VIZ_PAD_PX, h)
        pair = np.hstack([result["before"][y0:y1, x0:x1], np.full((y1 - y0, 3, 3), 128, np.uint8),
                          result["after"][y0:y1, x0:x1]])
        rows.append(cv2.resize(pair, None, fx=VIZ_SCALE + 1, fy=VIZ_SCALE + 1,
                               interpolation=cv2.INTER_NEAREST))
    if not rows:
        return
    width = max(r.shape[1] for r in rows)
    padded = [np.pad(r, ((0, 6), (0, width - r.shape[1]), (0, 0)), constant_values=128) for r in rows]
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / f"{result['strip_id']}_cuts.png"), np.vstack(padded))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prep", required=True, help="Stage 1 preprocessed pages dir")
    parser.add_argument("--manifest", required=True, help="Stage 2 strips manifest.json")
    parser.add_argument("--viz-dir", default=None,
                        help="If set, save before/after/removed stacks (rows: before, after, removed)")
    parser.add_argument("--cut-viz-dir", default=None,
                        help="If set, save before|after crops around each possible-cut piece")
    parser.add_argument("--only", nargs="*", default=None,
                        help="Substrings; only save viz for matching strip ids")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    pages = load_pages(args.prep)
    by_page: dict[int, list[dict[str, Any]]] = {}
    for entry in manifest:
        by_page.setdefault(entry["page"], []).append(entry)

    results: list[dict[str, Any]] = []
    for page, entries in sorted(by_page.items()):
        image = pages[page]
        boxes = [dict(e["box"]) for e in entries]  # already sorted top-to-bottom
        for i, entry in enumerate(entries):
            limits = s2._neighbor_limits(boxes, i, image.shape[0])
            results.append(audit_strip(image, entry, limits))

    print(f"{'strip_id':38s} {'inkB':>7s} {'inkA':>7s} {'rem':>6s} {'band':>5s} "
          f"{'nearB':>5s} {'cut_n':>5s} {'cut_px':>6s} {'brdg':>4s} {'add':>4s} {'oobB':>6s} {'oobA':>6s} {'lo_n':>4s} {'lo_px':>6s}")
    for r in results:
        print(f"{r['strip_id']:38s} {r['ink_before']:7d} {r['ink_after']:7d} {r['removed_px']:6d} "
              f"{r['band_removed_px']:5d} {r['near_band_removed_px']:5d} {r['cut_pieces']:5d} {r['cut_px']:6d} {r['bridges']:4d} "
              f"{r['added_px']:4d} {r['oob_before']:6d} {r['oob_after']:6d} "
              f"{r['leftover_pieces']:4d} {r['leftover_px']:6d}")

    total = lambda key: sum(r[key] for r in results)  # noqa: E731
    changed = sum(1 for r in results if r["removed_px"] > 0)
    print(f"\nAGGREGATE over {len(results)} strips")
    print(f"  ink before/after: {total('ink_before')} -> {total('ink_after')}; "
          f"removed {total('removed_px')}; pixels ADDED by mask: {total('added_px')}")
    print(f"  removed in staff band rows: {total('band_removed_px')}; "
          f"within line slack of band: {total('near_band_removed_px')}; "
          f"removed pieces touching kept ink (possible cuts): {total('cut_pieces')} pieces / {total('cut_px')} px")
    print(f"  out-of-band ink {total('oob_before')} -> {total('oob_after')} "
          f"({100 * (1 - total('oob_after') / max(total('oob_before'), 1)):.1f}% removed); "
          f"strips changed: {changed}/{len(results)}")
    bridged = [r for r in results if r["bridges"]]
    print(f"  strips with a removed piece bridging kept ink at both ends (tie/slur gap): "
          f"{len(bridged)}: " + ", ".join(r["strip_id"].split("_vidx")[0] for r in bridged))
    flagged = [r for r in results if r["leftover_px"] >= LEFTOVER_FLAG_PX]
    print(f"  strips with >= {LEFTOVER_FLAG_PX} leftover out-of-band px (inspect at full res): "
          f"{len(flagged)}")
    for r in sorted(flagged, key=lambda x: -x["leftover_px"]):
        print(f"    {r['strip_id']}: {r['leftover_pieces']} pieces, {r['leftover_px']} px")

    if args.cut_viz_dir:
        for r in results:
            if r["cut_pieces"]:
                save_cut_viz(r, Path(args.cut_viz_dir))
    if args.viz_dir:
        for r in results:
            if args.only is None or any(s in r["strip_id"] for s in args.only):
                save_viz(r, Path(args.viz_dir))


if __name__ == "__main__":
    main()
