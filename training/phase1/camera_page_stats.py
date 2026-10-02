"""Page-contrast and stroke statistics of the dev camera pages, the targets for Phase 1 camera augmentation.

Why (PIYA-106 plan, Phase 1 step 5 and the step-5 augmentation amendment): augmentation ranges are matched to
measured page statistics, not to SER. The quantities are the ml-cv-lead exploratory panel (native interline,
staff-line depth, notehead depth, their ratio, line FWHM) plus illumination spread and paper noise, measured on
the raw grey page before any Stage 1 blur or threshold, so `cut_corpus.py` can measure its augmented pages the
same way and compare. Dev data only (eval_prelim, user decision 2026-09-28); this makes Honneur less independent,
a trade-off the plan accepts.

Input: the Phase 0b Stage 1 cache (`_build_strip_source` arguments per dev page). Output: JSON with per-page values
and camera/digital summaries.

PENDING (2026-10-01, gate amendment (a)): camera_page_stats.json was measured with the old whole-pixel FWHM and
must be recomputed before the next smoke (`cut_corpus.py run/report` refuse a camera JSON without the current
FWHM_METHOD). Keep the old file for provenance, then record the new sha256:
  copy D:/PiyaNota-training/data/phase1_strips/camera_page_stats.json
       D:/PiyaNota-training/data/phase1_strips/camera_page_stats_v3_integer_fwhm.json
  python training/phase1/camera_page_stats.py --out D:/PiyaNota-training/data/phase1_strips/camera_page_stats.json
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import stage1_preprocessing as s1  # noqa: E402  (unpickling StaffBand needs the module)

DEFAULT_CACHE = Path("D:/PiyaNota-training/data/eval_prelim/_s1_cache_phase0b")
STAFF_LINES = 5
BAND_HALF_SPACINGS = 2.5      # staff band = centre +- 2.5 interlines (lines at +-2)
PURE_COLUMN_QUANTILE = 30     # inked columns at or below this ink percentile hold only staff lines
STAFF_COLUMN_MIN_INK_FRAC = 0.5  # a column inside the staff carries at least half the median column's ink
LINE_SEARCH_SPACINGS = 0.3    # look for each line's minimum this far around its expected row
PAPER_WINDOW_SPACINGS = 0.5   # local paper = column p90 within this distance of the line
X_SMOOTH_SPACINGS = 0.5       # horizontal box smoothing before the per-column minimum (lines are horizontal)
NOTEHEAD_PERCENTILE = 1       # "notehead depth" = band p1 depth (panel definition)
ILLUM_LO_PCT, ILLUM_HI_PCT = 5, 95
NOISE_HP_SIGMA_SPACINGS = 0.5  # high-pass for noise: subtract a blur this wide
MIN_PURE_COLUMNS = 20
SUMMARY_PCTS = (5, 25, 50, 75, 95)
COMB_MIN_REL = 0.03           # a staff column: its 5 line rows are >= 3% of paper darker than the mid rows ...
COMB_REL_TO_P90 = 0.4         # ... and >= 40% of the band's p90 comb (paper texture alone passed 3%: bwv126.6 p3)
COMB_P = 90
COMB_GAP_SPACINGS = 3.0       # comb columns closer than this are one staff (bridges noteheads, barlines)
# Paper-only mask for paper_grey / illum_ratio (2026-10-01, ml-cv-lead ruling (c)). Stage 1's `bg` (a max filter of
# the page) covers the whole frame, so table / background past the sheet entered both statistics. A dark background
# is separated by Otsu on log(bg), but only when the two classes really differ (a smooth illumination gradient on
# a frame-filling sheet must not be split in two); the paper is then the bright region connected to the staves.
PAPER_SPLIT_MAX_CLASS_RATIO = 0.75  # dark-class mean / bright-class mean must be below this to count as background
PAPER_MIN_PX = 100
# Gate amendment (a), 2026-10-01 (ml-cv-lead recal2): line FWHM is the distance between the two half-maximum
# crossings, each linearly interpolated between the samples either side of it. The old whole-pixel count of samples
# below half maximum quantised a 2-3 px line to 2 or 3 px (0.10 / 0.14 interline at 21 px), coarser than the gap
# between camera p5 and p50. Written into the output JSON so `cut_corpus.py` refuses camera stats measured the old
# way; the augmented pages are measured by this same function (cut_corpus imports page_stats).
FWHM_METHOD = "subpixel_linear_half_max_v1"
EDGE_HALF_PX = 0.5            # a side still below half max at the window edge is clamped to that sample's outer edge


def staff_columns(smooth: np.ndarray, spacing: float, centre: float) -> np.ndarray:
    """Boolean mask of the columns between the staff's left and right ends (longest line-comb run).

    Why: without it the "inked" columns of an augmented page include paper margins and frame background, whose
    illumination residue after background division passes the 0.5-median ink test while carrying no line; those
    columns reported line depth ~0.06 on staves whose real lines measure ~0.48 (smoke-50, 2026-10-01). The comb
    test (line rows darker than the rows midway between them) holds only where the five lines exist.
    """
    n_rows, n_cols = smooth.shape
    r = max(1, int(round(LINE_SEARCH_SPACINGS * spacing)))
    line_rows: list[np.ndarray] = []
    mid_rows: list[np.ndarray] = []
    for k in range(-2, 3):
        y0 = int(round(centre + k * spacing))
        line_rows.append(smooth[max(0, y0 - r):min(n_rows, y0 + r + 1)].min(axis=0))
    for k in range(-2, 2):
        mid_rows.append(smooth[min(n_rows - 1, int(round(centre + (k + 0.5) * spacing)))])
    paper = np.maximum(np.percentile(smooth, 90, axis=0), 1.0)
    strength = (np.median(np.stack(mid_rows), 0) - np.median(np.stack(line_rows), 0)) / paper
    comb = strength >= max(COMB_MIN_REL, COMB_REL_TO_P90 * float(np.percentile(strength, COMB_P)))
    idx = np.flatnonzero(comb)
    out = np.zeros(n_cols, bool)
    if idx.size == 0:
        return out
    gap = max(1, int(round(COMB_GAP_SPACINGS * spacing)))
    runs: list[tuple[int, int]] = []
    start = prev = int(idx[0])
    for x in idx[1:]:
        if x - prev > gap:
            runs.append((start, prev))
            start = int(x)
        prev = int(x)
    runs.append((start, prev))
    a, b = max(runs, key=lambda t: t[1] - t[0])
    out[a:b + 1] = True
    return out


def paper_mask(bg: np.ndarray, staff_rows: list[float]) -> np.ndarray:
    """Boolean mask of the paper sheet in Stage 1's background field (detection resolution).

    Why connected to the staves: the staves are on the paper by definition, while a bright patch of table or a
    second sheet elsewhere in the frame is not part of the page whose illumination the strips see.
    """
    lg = np.log(np.maximum(bg.astype(np.float32), 1.0))
    u8 = cv2.normalize(lg, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    t, _ = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = u8 > t
    full = np.ones(bg.shape, bool)
    if bright.all() or not bright.any():
        return full
    lo_mean, hi_mean = float(bg[~bright].mean()), float(bg[bright].mean())
    if lo_mean >= PAPER_SPLIT_MAX_CLASS_RATIO * hi_mean:
        return full
    n, lab = cv2.connectedComponents(bright.astype(np.uint8))
    keep: set[int] = set()
    for r in staff_rows:
        row = int(round(min(max(r, 0), bg.shape[0] - 1)))
        keep.update(int(v) for v in np.unique(lab[row][bright[row]]))
    keep.discard(0)
    mask = np.isin(lab, sorted(keep)) if keep else bright
    if int(mask.sum()) < PAPER_MIN_PX:
        raise ValueError("paper mask too small; the staves are not on a bright region")
    return mask


def half_max_width(profile: np.ndarray, level: float) -> float:
    """Sub-pixel width (px) of the dip around the profile's minimum, between its two crossings of `level`.

    Each crossing is linearly interpolated between the last sample at or above `level` and the first sample below
    it. Only the contiguous run around the minimum counts: a second dip in the window is another stroke, not this
    line. A side that stays below `level` up to the window edge is clamped EDGE_HALF_PX beyond the edge sample,
    which is what the old whole-pixel count gave for that side.

    Args:
        profile: 1-D grey values across the line (the rows of one column), ink dark.
        level: half-maximum level, paper - depth / 2.

    Returns:
        Width in px; 0.0 when the minimum is not below `level`.
    """
    v = np.asarray(profile, dtype=np.float64)
    n = v.size
    i_min = int(np.argmin(v))
    if not v[i_min] < level:
        return 0.0
    a = i_min
    while a > 0 and v[a - 1] < level:
        a -= 1
    b = i_min
    while b < n - 1 and v[b + 1] < level:
        b += 1
    # v[a - 1] >= level > v[a]: the crossing lies (v[a - 1] - level) / (v[a - 1] - v[a]) of a sample after a - 1.
    left = a - EDGE_HALF_PX if a == 0 else (a - 1) + (v[a - 1] - level) / (v[a - 1] - v[a])
    right = b + EDGE_HALF_PX if b == n - 1 else b + (level - v[b]) / (v[b + 1] - v[b])
    return float(right - left)


def line_column_stats(cols: np.ndarray, spacing: float, centre: float) -> tuple[list[float], list[float]]:
    """Depth (0..1 of local paper) and FWHM (interlines) of each staff line, per pure column, then median.

    Why per column and not on a column-median profile: residual dewarp wander of a 2-3 px line by a few px makes
    the line absent from most columns at any one row, so a median profile reports paper (an early version of this
    script measured line depth 0.02 that way). `cols` is already smoothed along x to cut noise, so the per-column
    minimum is not just the deepest noise sample. FWHM is sub-pixel (gate amendment (a), see FWHM_METHOD).
    """
    depths: list[float] = []
    fwhms: list[float] = []
    n_rows = cols.shape[0]
    r = max(1, int(round(LINE_SEARCH_SPACINGS * spacing)))
    pr = max(r + 1, int(round(PAPER_WINDOW_SPACINGS * spacing)))
    for k in range(-2, 3):
        y0 = int(round(centre + k * spacing))
        lo, hi = max(0, y0 - r), min(n_rows, y0 + r + 1)
        plo, phi = max(0, y0 - pr), min(n_rows, y0 + pr + 1)
        if hi - lo < 3:
            continue
        win = cols[lo:hi]
        paper = np.percentile(cols[plo:phi], 90, axis=0)
        low = win.min(axis=0)
        depth = paper - low
        ok = depth > 0
        if ok.sum() < MIN_PURE_COLUMNS:
            continue
        level = paper - depth / 2
        widths = np.array([half_max_width(win[:, c], float(level[c])) for c in np.flatnonzero(ok)])
        depths.append(float(np.median(depth[ok] / np.maximum(paper[ok], 1.0))))
        fwhms.append(float(np.median(widths)) / spacing)
    return depths, fwhms


def page_stats(args: tuple, spacing_hint: list[float]) -> dict[str, object]:
    hi, bg, map_y, _border_lo, staves = args
    gray = cv2.cvtColor(hi, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = h / bg.shape[0]
    bg_up = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    norm = cv2.divide(gray, bg_up, scale=255)
    if map_y is not None:
        norm = s1._remap_rows(norm, map_y)
    normf = norm.astype(np.float32)
    staff_rows: list[dict[str, float]] = []
    noise: list[float] = []
    for st in staves:
        c, sp = scale * (st.center + 0.5) - 0.5, st.spacing * scale
        y1, y2 = int(c - BAND_HALF_SPACINGS * sp), int(c + BAND_HALF_SPACINGS * sp) + 1
        if y1 < 0 or y2 > h:
            continue
        band = normf[y1:y2]
        k_x = max(1, int(round(X_SMOOTH_SPACINGS * sp)))
        smooth = cv2.blur(band, (k_x, 1))
        ink = (255.0 - band).sum(0)
        # Margin columns beyond the staff ends carry no lines and the least ink of all, so they must be excluded
        # before taking the low-ink (lines-only) columns, or "line depth" measures blank paper.
        inked = (ink >= STAFF_COLUMN_MIN_INK_FRAC * np.median(ink)) & staff_columns(smooth, sp, c - y1)
        if inked.sum() < MIN_PURE_COLUMNS:
            continue
        pure = inked & (ink <= np.percentile(ink[inked], PURE_COLUMN_QUANTILE))
        if pure.sum() < MIN_PURE_COLUMNS:
            continue
        depths, fwhms = line_column_stats(smooth[:, pure], sp, c - y1)
        if len(depths) < STAFF_LINES - 1:
            continue
        paper_level = float(np.percentile(band, 90))
        head_depth = (paper_level - float(np.percentile(band, NOTEHEAD_PERCENTILE))) / max(paper_level, 1.0)
        line_depth = float(np.median(depths))
        hp = band - cv2.GaussianBlur(band, (0, 0), NOISE_HP_SIGMA_SPACINGS * sp)
        mid_rows = [int(round(c - y1 + (k + 0.5) * sp)) for k in range(-2, 2)]
        vals = hp[mid_rows][:, pure].ravel()
        mad = float(np.median(np.abs(vals - np.median(vals))))
        noise.append(1.4826 * mad / max(paper_level, 1.0))
        staff_rows.append({"interline_px": sp, "line_depth": line_depth, "head_depth": head_depth,
                           "line_head_ratio": line_depth / head_depth if head_depth > 0 else float("nan"),
                           "line_fwhm_il": float(np.median(fwhms))})
    bg_f = bg.astype(np.float32)
    pm = paper_mask(bg, [st.center for st in staves])
    pv = bg_f[pm]
    return {"native_h": h, "native_w": w, "paper_grey": float(np.median(pv)),
            "illum_ratio": float(np.percentile(pv, ILLUM_LO_PCT) / max(np.percentile(pv, ILLUM_HI_PCT), 1.0)),
            "paper_area_frac": float(pm.mean()),
            "paper_grey_frame": float(np.median(bg_f)),
            "illum_ratio_frame": float(np.percentile(bg_f, ILLUM_LO_PCT) / max(np.percentile(bg_f, ILLUM_HI_PCT),
                                                                                1.0)),
            "noise_rel": float(np.median(noise)) if noise else None,
            "staves": staff_rows, "n_staves_measured": len(staff_rows), "n_staves": len(spacing_hint)}


def summarise(pages: dict[str, dict[str, object]]) -> dict[str, dict[str, list[float]]]:
    keys = ("interline_px", "line_depth", "head_depth", "line_head_ratio", "line_fwhm_il")
    out: dict[str, dict[str, list[float]]] = {}
    for cond in ("camera", "digital"):
        sel = [v for k, v in pages.items() if k.startswith(cond)]
        rows = [r for v in sel for r in v["staves"]]  # type: ignore[union-attr]
        s: dict[str, list[float]] = {}
        for key in keys:
            arr = np.array([r[key] for r in rows], dtype=float)
            arr = arr[np.isfinite(arr)]
            s[key] = [round(float(np.percentile(arr, p)), 4) for p in SUMMARY_PCTS] if arr.size else []
        for key in ("paper_grey", "illum_ratio", "noise_rel", "paper_area_frac", "paper_grey_frame",
                    "illum_ratio_frame"):
            arr = np.array([v[key] for v in sel if v[key] is not None], dtype=float)
            s[key] = [round(float(np.percentile(arr, p)), 4) for p in SUMMARY_PCTS] if arr.size else []
        s["n_pages"] = [float(len(sel))]
        s["n_staves"] = [float(len(rows))]
        out[cond] = s
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    pages: dict[str, dict[str, object]] = {}
    for pkl in sorted(a.cache.glob("*.pkl")):
        d = pickle.loads(pkl.read_bytes())
        pages[pkl.stem] = page_stats(d["args"], d["spacing"])
        print(pkl.stem, {k: v for k, v in pages[pkl.stem].items() if k != "staves"}, flush=True)
    result = {"fwhm_method": FWHM_METHOD, "summary_percentiles": list(SUMMARY_PCTS), "summary": summarise(pages),
              "pages": pages}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["summary"], indent=1))


if __name__ == "__main__":
    main()
