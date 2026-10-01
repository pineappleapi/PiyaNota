"""Fine-tuned CRNN (seed1, seed2) through the training-tree Stages 1-3, camera and digital input.

Reuses data/eval_fresh/run_eval.py unchanged (same Stage 1/2 calls, same (a)/(b) Stage 3 and the same
process_strip reproduction check); only the page source and output folder differ.
Output: runs/<condition>/<piece>/{stage12.json, stage3_seed1.json, stage3_seed2.json}.

Usage (repo root):  python data/eval_prelim/run_finetuned.py
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "eval_fresh"))
sys.path.insert(0, str(HERE))

import cv2  # noqa: E402
import torch  # noqa: E402

import run_eval as rf  # noqa: E402  (sets CPU-only before torch use)
from inputs import conditions, page_path  # noqa: E402

OUT = HERE / "runs"
SEEDS = ["seed1", "seed2"]


def phase1(work: Path, cond: str, piece: str, pages: list[int], ckm: Any) -> dict[str, Any]:
    """Same steps as run_eval.phase1, with the page file taken from inputs.page_path."""
    cache = work / "stage12.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    (work / "strips").mkdir(parents=True, exist_ok=True)
    diags: list[dict[str, Any]] = []
    strips: list[dict[str, Any]] = []
    readings: list[dict[str, Any]] = []
    for p in pages:
        src = page_path(cond, piece, p)
        diag: dict[str, Any] = {"page": p, "photo": str(src)}
        log = io.StringIO()
        t0 = time.time()
        try:
            with contextlib.redirect_stdout(log):
                page = rf.s1.preprocess_score_page(str(src), keep_unmasked=True)
                manifest_path = work / f"page{p:02d}_manifest.json"
                vs = rf.detect_staff_regions([(page.detect, p, page.strip_source, page)], model_weights=str(rf.YOLO),
                                             output_dir=str(work / "stage2_strips"), save_strips=False,
                                             save_viz=True, viz_dir=str(work / "viz"),
                                             manifest_path=str(manifest_path))
        except (ValueError, RuntimeError, cv2.error) as exc:
            diag.update(failure=f"{type(exc).__name__}: {exc}", n_strips=0, seconds=time.time() - t0)
            (work / f"page{p:02d}_log.txt").write_text(log.getvalue() + "\n" + traceback.format_exc(),
                                                       encoding="utf-8")
            diags.append(diag)
            print(f"[prelim-ft] {cond} {piece} p{p}: PIPELINE FAILURE {diag['failure']}", flush=True)
            continue
        (work / f"page{p:02d}_log.txt").write_text(log.getvalue(), encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        diag.update(angle=float(page.angle), mask_applied=bool(page.mask_applied), n_strips=len(manifest),
                    seconds=time.time() - t0)
        for voice, items in vs.items():
            for strip, page_index, sys_idx, voice_label, v_idx in items:
                sid = f"page{page_index:03d}_sys{sys_idx:02d}_{voice_label}_vidx{v_idx}"
                png = work / "strips" / f"{sid}.png"
                cv2.imwrite(str(png), strip)
                strips.append(dict(strip_id=sid, page=page_index, system=sys_idx, voice=voice_label, v_idx=v_idx,
                                   png=str(png.relative_to(rf.OUT))))
        with torch.no_grad():
            readings += [r.__dict__ for r in rf.s3b.classify_page(page, manifest, ckm)]
        diags.append(diag)
        print(f"[prelim-ft] {cond} {piece} p{p}: {len(manifest)} strips", flush=True)
    data = {"pages": diags, "strips": sorted(strips, key=lambda s: (s["page"], s["system"], s["v_idx"])),
            "readings": readings}
    cache.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ckm = rf.s3b.load_clef_key_model(rf.ROOT / rf.s3b.DEFAULT_CLEF_KEY_CHECKPOINT)
    meta = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "torch": torch.__version__,
            "hashes": {f: rf.sha256(rf.ROOT / f) for f in ["stage1_preprocessing.py", "stage2_detection.py",
                                                          "stage3_transcription.py", "stage3_clefkey.py",
                                                          "clef_key_core.py", "clef_voice_rules.py"]},
            "crnn": {k: rf.sha256(rf.CRNNS[k]) for k in SEEDS}, "yolo": rf.sha256(rf.YOLO)}
    (OUT / "run_meta_finetuned.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    for cond, piece, pages in conditions():
        # run_eval.phase2 resolves strip PNGs and writes output relative to its module-level OUT.
        rf.OUT = OUT / cond
        work = rf.OUT / piece
        st12 = phase1(work, cond, piece, pages, ckm)
        if piece == "both_sides_now":
            continue  # staff-count GT only: no Stage 3 scoring possible
        for seed in SEEDS:
            if not (work / f"stage3_{seed}.json").exists():
                rf.phase2(piece, st12, seed, ckm)


if __name__ == "__main__":
    main()
