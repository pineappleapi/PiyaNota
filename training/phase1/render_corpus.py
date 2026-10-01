"""Phase 1 step 3: render each corpus MEI with Verovio in every bundled SMuFL font, label it, check it (PIYA-106).

Per (piece, font) this writes, under <out>/renders/<font>/<piece_id>/ (or <out>/quarantine/... on failure):
* page_<p>.svg and page_<p>.png (resvg; this machine has no cairo) - the page as drawn;
* labels.json - one agnostic token list per (page, system, voice), from `music_to_agnostic` (dialect "verovio"),
  following the DRAWN clef (the tenor is labelled clef.G-L2 on its treble-8vb staff; Stage 3 adds the octave);
* check.json - the automatic SVG check (`svg_check.py`); a render with any mismatch is quarantined, not deleted;
* the vocabulary guard (`vocab_guard.py`): each labels.json row carries `quarantine` ("oov:<token>" when its label
  holds a token the CRNN cannot output, else None); only that strip is unusable, the render stays in renders/;
* meta.json - provenance: converter sha256, git HEAD and whether the converter differs from it, Verovio version,
  font, options, measure -> system -> page map, staff boxes in PNG pixels (for cutting G1b strips).

No strip cutting and no camera augmentation here: those come after the SVG check and G1b pass (plan, Phase 1).

Usage: python training/phase1/render_corpus.py --out D:/PiyaNota-training/data/phase1_renders
           [--fonts-per-piece N] [--composers bach,palestrina] [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import gc
import hashlib
import json
import random
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import resvg_py
import verovio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from music_to_agnostic import ConversionError, convert_staff, split_systems  # noqa: E402
from svg_check import compare, index_mei, label_view, read_page  # noqa: E402
from vocab_guard import apply_guard  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CONVERTER = REPO / "training" / "music_to_agnostic.py"
FONTS: tuple[str, ...] = ("Leipzig", "Bravura", "Gootville", "Leland", "Petaluma")
VOICES: tuple[str, ...] = ("Soprano", "Alto", "Tenor", "Bass")
PAGE_WIDTH = 2100             # Verovio page units (A4 proportions)
PAGE_HEIGHT = 2970
SCALES: tuple[int, ...] = (45, 50, 55)   # staff height about 6-7.5 mm on the A4 page, like printed octavos
PNG_WIDTH_PX = 2480           # A4 at 300 dpi
BASE_OPTIONS: dict[str, object] = {
    "breaks": "encoded", "pageWidth": PAGE_WIDTH, "pageHeight": PAGE_HEIGHT, "adjustPageHeight": True,
    "footer": "none", "header": "auto", "svgHtml5": True, "svgAdditionalAttribute": ["staff@n"],
}


def provenance() -> dict[str, object]:
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", str(CONVERTER)],
                           capture_output=True, text=True, check=True)
    return {
        "converter_sha256": hashlib.sha256(CONVERTER.read_bytes()).hexdigest(),
        "git_head": head.stdout.strip(),
        "converter_uncommitted_changes": bool(dirty.stdout.strip()),
        "verovio_version": verovio.toolkit().getVersion(),
    }


def labels_for(mei_path: Path) -> list[list[list[str]]]:
    """labels[staff_index][system] -> tokens."""
    return [split_systems(convert_staff(mei_path, str(s), dialect="verovio")) for s in range(1, 5)]


def render_one(mei_path: Path, plan: dict[str, object], font: str, scale: int, out_dir: Path,
               prov: dict[str, object]) -> dict[str, object]:
    """Render, label and check one (piece, font). Returns the check summary; writes everything to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    options = {**BASE_OPTIONS, "font": font, "scale": scale}
    tk = verovio.toolkit()
    tk.setOptions(options)
    if not tk.loadData(mei_path.read_text(encoding="utf-8")):
        raise ValueError("verovio could not load the MEI")
    svgs: list[str] = []
    for p in range(1, tk.getPageCount() + 1):
        svg = tk.renderToSVG(p)
        (out_dir / f"page_{p}.svg").write_text(svg, encoding="utf-8")
        png = resvg_py.svg_to_bytes(svg_string=svg, width=PNG_WIDTH_PX, background="white")
        (out_dir / f"page_{p}.png").write_bytes(bytes(png))
        svgs.append(svg)
    return check_render(mei_path, plan, options, svgs, out_dir, prov)


