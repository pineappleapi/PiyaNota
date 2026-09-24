"""
PiyaNota - Stage 2: Staff Region Detection (YOLOv8)
Detects and extracts individual staff strips from preprocessed score pages.
"""

import json
import logging

import cv2
import numpy as np
from pathlib import Path

# Ultralytics YOLOv8 — install with: pip install ultralytics
from ultralytics import YOLO

from stage1_preprocessing import StaffCurve, track_staff_curves

logger = logging.getLogger(__name__)


# ── Voice assignment by vertical index within a 4-staff SATB system ──────────
VOICE_MAP = {1: "Soprano", 2: "Alto", 3: "Tenor", 4: "Bass"}

# Detection thresholds
CONF_THRESHOLD = 0.4   # minimum confidence to keep a detection
NMS_THRESHOLD  = 0.3   # IoU threshold for Non-Maximum Suppression
STRIP_HEIGHT   = 64     # fixed height for CRNN-CTC input (px); must equal Stage 3's img_height


# Classical-prior reconciliation (BUG-001). YOLO alone returns 10/12 staves on
# some camera photos; an independent line-tracking count validates and repairs it.
BINARY_THRESHOLD = 127          # preprocessed pages are already binary; any mid value works
MATCH_MAX_CENTER_SPACINGS = 2.5  # YOLO box center may sit this many line-spacings off a curve and still "agree"
# Half-height of a classical box. 2.1 spacings (box ~4.2) matches YOLO's typical box height on
# these photos (~3.8-4.5): crop padding scales with box height, so a taller box would shrink
# the staff to ~36% of the strip vs ~50% for YOLO boxes and change the CRNN's glyph scale.
CLASSICAL_BOX_HALF_SPACINGS = 2.1
MAX_BOXES_PER_PAGE = 16          # Rule 2 cap (4 systems x 4 voices)
STAFFS_PER_SYSTEM = 4
MASK_LYRICS_DEFAULT = True       # blank non-staff ink in strips; mask_lyrics=False restores the old strips


