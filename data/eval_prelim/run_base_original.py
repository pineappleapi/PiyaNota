"""Base model: the original PiyaNota pipeline (main-branch Stages 1-3, extracted unchanged into orig_code/)
with the original Camera-PrIMuS CRNN, camera and digital input.

Per page: preprocess_score_image -> detect_staff_regions (one page at a time, so a page Stage 2 rejects
fails alone) -> per strip transcribe_strip + infer_pitch, i.e. exactly what process_strip does, keeping the
tokens for SER. Output uses the fine-tuned driver's record layout (version "a" only; the original pipeline
has no clef/key classifier): runs/<condition>/<piece>/{stage12_base.json, stage3_base.json}.

Usage (repo root):  python data/eval_prelim/run_base_original.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # CPU: deterministic, and avoids the dev-GPU hang (BUG-013)

import torch  # noqa: E402

torch.cuda.is_available = lambda: False

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "orig_code"))  # the main-branch stage modules shadow the training-tree ones
sys.path.insert(0, str(HERE))

import cv2  # noqa: E402
import stage1_preprocessing as s1  # noqa: E402
import stage3_transcription as s3  # noqa: E402
from stage2_detection import detect_staff_regions  # noqa: E402

from inputs import conditions, page_path  # noqa: E402

assert Path(s1.__file__).parent == HERE / "orig_code", s1.__file__

OUT = HERE / "runs"
YOLO = Path("D:/PiyaNota/staff_detector_files/weights/best.pt")
BASE_CRNN = Path("D:/PiyaNota/music_symbol_detection/crnn_cameraprimus_transcription.pt")
IMG_HEIGHT = 64
OPENING_KEY = re.compile(r"opening key sig (\d+#|\d+b|C major)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_piece(work: Path, cond: str, piece: str, pages: list[int], model: Any, device: torch.device) -> None:
    if (work / "stage3_base.json").exists():
        return
    work.mkdir(parents=True, exist_ok=True)
    diags: list[dict[str, Any]] = []
    recs: list[dict[str, Any]] = []
    for p in pages:
        src = page_path(cond, piece, p)
        diag: dict[str, Any] = {"page": p, "photo": str(src)}
        log = io.StringIO()
        t0 = time.time()
        try:
            with contextlib.redirect_stdout(log):
                img, angle = s1.preprocess_score_image(str(src))
                vs = detect_staff_regions([(img, p)], model_weights=str(YOLO), save_strips=False,
                                          save_viz=True, viz_dir=str(work / "viz_base"))
        except (ValueError, RuntimeError, cv2.error) as exc:
            diag.update(failure=f"{type(exc).__name__}: {exc}", n_strips=0, seconds=time.time() - t0)
            (work / f"base_page{p:02d}_log.txt").write_text(log.getvalue() + "\n" + traceback.format_exc(),
                                                            encoding="utf-8")
            diags.append(diag)
            print(f"[prelim-base] {cond} {piece} p{p}: PIPELINE FAILURE {diag['failure']}", flush=True)
            continue
        (work / f"base_page{p:02d}_log.txt").write_text(log.getvalue(), encoding="utf-8")
        items = sorted((it for v in vs.values() for it in v), key=lambda it: (it[2], it[4]))
        diag.update(angle=float(angle), n_strips=len(items), seconds=time.time() - t0)
        diags.append(diag)
        if piece == "both_sides_now":
            recs += [dict(strip_id=f"page{pi:03d}_sys{si:02d}_{vl}_vidx{vi}", page=pi, system=si, voice=vl,
                          v_idx=vi) for _, pi, si, vl, vi in items]
            print(f"[prelim-base] {cond} {piece} p{p}: {len(items)} strips", flush=True)
            continue
        for strip, pi, si, vl, vi in items:
            sid = f"page{pi:03d}_sys{si:02d}_{vl}_vidx{vi}"
            slog = io.StringIO()
            with contextlib.redirect_stdout(slog), torch.no_grad():
                toks = s3.transcribe_strip(strip, model, device, IMG_HEIGHT, strip_id=sid)
                ev = s3.infer_pitch(toks, voice=vl, page_index=pi, sys_idx=si)
            key_m = OPENING_KEY.search(slog.getvalue())
            recs.append(dict(strip_id=sid, page=pi, system=si, voice=vl, v_idx=vi, tokens=toks, repro_ok=True,
                             a=dict(events=ev, opening_key=key_m[1] if key_m else None,
                                    first_clef=next((t for t in toks if t.startswith("clef.")), None)),
                             b=None))
        print(f"[prelim-base] {cond} {piece} p{p}: {len(items)} strips", flush=True)
    (work / "stage12_base.json").write_text(json.dumps({"pages": diags, "strips": [
        {k: r[k] for k in ("strip_id", "page", "system", "voice", "v_idx")} for r in recs]}, indent=1),
        encoding="utf-8")
    (work / "stage3_base.json").write_text(json.dumps(recs, indent=1), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    model, device = s3.load_model(str(BASE_CRNN), torch.device("cpu"))
    meta = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "torch": torch.__version__,
            "main_commit": (HERE / "orig_code" / "MAIN_COMMIT.txt").read_text().strip(),
            "hashes": {f.name: sha256(f) for f in sorted((HERE / "orig_code").glob("*.py"))},
            "crnn": sha256(BASE_CRNN), "yolo": sha256(YOLO)}
    (OUT / "run_meta_base.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    for cond, piece, pages in conditions():
        run_piece(OUT / cond / piece, cond, piece, pages, model, device)


if __name__ == "__main__":
    main()