def check_render(mei_path: Path, plan: dict[str, object], options: dict[str, object], svgs: list[str],
                 out_dir: Path, prov: dict[str, object]) -> dict[str, object]:
    """Label the drawn pages, run the SVG check and the vocabulary guard, and write labels/check/meta.

    Split from `render_one` so `recheck_renders.py` can re-check existing SVGs against the current converter and
    check without paying for Verovio again. Raises ValueError when an SVG id is not in the MEI (stale render).
    """
    labels = labels_for(mei_path)
    mei = index_mei(mei_path)
    plan_systems: list[list[int]] = plan["systems"]  # type: ignore[assignment]
    failures: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    boxes_px: list[dict[str, object]] = []
    global_sys = 0
    pages = len(svgs)
    if pages != len(plan["pages"]):  # type: ignore[arg-type]
        failures.append({"page": None, "system": None, "staff": None,
                         "diff": [f"pages: drawn {pages} planned {len(plan['pages'])}"]})  # type: ignore[arg-type]
    for p, svg in enumerate(svgs, start=1):
        systems, geom = read_page(svg, mei)
        px = PNG_WIDTH_PX / geom.width_px * geom.scale
        for s_on_page, drawn in enumerate(systems):
            g = global_sys
            global_sys += 1
            if g >= len(plan_systems):
                failures.append({"page": p, "system": g, "staff": None, "diff": ["system beyond the plan"]})
                continue
            expected_ids = [mei.measure_ids[i] for i in plan_systems[g]]
            if drawn.measure_ids != expected_ids:
                failures.append({"page": p, "system": g, "staff": None,
                                 "diff": [f"measures: drawn {drawn.measure_ids} planned {expected_ids}"]})
            for s in range(1, 5):
                n = str(s)
                tokens = labels[s - 1][g] if g < len(labels[s - 1]) else []
                label_rows.append({"page": p, "system": g, "system_on_page": s_on_page, "voice": VOICES[s - 1],
                                   "staff_n": n, "measures": plan_systems[g], "tokens": tokens})
                if n not in drawn.staves:
                    failures.append({"page": p, "system": g, "staff": n, "diff": ["staff not drawn"]})
                    continue
                diff = compare(drawn.staves[n], label_view(tokens))
                if diff:
                    failures.append({"page": p, "system": g, "staff": n, "diff": diff})
                box = drawn.boxes[n]
                boxes_px.append({"page": p, "system": g, "staff_n": n,
                                 "top": (box.top + geom.margin_y) * px, "bottom": (box.bottom + geom.margin_y) * px,
                                 "left": (box.left + geom.margin_x) * px,
                                 "right": (box.right + geom.margin_x) * px})
    if global_sys != len(plan_systems):
        failures.append({"page": None, "system": None, "staff": None,
                         "diff": [f"systems: drawn {global_sys} planned {len(plan_systems)}"]})
    passed = not failures
    oov_counts = apply_guard(label_rows)
    oov_strips = [{"page": r["page"], "system": r["system"], "staff_n": r["staff_n"], "reason": r["quarantine"]}
                  for r in label_rows if r["quarantine"]]
    (out_dir / "labels.json").write_text(json.dumps(label_rows, indent=0), encoding="utf-8")
    (out_dir / "check.json").write_text(json.dumps({"pass": passed, "failures": failures}, indent=1),
                                        encoding="utf-8")
    meta = {**prov, "piece_id": plan["piece_id"], "source": plan["source"], "font": options["font"],
            "options": options, "png_width_px": PNG_WIDTH_PX, "pages": pages, "systems": plan_systems,
            "page_systems": plan["pages"], "measure_n": plan["measure_n"],
            "constructed": {k: plan[k] for k in ("key_change", "meter_change", "multirest")},
            "staff_boxes_px": boxes_px, "check_pass": passed,
            "strips": len(label_rows), "oov_strips": oov_strips, "oov_token_counts": dict(oov_counts)}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return {"pass": passed, "failures": failures, "strips": len(label_rows), "oov_strips": len(oov_strips),
            "oov_token_counts": dict(oov_counts)}