def detect_staff_regions(
    preprocessed_images: list,
    model_weights: str = "staff_detector_files\\weights\\best.pt",
    output_dir: str = "data/strips",
    save_strips: bool = True,
    save_viz: bool = False,          # ← new flag
    viz_dir: str = "data/detection_viz",
    manifest_path: str | None = None,
    mask_lyrics: bool = MASK_LYRICS_DEFAULT,
) -> dict:
    """Detects staves per page and crops one fixed-height strip per staff.

    Args:
        manifest_path: If set, writes a JSON list of {strip_id, page, system,
            voice, box, source} so a strip can be traced back to its page region.
        mask_lyrics: Blank lyric/dynamic/label ink that is not attached to the staff.
    """
    manifest: list[dict] = []
    output_path = Path(output_dir)
    if save_strips:
        output_path.mkdir(parents=True, exist_ok=True)

    viz_path = Path(viz_dir)
    if save_viz:
        viz_path.mkdir(parents=True, exist_ok=True)

    model = YOLO(model_weights)

    voice_sequences = {"Soprano": [], "Alto": [], "Tenor": [], "Bass": []}

    for image, page_index in preprocessed_images:
        if len(image.shape) == 2:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            image_bgr = image.copy()

        img_h, img_w = image_bgr.shape[:2]

        # ── Single model call per page ────────────────────────────────────
        results = model(image_bgr, conf=CONF_THRESHOLD, iou=NMS_THRESHOLD, verbose=False)


        boxes   = _extract_boxes(results)

        # Rule 1: Filter out low-confidence detections before grouping
        boxes = [b for b in boxes if b["conf"] >= CONF_THRESHOLD]

        # Rule 2: cap at 16 (4 systems × 4 voices max)
        if len(boxes) > 16:
            boxes = sorted(boxes, key=lambda b: b["conf"], reverse=True)[:16]

        # Rule 3: sort top-to-bottom for correct SATB grouping
        boxes = sorted(boxes, key=lambda b: b["cy"])

        # Rule 3.5: remove duplicate detections on the same staff
        boxes = _remove_duplicates(boxes, min_cy_gap=30)

        # Rule 3.55: cross-check against the classical staff tracker (BUG-001).
        boxes = _reconcile_with_classical(boxes, image_bgr, page_index)

        # Rule 3.6: staff-count validation — open-score enforcement (PIYA-105 #4)
        if len(boxes) != 0 and len(boxes) % 4 != 0:
            raise ValueError(
                f"[Stage 2] page {page_index}: unsupported_staff_layout — "
                f"detected {len(boxes)} staff region(s) after filtering/dedup, "
                f"not divisible by 4. Closed-score (2-staff) SATB is not "
                f"supported (see docs/sow.md Section 3)."
            )

        # ── DEBUG: print raw box heights ──────────────────────────────────────
        for b in boxes:
            print(f"  [Stage 2] y1={b['y1']} y2={b['y2']} height={b['y2']-b['y1']}px conf={b['conf']:.2f}")

        # Rule 4: stretch to full width — stafflines always span full page
        for b in boxes:
            b["x1"] = 0
            b["x2"] = img_w

        if len(boxes) == 0:
            print(f"[Stage 2] WARNING: No staff regions detected on page {page_index}.")
            continue

        print(f"[Stage 2] Page {page_index}: {len(boxes)} staff region(s) detected.")

        # ── Visualization after validation ────────────────────────────────
        if save_viz:
            _draw_and_save_viz(image_bgr, boxes, page_index, viz_path)

        systems = [boxes[i:i+4] for i in range(0, len(boxes), 4)]

        box_index = {id(b): i for i, b in enumerate(boxes)}
        for sys_idx, system in enumerate(systems, start=1):
            for v_idx, box in enumerate(system, start=1):
                voice = VOICE_MAP.get(v_idx, f"Voice_{v_idx}")
                strip_id = f"page{page_index:03d}_sys{sys_idx:02d}_{voice}_vidx{v_idx}"
                strip = _crop_and_resize(
                    image_bgr, box, STRIP_HEIGHT, strip_id=strip_id,
                    limits=_neighbor_limits(boxes, box_index[id(box)], img_h),
                    mask_lyrics=mask_lyrics)
                voice_sequences[voice].append((strip, page_index, sys_idx, voice, v_idx))
                manifest.append({
                    "strip_id": strip_id, "page": page_index, "system": sys_idx,
                    "voice": voice, "source": box.get("source", "yolo"),
                    "box": {k: int(box[k]) for k in ("x1", "y1", "x2", "y2")},
                })
                logger.info("strip_id=%s dims=%dx%d (wxh)", strip_id, strip.shape[1], strip.shape[0])

                if save_strips:
                    fname = output_path / f"{strip_id}.png"
                    cv2.imwrite(str(fname), strip)

    if manifest_path is not None:
        Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
        Path(manifest_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _report(voice_sequences)
    return voice_sequences

def _classical_boxes(image_bgr: np.ndarray) -> tuple[list[dict], list[StaffCurve]]:
    """Finds staves by line tracking and returns one full-width box per staff.

    Why classical: it has no training distribution, so it cannot share YOLO's
    font/domain gap, and it gives an independent staff count on tilted pages.

    Args:
        image_bgr: Preprocessed page (Stage 1 output).

    Returns:
        (boxes sorted top-to-bottom, matching curves).
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, BINARY_THRESHOLD, 255, cv2.THRESH_BINARY)
    curves = track_staff_curves(binary)
    img_h, img_w = binary.shape
    boxes: list[dict] = []
    for c in curves:
        spacing = float(np.median(c.spacing_at(np.linspace(c.x_min, c.x_max, 32))))
        half = CLASSICAL_BOX_HALF_SPACINGS * spacing
        cy = c.mean_center
        boxes.append({
            "x1": 0, "x2": img_w,
            "y1": max(0, int(round(cy - half))), "y2": min(img_h, int(round(cy + half))),
            "cy": cy, "conf": 1.0, "source": "classical", "spacing": spacing,
        })
    return boxes, curves


def _reconcile_with_classical(boxes: list, image_bgr: np.ndarray, page_index: int) -> list:
    """Keeps YOLO's boxes when the classical tracker agrees; otherwise repairs them.

    Agreement means the same count and every YOLO center within
    MATCH_MAX_CENTER_SPACINGS of its curve, so clean pages keep YOLO's exact
    output (no regression). On disagreement the classical boxes replace YOLO's
    (fills missed staves, drops spurious/duplicate ones) but only if they form a
    valid open-score layout; otherwise YOLO's result is returned and the caller's
    divisible-by-4 validation still applies (PIYA-105 #4).
    """
    classical, _ = _classical_boxes(image_bgr)
    n_c, n_y = len(classical), len(boxes)
    if n_c == 0 or n_c > MAX_BOXES_PER_PAGE:
        return boxes
    if n_c == n_y and all(
        abs(y["cy"] - c["cy"]) <= MATCH_MAX_CENTER_SPACINGS * c["spacing"]
        for y, c in zip(boxes, classical)
    ):
        return boxes
    if n_c % STAFFS_PER_SYSTEM != 0:
        logger.warning(
            "page=%d yolo=%d classical=%d source=yolo reason=classical_count_not_divisible_by_%d",
            page_index, n_y, n_c, STAFFS_PER_SYSTEM)
        print(f"[Stage 2] page {page_index}: classical count {n_c} not divisible by "
              f"{STAFFS_PER_SYSTEM}; keeping YOLO's {n_y}.")
        return boxes
    # Loud on purpose: the tracker has no confidence output and was tuned on 7 photos, so any
    # override must be traceable to a page (strip manifests carry source="classical").
    logger.warning("page=%d yolo=%d classical=%d source=classical (tracker overrides YOLO)",
                   page_index, n_y, n_c)
    print(f"[Stage 2] page {page_index}: YOLO found {n_y}, line tracker found {n_c} "
          f"-> using line-tracked staves.")
    return classical


def _remove_duplicates(boxes: list, min_cy_gap: int = 30) -> list:
    """
    If two boxes have vertical centers within min_cy_gap pixels,
    they're on the same staff — keep only the higher confidence one.
    """
    if not boxes:
        return boxes
    filtered = [boxes[0]]
    for box in boxes[1:]:
        if box["cy"] - filtered[-1]["cy"] > min_cy_gap:
            filtered.append(box)
        else:
            # Same staff — keep higher confidence
            if box["conf"] > filtered[-1]["conf"]:
                filtered[-1] = box
    return filtered



def _draw_and_save_viz(image_bgr, boxes, page_index, output_path,
                        box_color=(0, 0, 255), box_thickness=2, font_scale=0.6):
    """Draws boxes on a copy of the image and saves it. No YOLO call."""
    canvas = image_bgr.copy()
    systems = [boxes[i:i+4] for i in range(0, len(boxes), 4)]

    for sys_idx, system in enumerate(systems, start=1):
        for v_idx, box in enumerate(system, start=1):
            voice = VOICE_MAP.get(v_idx, f"Voice_{v_idx}")
            src = box.get("source", "yolo")
            label = f"S{sys_idx} {voice} ({src} {box['conf']:.2f})"
            cv2.rectangle(canvas, (box["x1"], box["y1"]),
                          (box["x2"], box["y2"]), box_color, box_thickness)
            (tw, th), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
            label_y = max(box["y1"] - 4, th + 4)
            cv2.rectangle(canvas,
                          (box["x1"], label_y - th - baseline - 2),
                          (box["x1"] + tw + 4, label_y + baseline - 2),
                          box_color, cv2.FILLED)
            cv2.putText(canvas, label, (box["x1"] + 2, label_y - baseline),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                        (255, 255, 255), 1, cv2.LINE_AA)

    fname = output_path / f"page{page_index:03d}_detections.png"
    cv2.imwrite(str(fname), canvas)
    print(f"[Viz] Page {page_index}: {len(boxes)} box(es) drawn -> {fname.name}")

# ── Training helpers ──────────────────────────────────────────────────────────

def train_yolov8(
    data_yaml: str,
    base_weights: str = "yolov8n.pt",
    epochs: int = 50,
    img_size: int = 640,
    batch: int = 8,
    project: str = "runs/train",
    name: str = "piyanota_staff_detector",
    degrees: float = 0.0,
    perspective: float = 0.0,
    shear: float = 0.0,
    fliplr: float = 0.5,
):
    """
    Fine-tunes YOLOv8 on annotated staff region data.

    Args:
        data_yaml:    Path to dataset YAML (see data/dataset.yaml template).
        base_weights: Starting weights — 'yolov8n.pt' for pretrained backbone.
        epochs:       Training epochs (50 is good for a first run).
        img_size:     Input resolution (640 recommended).
        project:      Output directory for training runs.
        name:         Run name (subfolder under project/).
        degrees:      Rotation augmentation range in degrees (+/-). Defaults to
            Ultralytics' library default (0.0 — no rotation augmentation).
        perspective:  Perspective-warp augmentation fraction. Defaults to
            Ultralytics' library default (0.0 — no perspective augmentation).
            Ultralytics' own docs describe ~0-0.001 as the sane range; values
            above that destabilize box regression.
        shear:        Shear augmentation range in degrees (+/-). Defaults to
            Ultralytics' library default (0.0 — no shear augmentation).
        fliplr:       Horizontal-flip augmentation probability. Defaults to
            Ultralytics' library default (0.5).

    Usage:
        python stage2_detection.py --train
    """
    model = YOLO(base_weights)
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=img_size,
        batch=batch,
        project=project,
        name=name,
        exist_ok=True,
        resume=False,
        amp=False,       # ← force disable AMP explicitly
        lr0=0.001,       # ← lower from default 0.01
        lrf=0.001,
        degrees=degrees,
        perspective=perspective,
        shear=shear,
        fliplr=fliplr,
        )
    print(f"\n[Training] Complete. Best weights saved to: "
          f"{project}/{name}/weights/best.pt")
    return results


def evaluate_model(weights: str, data_yaml: str):
    """Runs mAP evaluation on the test split."""
    model = YOLO(weights)
    metrics = model.val(data=data_yaml)
    print(f"\n[Eval] mAP50:    {metrics.box.map50:.4f}")
    print(f"[Eval] mAP50-95: {metrics.box.map:.4f}")
    return metrics


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_boxes(results) -> list:
    """Parses Ultralytics Results into a list of box dicts."""
    boxes = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            boxes.append({
                "x1": int(x1), "y1": int(y1),
                "x2": int(x2), "y2": int(y2),
                "cy": (y1 + y2) / 2,
                "conf": conf,
            })
    return boxes


# ── BUG-011 / fix/bug002-label-bleed: left-margin (voice-label) blanking ─────
# Two independent blanking techniques were tried and reverted here -- see
# docs/bug-tracker.md BUG-011 and the fix/bug002-label-bleed branch history.
# v1 (horizontal-continuity) clipped the clef on real samples; kernel/min-run
# ablation proved this wasn't tunable. v2 (vertical-extent/tall-ink opening)
# was geometrically correct -- verified to remove only the label text, never
# the clef -- but *reduced* real-pipeline clef accuracy (2/43 -> 0/43 on the
# 6-screenshot set, non-BUG-012 strips), including flipping two previously-
# correct predictions to wrong on pixel-verified-unchanged notation. Both
# ml-cv-lead and senior-reviewer recommended against merging either version;
# the label-bleed hypothesis for BUG-011's clef misreads is not supported by
# this evidence. Do not resurrect this approach without new evidence that
# label text is actually a causal factor (this session's ablation argues the
# opposite -- removing it made the model worse, not better).


# Content-adaptive strip extent. A fixed pad (0.5 x box height) matches CameraPrIMuS's
# ~50% staff/height ratio on average, but clips the treble clef, ledger-line notes and
# long stems on real photos. CameraPrIMuS crops follow the content extent, so we keep the
# fixed pad as the MINIMUM and grow outward to whatever is physically attached to the staff.
CROP_MIN_PAD = 0.5          # x box height, per side; the previous fixed padding
CROP_MAX_PAD = 1.5          # x box height, per side; bounds growth into neighbouring staves
CROP_X_SKIP_FRAC = 0.10     # ignore the left brace/bracket/voice label when scanning
CROP_LINE_KERNEL_HEIGHTS = 2.0  # x box height; horizontal opening this long removes staff lines
CROP_MIN_COMPONENT_PX = 6   # ignore specks so dust does not extend the crop
CROP_MAX_COMPONENT_HEIGHTS = 2.5  # x box height; taller than any real glyph (a treble clef
                                  # is ~2x) so it is a brace/bracket/barline spanning staves
CROP_EDGE_MARGIN_PX = 2     # breathing room beyond the outermost attached ink
CROP_LINE_REMOVAL_PAD_PX = 1    # extra rows removed above/below each staff line
CROP_STROKE_MIN_SPACINGS = 1.0  # vertical run (x line spacing) that counts as a stem/clef
                                # stroke rather than a staff line crossing it
CROP_STAFF_SPACINGS = 4.0   # a box spans 4 line spacings (5 lines)
CROP_SLIVER_MAX_WIDTH_PX = 4    # narrower than this AND taller than the staff = bracket sliver
CROP_SLIVER_MIN_HEIGHTS = 1.25  # x box height

# Lyric masking. The CRNN was trained on lyric-free strips, but the crop still contains
# neighbouring staves' lyrics/dynamics (they sit between staves). Everything that is not the
# staff or ink attached to it is blanked in the crop itself; cropping tighter cannot do this
# because lyrics can lie inside the rows that notes need.
BACKGROUND_VALUE = 255          # preprocessed pages are white-on-black-ink; blanked = white
# x line spacing; a component within this of the outer lines counts as touching the staff
# (JPEG/threshold jitter). 0.5 deleted triplet brackets.
MASK_ATTACH_TOL_SPACINGS = 0.75
MASK_LINE_BAND_SPACINGS = 0.3   # x line spacing; box edges may miss the true outer line by this much
MASK_HALO_PX = 1  # blank this far around removed ink so grey halos vanish
# Off-band opened runs at least this thick are beams, not a neighbour's staff lines (which
# measured 1-3 px at 6.75-9.5 px spacing).
MASK_BEAM_MIN_PX = 4
MASK_BEAM_MIN_SPACINGS = 0.4
# Ledger-line notes: a notehead centred on a short ledger line floats 1+ spacings off the
# staff, so it does not overlap the staff rows, yet it is content. It is told apart from
# text by shape: a compact glyph with ink on BOTH sides of one short horizontal line
# (a lyric extender/underscore has ink only above it).
LEDGER_MAX_REACH_SPACINGS = 3.5   # component's near edge is at most this far from the staff
LEDGER_RUN_MIN_SPACINGS = 1.2     # the ledger line is longer than a notehead...
LEDGER_RUN_MAX_SPACINGS = 3.0     # ...but far shorter than an extender line
LEDGER_MAX_HEIGHT_SPACINGS = 2.5  # notehead (+ledger) height; words with ascenders/descenders vary
LEDGER_MAX_WIDTH_SPACINGS = 3.5   # ledger note width; a lyric word + extender is wider
LEDGER_SIDE_MIN_SPACINGS = 0.25   # ink required above AND below the ledger row
LEDGER_THIN_ROW_FRAC = 0.8        # rows this close to the peak count as "the line"...
LEDGER_MAX_LINE_SPACINGS = 0.3    # ...and must be no thicker than this (letters like "o" are thicker)


def _staff_glyph_components(image: np.ndarray, box: dict, x_skip: int = 0):
    """Splits the ink around one staff into staff lines and connected glyph components.

    Shared by the crop-extent scan and the lyric mask so both agree on what is "attached".

    Returns:
        None if the analysis window is empty, else
        (win_top, ink, line_mask, labels, count, stats, staff_lines, strokes):
        ``ink``/``line_mask``/``staff_lines``/``strokes`` are 0/1
        masks over rows [win_top, ...) and columns [box.x1 + x_skip, box.x2); ``labels``/
        ``count``/``stats`` come from connectedComponentsWithStats on the line-removed glyph
        mask (staff lines removed, vertical strokes restored).
    """
    img_h, img_w = image.shape[:2]
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x1 = max(int(box["x1"]), 0) + x_skip
    x2 = min(int(box["x2"]), img_w)
    y1, y2 = int(box["y1"]), int(box["y2"])
    height = max(y2 - y1, 1)
    max_pad = int(height * CROP_MAX_PAD)

    win_top, win_bottom = max(0, y1 - max_pad), min(img_h, y2 + max_pad)
    ink = (gray[win_top:win_bottom, x1:x2] < BINARY_THRESHOLD).astype(np.uint8)
    if ink.size == 0:
        return None

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(int(height * CROP_LINE_KERNEL_HEIGHTS), 3), 1))
    staff_lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
    line_mask = cv2.dilate(
        staff_lines, np.ones((2 * CROP_LINE_REMOVAL_PAD_PX + 1, 1), np.uint8))
    # Removing a staff line also cuts every stem and the clef where they cross it. Vertically
    # long strokes are restored so their parts above/below the staff stay connected to the
    # staff, without a blind bridge that would also glue nearby dynamics/lyrics on.
    stroke_rows = max(int(height / CROP_STAFF_SPACINGS * CROP_STROKE_MIN_SPACINGS), 3)
    strokes = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((stroke_rows, 1), np.uint8))
    glyphs = (ink & (1 - line_mask)) | strokes

    count, labels, stats, _ = cv2.connectedComponentsWithStats(glyphs, connectivity=8)
    return win_top, ink, line_mask, labels, count, stats, staff_lines, strokes


def _content_extent(image: np.ndarray, box: dict,
                    limits: tuple[int, int] | None = None) -> tuple[int, int]:
    """Returns (y1, y2) of the strip crop, grown to include ink attached to the staff.

    Why: notes, stems, slurs and the clef routinely extend past a fixed margin. Staff
    lines are removed first because they touch every notehead and would otherwise chain
    the whole page into one component; what remains is noteheads, stems, clef, accidentals
    and slurs. Only components overlapping the staff's own rows count, so lyrics and
    dynamics (separate glyphs) and neighbouring staves do not stretch the crop. The result
    stays within [CROP_MIN_PAD, CROP_MAX_PAD] of the box.

    Args:
        limits: (upper, lower) page rows, normally the midpoints to the adjacent staves.
            Growth beyond the minimum pad stops there: barlines that span two staves are
            "attached" glyphs and would otherwise drag the next staff into the crop.
    """
    img_h = image.shape[0]
    x_skip = int((box["x2"] - box["x1"]) * CROP_X_SKIP_FRAC)
    y1, y2 = int(box["y1"]), int(box["y2"])
    height = max(y2 - y1, 1)
    min_pad, max_pad = int(height * CROP_MIN_PAD), int(height * CROP_MAX_PAD)

    analysis = _staff_glyph_components(image, box, x_skip)
    if analysis is None:
        return max(0, y1 - min_pad), min(img_h, y2 + min_pad)
    win_top, _, _, _, count, stats, _, _ = analysis

    box_top, box_bottom = y1 - win_top, y2 - win_top
    top, bottom = y1, y2
    for i in range(1, count):
        comp_top = stats[i, cv2.CC_STAT_TOP]
        comp_bottom = comp_top + stats[i, cv2.CC_STAT_HEIGHT]
        if stats[i, cv2.CC_STAT_AREA] < CROP_MIN_COMPONENT_PX:
            continue
        comp_h = stats[i, cv2.CC_STAT_HEIGHT]
        if comp_h > height * CROP_MAX_COMPONENT_HEIGHTS:
            continue  # system brace/bracket spanning staves, not this staff's own content
        if (stats[i, cv2.CC_STAT_WIDTH] <= CROP_SLIVER_MAX_WIDTH_PX
                and comp_h > height * CROP_SLIVER_MIN_HEIGHTS):
            continue  # slanted bracket sliver; real stems are shorter than the staff+
        if comp_bottom < box_top or comp_top > box_bottom:
            continue  # does not touch this staff's rows
        top = min(top, win_top + comp_top)
        bottom = max(bottom, win_top + comp_bottom)

    top = min(y1 - min_pad, top - CROP_EDGE_MARGIN_PX)
    bottom = max(y2 + min_pad, bottom + CROP_EDGE_MARGIN_PX)
    top, bottom = max(y1 - max_pad, top), min(y2 + max_pad, bottom)
    if limits is not None:
        # Never shrink below the old fixed pad, even on tightly spaced staves.
        top = max(top, min(limits[0], y1 - min_pad))
        bottom = min(bottom, max(limits[1], y2 + min_pad))
    return max(0, top), min(img_h, bottom)


def _looks_like_ledger_note(comp: np.ndarray, stat: np.ndarray, band_top: int,
                            band_bottom: int, spacing: float) -> bool:
    """True if a component near the staff is a notehead sitting on a ledger line.

    Args:
        comp: Bool mask (window-sized) of the component.
        stat: Its connectedComponentsWithStats row.
        band_top, band_bottom: Staff rows in window coordinates.
        spacing: Staff-line spacing in px.
    """
    top = int(stat[cv2.CC_STAT_TOP])
    bottom = top + int(stat[cv2.CC_STAT_HEIGHT])
    left = int(stat[cv2.CC_STAT_LEFT])
    right = left + int(stat[cv2.CC_STAT_WIDTH])
    gap = top - band_bottom if top > band_bottom else band_top - bottom
    if gap > LEDGER_MAX_REACH_SPACINGS * spacing:
        return False
    if (bottom - top > LEDGER_MAX_HEIGHT_SPACINGS * spacing
            or right - left > LEDGER_MAX_WIDTH_SPACINGS * spacing):
        return False
    rows = comp[top:bottom, left:right].sum(axis=1)
    line_row = int(rows.argmax())
    if not LEDGER_RUN_MIN_SPACINGS * spacing <= rows[line_row] <= LEDGER_RUN_MAX_SPACINGS * spacing:
        return False
    thickness = int((rows >= LEDGER_THIN_ROW_FRAC * rows[line_row]).sum())
    if thickness > max(2, LEDGER_MAX_LINE_SPACINGS * spacing):
        return False
    side = LEDGER_SIDE_MIN_SPACINGS * spacing
    return line_row >= side and (bottom - top - line_row) >= side


def _non_staff_ink_mask(image: np.ndarray, box: dict) -> tuple[int, int, np.ndarray]:
    """Finds ink around one staff that is neither the staff nor attached to it (lyrics etc.).

    "Attached" = a line-removed connected component (see _staff_glyph_components) whose rows
    overlap the staff's line rows (within MASK_ATTACH_TOL_SPACINGS): noteheads with stems,
    beams, clefs, accidentals, rests, barlines, ties and dynamics that touch the staff.
    Staff lines are kept only inside the staff's own row band, so a neighbouring staff's lines
    that fall inside the crop are blanked too. Thick off-band opened runs (beams) are kept as
    glyph ink; thin ones are treated as lines. Unlike the extent scan, over-tall components
    (barlines, brace) are kept whole: they are real ink of this staff and dropping them would
    change the strip content, not just remove text.

    Returns:
        (win_top, x_start, remove): ``remove`` is a bool mask over page rows
        [win_top, win_top + remove.shape[0]) and columns [x_start, x_start + remove.shape[1]).
    """
    x_start = max(int(box["x1"]), 0)
    analysis = _staff_glyph_components(image, box, 0)
    if analysis is None:
        return 0, x_start, np.zeros((0, 0), dtype=bool)
    win_top, ink, _, _, _, _, staff_lines, strokes = analysis
    y1, y2 = int(box["y1"]), int(box["y2"])
    height = max(y2 - y1, 1)

    # The detector's own box is the staff band. Deriving it from detected line rows instead
    # fails on tilted/curved staves, where the line-opening only finds fragments and the band
    # collapses, which then strips notes (seen on the sheared page-2 Alto strip).
    band_top, band_bottom = y1 - win_top, y2 - win_top
    spacing = height / CROP_STAFF_SPACINGS
    line_slack = int(round(spacing * MASK_LINE_BAND_SPACINGS))

    # Only the opening's hits INSIDE the staff band are staff lines. A long beam or tie outside
    # it also survives the line opening (it is longer than the kernel), and treating it as a
    # line would delete it; it must stay glyph ink so it can attach to its stems.
    in_band = np.zeros_like(ink, dtype=bool)
    in_band[max(band_top - line_slack, 0):band_bottom + line_slack + 1] = True
    line_pixels = (cv2.dilate(
        staff_lines, np.ones((2 * CROP_LINE_REMOVAL_PAD_PX + 1, 1), np.uint8)) > 0) & in_band
    # Off-band opened runs are either beams/ties (thick: keep) or a NEIGHBOUR's staff lines
    # (thin: must stay removed, or barlines spanning both staves chain the neighbour's whole
    # staff and its lyrics onto this one). Staff lines are <= 3 px on the camera photos.
    off_band = staff_lines.copy()
    off_band[in_band] = 0
    beam_rows = max(MASK_BEAM_MIN_PX, int(round(spacing * MASK_BEAM_MIN_SPACINGS)))
    beams = cv2.morphologyEx(off_band, cv2.MORPH_OPEN, np.ones((beam_rows, 1), np.uint8))
    all_lines = cv2.dilate(
        staff_lines, np.ones((2 * CROP_LINE_REMOVAL_PAD_PX + 1, 1), np.uint8)) > 0
    glyphs = ((ink > 0) & ~all_lines) | (strokes > 0) | (beams > 0)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        glyphs.astype(np.uint8), connectivity=8)

    tol = int(round(spacing * MASK_ATTACH_TOL_SPACINGS))

    tops = stats[:, cv2.CC_STAT_TOP]
    bottoms = tops + stats[:, cv2.CC_STAT_HEIGHT]
    # Any component touching the staff rows (within a small tolerance) is content: notes, stems
    # hanging below the staff, ties/slurs hugging it and staff-line fragments on tilted pages
    # all live there. Tried and rejected: demanding a minimum overlap to drop the "f"/"p" of
    # dynamics whose descender dips into the staff -- it also deleted down-stems of second-voice
    # notes and slurs. Dynamics that touch the staff therefore stay (known residual).
    attached = (bottoms >= band_top - tol) & (tops <= band_bottom + tol)
    attached[0] = False  # label 0 is background

    for i in np.nonzero(~attached)[0][1:]:
        attached[i] = _looks_like_ledger_note(
            labels == i, stats[i], band_top, band_bottom, spacing)

    keep = attached[labels]
    keep |= line_pixels  # the staff itself, including wobbly fringe pixels off the opened run
    keep &= ink > 0

    removed = (ink > 0) & ~keep
    halo = np.ones((2 * MASK_HALO_PX + 1,) * 2, np.uint8)
    remove = cv2.dilate(removed.astype(np.uint8), halo) > 0
    remove &= ~(cv2.dilate(keep.astype(np.uint8), halo) > 0)
    remove |= removed
    return win_top, x_start, remove


def _neighbor_limits(boxes: list, index: int, img_h: int) -> tuple[int, int]:
    """Returns the page rows halfway to the staves above and below boxes[index]."""
    box = boxes[index]
    upper = (boxes[index - 1]["y2"] + box["y1"]) // 2 if index > 0 else 0
    lower = (box["y2"] + boxes[index + 1]["y1"]) // 2 if index + 1 < len(boxes) else img_h
    return int(upper), int(lower)


def _crop_and_resize(image: np.ndarray, box: dict, target_height: int,
                     padding: float = CROP_MIN_PAD,
                     strip_id: str = "",
                     adaptive_extent: bool = True,
                     limits: tuple[int, int] | None = None,
                     mask_lyrics: bool = MASK_LYRICS_DEFAULT) -> np.ndarray:
    """Crops one staff to a full-width strip and resizes it to target_height.

    Args:
        padding: Minimum per-side padding as a fraction of box height.
        adaptive_extent: Grow the crop to the staff's attached content (see
            _content_extent). False restores the old fixed-padding crop.
        limits: Adjacent-staff midpoints bounding adaptive growth (see _content_extent).
        mask_lyrics: Blank ink that is not the staff or attached to it (see
            _non_staff_ink_mask). False reproduces the unmasked strips.
    """
    img_h, img_w = image.shape[:2]
    x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]

    if adaptive_extent:
        y1, y2 = _content_extent(image, box, limits)
    else:
        pad = int((y2 - y1) * padding)
        y1 = max(0, y1 - pad)
        y2 = min(img_h, y2 + pad)

    crop = image[y1:y2, max(0, x1):x2]

    if mask_lyrics and crop.size != 0:
        win_top, x_start, remove = _non_staff_ink_mask(image, box)
        sub = remove[y1 - win_top:y2 - win_top, max(0, x1) - x_start:x2 - x_start]
        # The analysis window is at most CROP_MAX_PAD from the box, the same bound as the crop,
        # so ``sub`` always covers the crop; a mismatch means the bound was broken upstream.
        if sub.shape != crop.shape[:2]:
            raise ValueError(f"lyric mask {sub.shape} does not cover crop {crop.shape[:2]}")
        crop = crop.copy()
        crop[sub] = BACKGROUND_VALUE

    if crop.size == 0:
        return np.zeros((target_height, target_height, 3), dtype=np.uint8)

    h, w = crop.shape[:2]
    new_w = int(w * (target_height / h))
    resized = cv2.resize(crop, (new_w, target_height), interpolation=cv2.INTER_AREA)
    return resized


def _report(voice_sequences: dict):
    print("\n[Stage 2] Voice strip counts:")
    for voice, strips in voice_sequences.items():
        print(f"  {voice}: {len(strips)} strip(s)")
    empty = [v for v, s in voice_sequences.items() if len(s) == 0]
    if empty:
        print(f"\n  WARNING: Missing voice(s): {empty}. "
              f"Check detection results or recapture.")
        

# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from stage1_preprocessing import preprocess_batch

    parser = argparse.ArgumentParser(description="PiyaNota Stage 2 — Staff Detection")
    parser.add_argument("--input",   default="data/raw",           help="Raw images dir")
    parser.add_argument("--prep",    default="data/preprocessed",  help="Preprocessed dir")
    parser.add_argument("--strips",  default="data/strips",        help="Output strips dir")
    parser.add_argument("--weights", default="staff_detector_files\\weights\\best.pt", help="YOLOv8 weights")
    parser.add_argument("--train",   action="store_true",          help="Run training instead")
    parser.add_argument("--data",    default="data/dataset.yaml",  help="Dataset YAML (for training)")
    parser.add_argument("--viz",     action="store_true",          help="Visualize detections with red boxes")
    args = parser.parse_args()

    if args.train:
        train_yolov8(data_yaml=args.data, base_weights=args.weights)
    else:
        pages = preprocess_batch(args.input, args.prep, save_debug=True)
        voices = detect_staff_regions(
            pages,
            model_weights=args.weights,
            output_dir=args.strips,
            save_viz=args.viz,        # ← one call does both
        )
        print("\nStage 2 complete. Strips ready for Stage 3 (CRNN-CTC).")
