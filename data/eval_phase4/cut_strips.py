"""Phase 4 strip cut (PREREG.md section 3): Stage 1 + Stage 2 once, one page at a time. No model beyond YOLO runs.

Why not training/run_stage12.py: it batches a whole folder and numbers pages by folder order; here the page number is
the dataset manifest `page` column and a page that raises fails alone.

Firewall: Stage 1/2 stdout and stderr (they print per-page staff counts) go to per-page log files, never the console.
The console shows only the pages where Stage 2 raised. Refuses to overwrite an existing output folder (one cut).

Writes, per piece, under --out: strips/*.png, page<NN>_manifest.json, page<NN>_stage1.pkl (the PreprocessedPage,
for ClefKeyNet at the look), viz/, eyeball/, page<NN>_log.txt; and --out/cut_record.json with every sha256.

Usage (from the repo root):  python data/eval_phase4/cut_strips.py
Dry run on dev pages:        python data/eval_phase4/cut_strips.py --pieces honneur_a_toi --split dev --out <scratch>
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
import pickle
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # CPU, as data/eval_fresh: same boxes on every machine

import cv2
import torch

torch.cuda.is_available = lambda: False
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import stage1_preprocessing as s1  # noqa: E402
from stage2_detection import detect_staff_regions  # noqa: E402
from training.run_stage12 import write_eyeball_sheets  # noqa: E402

PHOTOS = Path("D:/PiyaNota/data/piyanota_dataset")
YOLO = Path("D:/PiyaNota/staff_detector_files/weights/best.pt")
OUT = Path("D:/PiyaNota/datasets/phase4_strips")
FREEZE_COMMIT = "c4db961"  # arm freeze; the cut must come after it (PREREG 3)
PIECES = ("ama_namin", "salmo_150", "ale_nasa_langit_na_ba_ako", "bituing_walang_ningning", "folk_medley",
          "hesus_ng_aking_buhay", "panalangin_sa_pagiging_bukas_palad", "sanay_wala_nang_wakas", "dormi_jesu",
          "livin_on_a_prayer")
EXPECTED_TEST_PAGES = 62  # PREREG section 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def pages_of(piece: str, split: str) -> list[tuple[int, str]]:
    with open(PHOTOS / "dataset_manifest.csv", encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["piece"] == piece and r["split"] == split]
    return sorted((int(r["page"]), r["filename"]) for r in rows)


def cut_page(work: Path, page_no: int, photo: Path) -> dict[str, Any]:
    log = io.StringIO()
    manifest_path = work / f"page{page_no:02d}_manifest.json"
    rec: dict[str, Any] = {"page": page_no, "photo": photo.name, "photo_sha256": sha256(photo)}
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            page = s1.preprocess_score_page(str(photo), keep_unmasked=True)
            detect_staff_regions([(page.detect, page_no, page.strip_source)], model_weights=str(YOLO),
                                 output_dir=str(work / "strips"), save_viz=True, viz_dir=str(work / "viz"),
                                 manifest_path=str(manifest_path))
    except (ValueError, RuntimeError, cv2.error) as exc:
        rec["failure"] = f"{type(exc).__name__}: {exc}"
        log.write("\n" + traceback.format_exc())
    (work / f"page{page_no:02d}_log.txt").write_text(log.getvalue(), encoding="utf-8")
    if "failure" in rec:
        return rec
    pkl = work / f"page{page_no:02d}_stage1.pkl"
    pkl.write_bytes(pickle.dumps(page, protocol=pickle.HIGHEST_PROTOCOL))
    rec["manifest_sha256"] = sha256(manifest_path)
    rec["stage1_pkl_sha256"] = sha256(pkl)
    return rec


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pieces", nargs="+", default=list(PIECES))
    parser.add_argument("--split", default="test")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; the cut runs once (PREREG 3). Re-cutting needs an amendment.")
    if subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", FREEZE_COMMIT, "HEAD"]).returncode:
        sys.exit(f"HEAD does not contain the arm freeze {FREEZE_COMMIT}")
    dirty = git("status", "--porcelain", "stage1_preprocessing.py", "stage2_detection.py", "data/eval_phase4/cut_strips.py")
    if dirty and args.split == "test":  # dev dry runs may use an uncommitted script
        sys.exit(f"uncommitted changes, the record would not match the commit:\n{dirty}")
    plan = {p: pages_of(p, args.split) for p in args.pieces}
    n_pages = sum(len(v) for v in plan.values())
    if args.split == "test" and n_pages != EXPECTED_TEST_PAGES:
        sys.exit(f"{n_pages} test pages, PREREG says {EXPECTED_TEST_PAGES}")

    record: dict[str, Any] = {
        "commit": git("rev-parse", "HEAD"), "split": args.split,
        "code_sha256": {name: sha256(ROOT / name) for name in
                        ("data/eval_phase4/cut_strips.py", "stage1_preprocessing.py", "stage2_detection.py",
                         "training/run_stage12.py")},
        "yolo_sha256": sha256(YOLO), "torch": torch.__version__, "cv2": cv2.__version__, "pieces": {}}
    failures: list[str] = []
    for piece, pages in plan.items():
        work = out / piece
        (work / "strips").mkdir(parents=True)
        recs = [cut_page(work, n, PHOTOS / fname) for n, fname in pages]
        write_eyeball_sheets(work / "strips", work / "eyeball")
        record["pieces"][piece] = {
            "pages": recs,
            "strips_sha256": {p.name: sha256(p) for p in sorted((work / "strips").glob("*.png"))}}
        # the exception type only: Stage 2's message states the staff count (kept in cut_record.json and the log)
        failures += [f"{piece} p{r['page']}: {r['failure'].split(':')[0]}" for r in recs if "failure" in r]
    (out / "cut_record.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(f"cut done: {len(plan)} pieces, {n_pages} pages. Stage 2 failures: {len(failures)}")
    for f in failures:
        print("  " + f)
    print(f"record sha256 {sha256(out / 'cut_record.json')}")


if __name__ == "__main__":
    main()
