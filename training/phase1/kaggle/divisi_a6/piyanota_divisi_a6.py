"""PIYA-106 A6: build the divisi corpus, the test renders and the corpus gates on Kaggle CPU (design sections 4-5).

One launch, no GPU. Structure follows the full-2 build kernel (`../divisi/piyanota_divisi_full.py`); what changed:
1. No G1b parity canary. That canary compared against the user-reviewed full-2 build, and the A6 generator
   deliberately builds a different corpus. The A6 G1b page is scored by the user outside this kernel.
2. Train renders use 2 fonts chosen from the 4 that are not Gootville (`render_corpus.py --exclude-font`), so no
   Gootville chord strip reaches training; val renders use all 5 fonts. Gootville stays in val and test, which is
   what makes it a held-out chord font.
3. Test renders: the val pieces whose crc32 is ODD, built three times with injection seeds divisi-t1..t3, rendered in
   all 5 fonts and cut. They are separate folders, never merged into the training renders (design section 4).
4. Gates (`divisi_a6_gates.py`) run on the finished build and the three test folders. The kernel exits non-zero if
   any gate fails or is missing, after the outputs are written so a failed run can still be inspected. The
   `--allow-no-test` escape hatch of the gates CLI is never used here.

Outputs under /kaggle/working: build/ (corpus, cut strips in out/, manifest/, divisi_summary.json), test_t{1,2,3}/
(same layout), xorder_report.json, column_gate.json, a6_gates.json, renders_svg.tar.gz, logs, kernel_status.json.

Local dry run (never on Kaggle): `--dry-run` swaps only the path resolution (work/scratch/code dir, the working tree
instead of a bundle clone, no pip) and takes `--limit N` pieces, `--cut-pages N`, `--commit-override`, and
`--no-abort-on-gate` so the stages after the gates still run. Nothing else differs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zlib
from pathlib import Path

# Filled by the controller after review with the full sha of the reviewed commit; the kernel refuses to run on
# anything else (a placeholder must fail loudly, never fall back to "whatever is in the bundle").
COMMIT = "UNSET-FILL-AFTER-REVIEW"
BRANCH = "piya106/stroke-calibration"
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
WORKERS = 4
CANARY_PAGES = 5
SESSION_MINUTES = 700       # of Kaggle's 12 h; the main cut stops starting pages when this is used up
PINS = ["numpy==2.5.3", "opencv-python==5.0.0.93", "scipy==1.16.3", "pillow==12.3.0", "psutil==7.2.2",
        "fonttools==4.61.0", "resvg_py==0.5.0", "ultralytics==8.4.144", "music21==10.5.0", "verovio==6.3.0"]
TORCH_PINS = ["torch==2.6.0", "torchvision==0.21.0"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
OPENCV_VARIANTS = ["opencv-python", "opencv-python-headless", "opencv-contrib-python",
                   "opencv-contrib-python-headless"]
HELD_OUT_FONT = "Gootville"
FONTS_PER_SPLIT = {"train": 2, "val": 5}   # train picks 2 of the 4 non-held-out fonts
TEST_FONTS = 5
TEST_SEEDS = ("divisi-t1", "divisi-t2", "divisi-t3")
CORPUS_SEED = "divisi"
DIVISI_SUFFIX = "__divisi"   # build_corpus.DIVISI_SUFFIX; the crc32 halves hash the suffixed id, as eval_divisi_a6 does
DRY_WORKERS = 1
DRY_CANARY_PAGES = 2

T0 = time.time()
status: dict[str, object] = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/divisi_a6")


def save_status() -> None:
    (WORK / "kernel_status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")


def abort(msg: str) -> None:
    status["aborted"] = msg
    save_status()
    raise SystemExit(msg)


def sh(cmd: list[str], log: Path | None = None, **kw: object) -> None:
    """Run a command; a non-zero exit aborts the kernel with the command named (and the status file written)."""
    print("+", " ".join(cmd[:8]), "..." if len(cmd) > 8 else "", flush=True)
    try:
        if log is None:
            subprocess.run(cmd, check=True, **kw)
        else:
            with log.open("a", encoding="utf-8") as f:
                subprocess.run(cmd, check=True, stdout=f, stderr=subprocess.STDOUT, **kw)
    except subprocess.CalledProcessError as exc:
        abort(f"command failed (exit {exc.returncode}): {' '.join(cmd[:6])} ...")


def find_one(name: str) -> Path:
    hits = sorted(Path("/kaggle/input").rglob(name))
    if not hits:
        abort(f"{name} not found under /kaggle/input")
    return hits[0]


def is_test_half(piece: str) -> bool:
    """The odd-crc32 half of the val pieces. Same input as training/phase2/eval_divisi_a6.py `load_rows`: the id of
    the built `<piece>__divisi` copy, so the tuning half (even) and this test half never overlap."""
    return zlib.crc32((piece + DIVISI_SUFFIX).encode()) % 2 == 1


def select_pieces(split_of: dict[str, str], limit: int) -> tuple[list[str], list[str], list[str]]:
    """(train, val, test-half-of-val) piece ids. `limit` > 0 (dry run only) keeps that many train pieces, that many
    test-half pieces and that many tuning-half pieces, so every stage still sees each kind."""
    train = sorted(p for p, s in split_of.items() if s == "train")
    val = sorted(p for p, s in split_of.items() if s == "val")
    test = [p for p in val if is_test_half(p)]
    if limit:
        tuning = [p for p in val if not is_test_half(p)][:limit]
        train, test = train[:limit], test[:limit]
        val = sorted(tuning + test)
    return train, val, test


def link_or_copy(src: Path, dst: Path, skip_png: bool = False) -> None:
    """Symlink (Kaggle, Linux); copy where symlinks need a privilege the dry-run host lacks.

    `skip_png` only drops page PNGs of the renders in the copy fallback; the cut strips are PNGs too and must stay.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(src, dst, target_is_directory=src.is_dir())
    except OSError as exc:
        print(f"symlink {dst} failed ({exc}); copying instead", flush=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.png") if skip_png else None)
        else:
            shutil.copy2(src, dst)


def subset_corpus(src: Path, dst: Path, pieces: list[str]) -> None:
    """Copy the MEI and plan of `pieces` into dst/corpus so a render run covers only that split."""
    (dst / "corpus").mkdir(parents=True, exist_ok=True)
    for p in pieces:
        for suffix in (".mei", ".plan.json"):
            f = src / "corpus" / f"{p}{DIVISI_SUFFIX}{suffix}"
            if f.is_file():   # a piece the build skipped is reported by pieces_missing_from_build, not here
                shutil.copy2(f, dst / "corpus" / f.name)


def main() -> int:  # noqa: C901 (a linear kernel script; stages are numbered, not split across functions)
    global WORK, SCRATCH, COMMIT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="local CPU dry run: path resolution only, see docstring")
    ap.add_argument("--work", type=Path, default=None)
    ap.add_argument("--scratch", type=Path, default=None)
    ap.add_argument("--code-dir", type=Path, default=None, help="dry run: folder holding the files of the code dataset")
    ap.add_argument("--commit-override", default="", help="dry run only: record this sha instead of COMMIT")
    ap.add_argument("--limit", type=int, default=0, help="dry run only: pieces per kind (train / tuning / test)")
    ap.add_argument("--cut-pages", type=int, default=0, help="dry run only: pages per cut run")
    ap.add_argument("--no-abort-on-gate", action="store_true", help="dry run only: finish later stages after a gate fail")
    args = ap.parse_args()
    dry = args.dry_run
    if not dry and (args.limit or args.cut_pages or args.no_abort_on_gate or args.commit_override or args.code_dir):
        raise SystemExit("--limit/--cut-pages/--no-abort-on-gate/--commit-override/--code-dir need --dry-run")
    if dry:
        if args.work is None or args.scratch is None or args.code_dir is None:
            raise SystemExit("--dry-run needs --work, --scratch and --code-dir")
        WORK, SCRATCH = args.work, args.scratch
        COMMIT = args.commit_override or COMMIT
    if not COMMIT_SHA.fullmatch(COMMIT):   # before any directory is made: nothing may run on an unreviewed commit
        raise SystemExit(f"COMMIT is not a full sha ({COMMIT!r}): the controller fills it after review")
    WORK.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    status.update({"commit": COMMIT, "dry_run": dry})
    workers = DRY_WORKERS if dry else WORKERS
    canary_pages = DRY_CANARY_PAGES if dry else CANARY_PAGES
    cut_limit = args.cut_pages

    # 1. Pinned environment (Kaggle only: the dry run uses the dev venv, whose pins match).
    if not dry:
        sh([sys.executable, "-m", "pip", "uninstall", "-y", "-q", *OPENCV_VARIANTS])
        sh([sys.executable, "-m", "pip", "install", "-q", *TORCH_PINS, "--index-url", TORCH_INDEX])
        sh([sys.executable, "-m", "pip", "install", "-q", *PINS])

    # 2. Code at the reviewed commit.
    if dry:
        code_dir = args.code_dir
        repo = Path(__file__).resolve().parents[4]
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        status["dry_run_working_tree_head"] = head   # the working tree, not a bundle: the new code is uncommitted
    else:
        code_dir = find_one("repo.bundle").parent
        repo = SCRATCH / "repo"
        sh(["git", "clone", "-q", "-b", BRANCH, str(code_dir / "repo.bundle"), str(repo)],
           env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"})
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        if head != COMMIT:
            abort(f"bundle HEAD {head} != reviewed commit {COMMIT}")
    manifest = code_dir / "phase2_manifest.jsonl"
    sys.path.insert(0, str(code_dir))
    from parity_digest import compare, digest  # noqa: PLC0415

    env_run = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "PYTHONUTF8": "1"}
    p1, p2 = repo / "training" / "phase1", repo / "training" / "phase2"

    def build(out: Path, pieces: list[str], seed: str) -> None:
        sh([sys.executable, str(p1 / "build_corpus.py"), "--out", str(out), "--composers", "bach", "--divisi",
            str(manifest), "--divisi-seed", seed, "--pieces", ",".join(pieces)],
           WORK / f"build_{out.name}.log", cwd=str(repo), env=env_run)

    def render(out: Path, fonts: int, exclude: str = "") -> None:
        extra = ["--exclude-font", exclude] if exclude else []
        sh([sys.executable, str(p1 / "render_corpus.py"), "--out", str(out), "--composers", "bach",
            "--fonts-per-piece", str(fonts), "--vocab-ext", *extra],
           WORK / f"render_{out.name}.log", cwd=str(repo), env=env_run)

    def cut(out: Path, renders: Path, limit: int, n_workers: int, max_minutes: float = 0.0) -> None:
        cmd = [sys.executable, str(p1 / "cut_corpus.py"), "run", "--out", str(out), "--renders", str(renders),
               "--yolo", str(code_dir / "best.pt"), "--camera", str(code_dir / "camera_page_stats.json"), "--stats",
               "--workers", str(n_workers)]
        if limit:
            cmd += ["--limit", str(limit)]
        if max_minutes:
            cmd += ["--max-minutes", str(max_minutes)]
        sh(cmd, WORK / f"cut_{out.parent.name}_{out.name}.log", cwd=str(repo), env=env_run)

    def cut_complete(out: Path, renders: Path, what: str) -> None:
        """Every rendered page has a result; a time-boxed or crashed cut would silently shrink the corpus."""
        pages_in = len(list(renders.rglob("page_*.svg")))
        pages_out = len(list((out / "pages").rglob("*.json"))) if (out / "pages").exists() else 0
        status[f"{what}_pages"] = {"rendered_pages": pages_in, "cut_results": pages_out}
        save_status()
        if not cut_limit and pages_out < pages_in:
            abort(f"{what}: {pages_out} page results for {pages_in} rendered pages (cut incomplete)")

    def make_manifest(out: Path, dest: Path) -> None:
        sh([sys.executable, str(p2 / "build_manifest.py"), str(out), str(dest)],
           WORK / f"manifest_{dest.parent.name}.log", cwd=str(repo), env=env_run)
        rows = [json.loads(x) for x in (dest / "phase2_manifest.jsonl").read_text(encoding="utf-8").splitlines() if x]
        wrong = [r["piece"] for r in rows if split_of[r["piece"].removesuffix(DIVISI_SUFFIX)] != r["split"]]
        if wrong:
            abort(f"{dest}: {len(set(wrong))} pieces whose split differs from the Phase 2 manifest, e.g. {wrong[:3]}")

    # 3. Pieces, with the splits of the Phase 2 manifest. Test half = odd crc32 of val pieces.
    split_of: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        split_of[row["piece"]] = row["split"]
    train, val, test = select_pieces(split_of, args.limit)
    status["pieces"] = {"train": len(train), "val": len(val), "test_half": len(test),
                        "tuning_half": len(val) - len(test)}
    save_status()
    if not train or not test:
        abort(f"empty piece selection: {status['pieces']}")

    # 4. Build the corpus once (the mix gates need one summary), then render each split into its own folder.
    corpus_all = SCRATCH / "corpus_all"
    build(corpus_all, train + val, CORPUS_SEED)
    merged = SCRATCH / "renders"
    for split, pieces in (("train", train), ("val", val)):
        rdir = SCRATCH / f"render_{split}"
        subset_corpus(corpus_all, rdir, pieces)
        render(rdir, FONTS_PER_SPLIT[split], HELD_OUT_FONT if split == "train" else "")
        shutil.copytree(rdir / "renders", merged, dirs_exist_ok=True)
        shutil.copy2(rdir / "render_summary.json", WORK / f"render_summary_{split}.json")
    bdir = WORK / "build"
    shutil.copytree(corpus_all / "corpus", bdir / "corpus", dirs_exist_ok=True)
    for f in corpus_all.glob("*.json"):
        shutil.copy2(f, bdir / f.name)
    status["build_render_minutes"] = round((time.time() - T0) / 60, 1)
    save_status()

    # 5. Test renders: three injection seeds over the test-half pieces, all 5 fonts, cut separately.
    test_dirs: list[Path] = []
    for n, seed in enumerate(TEST_SEEDS, start=1):
        tdir = SCRATCH / f"test_t{n}"
        out_dir = WORK / f"test_t{n}"
        build(tdir, test, seed)
        render(tdir, TEST_FONTS)
        cut(out_dir / "out", tdir / "renders", cut_limit, workers)
        cut_complete(out_dir / "out", tdir / "renders", f"test_t{n}")
        make_manifest(out_dir / "out", out_dir / "manifest")
        shutil.copytree(tdir / "corpus", out_dir / "corpus", dirs_exist_ok=True)
        for f in tdir.glob("*.json"):
            shutil.copy2(f, out_dir / f.name)
        test_dirs.append(out_dir)
    status["test_minutes"] = round((time.time() - T0) / 60, 1)
    save_status()

    # 6. Worker check, then the main cut.
    cut(SCRATCH / "canary_workersN", merged, canary_pages, workers)
    cut(SCRATCH / "canary_workers1", merged, canary_pages, 1)
    check = compare(digest(SCRATCH / "canary_workers1"), digest(SCRATCH / "canary_workersN"))
    status["workers1_vs_workersN"] = {**check, "workers_compared": [1, workers]}
    if not check["identical"]:
        abort("worker check differs: cut NOT started")
    cut(bdir / "out", merged, cut_limit, workers, SESSION_MINUTES - (time.time() - T0) / 60)
    cut_complete(bdir / "out", merged, "build")
    make_manifest(bdir / "out", bdir / "manifest")
    status["cut_finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_status()

    # 7. Audits: chord x-order (A3) and column collapse, then the renders archive (SVG + JSON, no PNG).
    sh([sys.executable, str(p1 / "chord_xorder_audit.py"), "--renders", str(merged), "--out",
        str(WORK / "xorder_report.json")], cwd=str(repo), env=env_run)
    colgate = SCRATCH / "colgate"
    link_or_copy(bdir / "manifest", colgate / "manifest")
    link_or_copy(bdir / "out", colgate / "out")
    link_or_copy(merged, colgate / "renders_svg" / "renders", skip_png=True)
    with (WORK / "column_gate.json").open("w", encoding="utf-8") as f:
        # shortcut: the column gate prints its report and has no pass/fail exit; it is recorded here, not enforced
        # (full-2 recorded 0.16% infeasible columns), so the controller reads column_gate.json after the run.
        col = subprocess.run([sys.executable, str(p1 / "divisi_column_gate.py"), str(colgate)], stdout=f,
                             stderr=subprocess.STDOUT, cwd=str(repo), env=env_run, check=False)
    status["column_gate_exit"] = col.returncode
    save_status()
    with tarfile.open(WORK / "renders_svg.tar.gz", "w:gz") as t:
        for f in sorted(merged.rglob("*")):
            if f.is_file() and f.suffix in (".svg", ".json"):
                t.add(f, arcname=str(Path("renders") / f.relative_to(merged)))

    # 8. Corpus gates. Exit 1 on any failed or MISSING gate; the escape hatch for absent tests is never passed.
    gates = subprocess.run([sys.executable, str(p1 / "divisi_a6_gates.py"), "--build", str(bdir), "--test",
                            *map(str, test_dirs), "--out", str(WORK / "a6_gates.json"), "--a5-manifest",
                            str(manifest)], cwd=str(repo), env=env_run, check=False)
    status["gates_exit"] = gates.returncode
    status["total_minutes"] = round((time.time() - T0) / 60, 1)
    save_status()
    print(json.dumps(status, indent=1))
    if col.returncode != 0:   # a crash of the report script, not a verdict: the column report would be missing
        print(f"WARNING: column gate script exited {col.returncode}; see column_gate.json", flush=True)
    if (gates.returncode != 0 or col.returncode != 0) and not args.no_abort_on_gate:
        abort(f"A6 corpus gates failed (gates exit {gates.returncode}, column gate exit {col.returncode}); "
              "see a6_gates.json and column_gate.json")
    return 0 if args.no_abort_on_gate else gates.returncode


if __name__ == "__main__":
    sys.exit(main())