def oov_summary(results: list[dict[str, object]]) -> dict[str, object]:
    """Usable vs OOV-quarantined strips per font among passed renders, and OOV token counts."""
    per_font: dict[str, dict[str, int]] = {}
    tokens: collections.Counter[str] = collections.Counter()
    for r in results:
        if not r["pass"] or r.get("skipped_existing"):
            continue
        f = per_font.setdefault(str(r["font"]), {"strips": 0, "oov_strips": 0})
        f["strips"] += int(r.get("strips", 0))  # type: ignore[arg-type]
        f["oov_strips"] += int(r.get("oov_strips", 0))  # type: ignore[arg-type]
        tokens.update(r.get("oov_token_counts", {}))  # type: ignore[arg-type]
    return {"per_font": per_font, "token_counts": dict(tokens)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--composers", default="bach,palestrina")
    parser.add_argument("--fonts-per-piece", type=int, default=len(FONTS),
                        help="fonts per piece, rotated so every font is used equally (default all 5)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0,
                        help="first plan index per composer; with --limit this renders one chunk, so a killed run "
                             "loses at most that chunk")
    parser.add_argument("--skip-existing", action="store_true",
                        help="keep (piece, font) renders that already passed instead of re-rendering them")
    parser.add_argument("--summary-name", default="render_summary.json")
    args = parser.parse_args()
    prov = provenance()
    corpus = args.out / "corpus"
    results: list[dict[str, object]] = []
    patterns: collections.Counter[str] = collections.Counter()
    t0 = time.time()
    for composer in args.composers.split(","):
        all_plans = sorted(corpus.glob(f"{composer}_*.plan.json"))
        end = args.start + args.limit if args.limit else len(all_plans)
        # The font rotation uses the index in the full sorted list, so chunked runs rotate like one long run.
        for i, plan_path in list(enumerate(all_plans))[args.start:end]:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            mei_path = corpus / f"{plan['piece_id']}.mei"
            rng = random.Random(f"phase1-render:{plan['piece_id']}")
            start = i % len(FONTS)
            fonts = [FONTS[(start + k) % len(FONTS)] for k in range(args.fonts_per_piece)]
            for font in fonts:
                scale = rng.choice(SCALES)
                ok_dir = args.out / "renders" / font / plan["piece_id"]
                bad_dir = args.out / "quarantine" / font / plan["piece_id"]
                if args.skip_existing and (ok_dir / "check.json").exists():
                    if json.loads((ok_dir / "check.json").read_text(encoding="utf-8"))["pass"]:
                        results.append({"piece_id": plan["piece_id"], "composer": composer, "font": font,
                                        "scale": scale, "pass": True, "n_failures": 0, "skipped_existing": True})
                        continue
                for d in (ok_dir, bad_dir):
                    if d.exists():
                        shutil.rmtree(d)
                try:
                    res = render_one(mei_path, plan, font, scale, ok_dir, prov)
                except (ConversionError, ValueError, KeyError) as exc:
                    res = {"pass": False, "failures": [{"diff": [f"render error: {exc}"]}]}
                    ok_dir.mkdir(parents=True, exist_ok=True)
                    (ok_dir / "check.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
                if not res["pass"]:
                    bad_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(ok_dir), str(bad_dir))
                    for f in res["failures"]:
                        for d in f["diff"]:
                            patterns[d.split(":")[0]] += 1
                results.append({"piece_id": plan["piece_id"], "composer": composer, "font": font, "scale": scale,
                                "pass": res["pass"], "n_failures": len(res["failures"]),
                                "strips": res.get("strips", 0), "oov_strips": res.get("oov_strips", 0),
                                "oov_token_counts": res.get("oov_token_counts", {})})
                del res
                gc.collect()   # a Verovio toolkit holds the whole laid-out score; free it before the next font
            if i % 10 == 0:
                done = sum(1 for r in results if r["pass"])
                print(f"{composer} {i}/{len(all_plans)} {time.time() - t0:.0f}s pass {done}/{len(results)}", flush=True)
    summary = {**prov, "renders": len(results), "passed": sum(1 for r in results if r["pass"]),
               "per_font": {f: {"renders": sum(1 for r in results if r["font"] == f),
                                "passed": sum(1 for r in results if r["font"] == f and r["pass"])} for f in FONTS},
               "failure_fields": dict(patterns), "oov": oov_summary(results), "results": results}
    (args.out / args.summary_name).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=1))


if __name__ == "__main__":
    main()
