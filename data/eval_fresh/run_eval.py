"""Fresh-photo evaluation driver (pre-registered in PREREG.md). Blind to the ground truth.

Phase 1 (once per piece, cached): Stage 1 + Stage 2 page by page with the training-tree stage files, and
ClefKeyNet readings on each Stage 2 strip. Phase 2 (per CRNN): one CRNN decode per strip, fed to both
Stage 3 versions: (a) stage3_transcription.infer_pitch as-is, (b) stage3_clefkey.infer_pitch_b.

Usage (from the repo root):  python data/eval_fresh/run_eval.py
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

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # CPU: deterministic decode, same numbers on every rerun

import cv2
import torch

torch.cuda.is_available = lambda: False  # stage modules pick their device from this
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import stage1_preprocessing as s1  # noqa: E402
import stage3_clefkey as s3b  # noqa: E402
import stage3_transcription as s3  # noqa: E402
from stage2_detection import detect_staff_regions  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "runs"
PHOTOS = Path("D:/PiyaNota/data/piyanota_dataset")
YOLO = Path("D:/PiyaNota/staff_detector_files/weights/best.pt")
CRNNS = {
    "seed1": Path("D:/PiyaNota/music_symbol_detection/finetuned_font_seed1.pt"),
    "seed2": Path("D:/PiyaNota/music_symbol_detection/finetuned_font_seed2.pt"),
    "baseline": Path("D:/PiyaNota/music_symbol_detection/crnn_cameraprimus_transcription.pt"),
}
PIECES = {"non_nobis_domine": 4, "honneur_a_toi": 3, "gaano_ko_ikaw_kamahal": 9, "handog": 14}
IMG_HEIGHT = 64
OPENING_KEY = re.compile(r"opening key sig (\d+#|\d+b|C major)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase1(piece: str, n_pages: int, ckm: s3b.ClefKeyModel) -> dict[str, Any]:
    """Stage 1 + 2 + classifier readings for one piece; cached in runs/<piece>/stage12.json."""
    work = OUT / piece
    cache = work / "stage12.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    (work / "strips").mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    strips: list[dict[str, Any]] = []
    readings: list[dict[str, Any]] = []
    for p in range(1, n_pages + 1):
        photo = PHOTOS / f"{piece}_pg{p:02d}.jpg"
        diag: dict[str, Any] = {"page": p, "photo": photo.name}
        log = io.StringIO()
        try:
            with contextlib.redirect_stdout(log):
                page = s1.preprocess_score_page(str(photo), keep_unmasked=True)
                manifest_path = work / f"page{p:02d}_manifest.json"
                vs = detect_staff_regions([(page.detect, p, page.strip_source)], model_weights=str(YOLO),
                                          output_dir=str(work / "stage2_strips"), save_strips=False, save_viz=True,
                                          viz_dir=str(work / "viz"), manifest_path=str(manifest_path))
        except (ValueError, RuntimeError, cv2.error) as exc:
            diag["failure"] = f"{type(exc).__name__}: {exc}"
            diag["n_strips"] = 0
            (work / f"page{p:02d}_log.txt").write_text(log.getvalue() + "\n" + traceback.format_exc(), encoding="utf-8")
            pages.append(diag)
            print(f"[eval] {piece} p{p}: PIPELINE FAILURE {diag['failure']}")
            continue
        (work / f"page{p:02d}_log.txt").write_text(log.getvalue(), encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        diag.update(angle=float(page.angle), mask_applied=bool(page.mask_applied), n_strips=len(manifest))
        for voice, items in vs.items():
            for strip, page_index, sys_idx, voice_label, v_idx in items:
                sid = f"page{page_index:03d}_sys{sys_idx:02d}_{voice_label}_vidx{v_idx}"
                png = work / "strips" / f"{sid}.png"
                cv2.imwrite(str(png), strip)
                strips.append(dict(strip_id=sid, page=page_index, system=sys_idx, voice=voice_label, v_idx=v_idx,
                                   png=str(png.relative_to(OUT))))
        with torch.no_grad():
            readings += [r.__dict__ for r in s3b.classify_page(page, manifest, ckm)]
        pages.append(diag)
        print(f"[eval] {piece} p{p}: {len(manifest)} strips, angle {page.angle:.2f}")
    data = {"pages": pages, "strips": sorted(strips, key=lambda s: (s["page"], s["system"], s["v_idx"])),
            "readings": readings}
    cache.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def phase2(piece: str, st12: dict[str, Any], crnn: str, ckm: s3b.ClefKeyModel) -> None:
    """Stage 3 (a) and (b) for one piece and CRNN -> runs/<piece>/stage3_<crnn>.json."""
    model, device = s3.load_model(str(CRNNS[crnn]), torch.device("cpu"))
    decisions = s3b.decide([s3b.ClefKeyReading(**r) for r in st12["readings"]], ckm)
    out: list[dict[str, Any]] = []
    n_repro_fail = 0
    for st in st12["strips"]:
        img = cv2.imread(str(OUT / st["png"]), cv2.IMREAD_UNCHANGED)
        scored = s3.transcribe_strip(img, model, device, IMG_HEIGHT, return_confidence=True, strip_id=st["strip_id"])
        toks, confs = [t for t, _ in scored], [float(c) for _, c in scored]
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            ev_a = s3.infer_pitch(toks, voice=st["voice"], page_index=st["page"], sys_idx=st["system"],
                                  confidences=confs)
            ev_ref = s3.process_strip(img, st["voice"], st["page"], model, device, IMG_HEIGHT, v_idx=st["v_idx"],
                                      viz_dir=None, sys_idx=st["system"], strip_id=st["strip_id"])
        repro_ok = json.dumps(ev_a, sort_keys=True) == json.dumps(ev_ref, sort_keys=True)
        n_repro_fail += not repro_ok
        key_m = OPENING_KEY.search(log.getvalue())
        rec: dict[str, Any] = dict(st, tokens=toks, confs=confs, repro_ok=repro_ok,
                                   a=dict(events=ev_a, opening_key=key_m[1] if key_m else None,
                                          first_clef=next((t for t in toks if t.startswith("clef.")), None),
                                          log=log.getvalue()))
        dec = decisions.get(st["strip_id"])
        if dec is None:
            rec["b"] = None  # no reading: cannot happen when classify_page saw the same manifest
        else:
            ev_b, toks_b, info = s3b.infer_pitch_b(toks, confs, st["voice"], st["page"], st["system"], dec)
            rec["b"] = dict(events=ev_b, tokens=toks_b, info=info)
        out.append(rec)
    path = OUT / piece / f"stage3_{crnn}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"[eval] {piece} {crnn}: {len(out)} strips, reproduction failures {n_repro_fail}")
    if n_repro_fail:
        raise RuntimeError(f"{piece} {crnn}: (a) events differ from process_strip on {n_repro_fail} strips")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ckm = s3b.load_clef_key_model(ROOT / s3b.DEFAULT_CLEF_KEY_CHECKPOINT)
    meta = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "torch": torch.__version__,
            "hashes": {f: sha256(ROOT / f) for f in ["stage1_preprocessing.py", "stage2_detection.py",
                                                    "stage3_transcription.py", "stage3_clefkey.py",
                                                    "clef_key_core.py", "clef_voice_rules.py"]},
            "crnn": {k: sha256(v) for k, v in CRNNS.items()}, "yolo": sha256(YOLO),
            "clef_key_ckpt": sha256(ROOT / s3b.DEFAULT_CLEF_KEY_CHECKPOINT),
            "clef_key_thresholds": {"clef": ckm.clef_threshold, "key": ckm.key_threshold,
                                    "g8vb_reliable": ckm.g8vb_reliable}}
    (OUT / "run_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    for piece, n in PIECES.items():
        st12 = phase1(piece, n, ckm)
        for crnn in CRNNS:
            phase2(piece, st12, crnn, ckm)


if __name__ == "__main__":
    main()
