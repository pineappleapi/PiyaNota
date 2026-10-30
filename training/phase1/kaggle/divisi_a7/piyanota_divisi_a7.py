"""PIYA-106 A7: build, render and cut one arm's divisi corpus on Kaggle CPU, then run the A7 corpus gates.

One kernel per arm (`ARM` below: "C" chords only, "CL" chords + layers), pushed as piyanota-divisi-a7-c and
piyanota-divisi-a7-cl so both run in parallel; the two copies differ only in the ARM line. Follows the A6 build
kernel (`../divisi_a6/piyanota_divisi_a6.py`) with these changes (design piya-106-divisi-a7-design.md, 14.3-14.6):
1. `build_corpus.py --a7 <ARM> --divisi-seed divisi-a7`; renders guard against VOCAB_EXT_A7 (`--vocab-a7`).
2. No synthetic test seeds: A7 is tested on the real 10-piece test set (user 2026-10-30), outside this kernel.
3. Gates: `divisi_a7_gates.py` (A7 targets, dyad exposure vs A6 v2, template/ledger floors, x-order audit).
Train renders use 2 of the 4 non-Gootville fonts, val renders all 5, so Gootville stays a held-out font.
The kernel always exits 0 once WORK exists and writes kernel_status.json with status ok | gate_fail | kernel_error.

Outputs under /kaggle/working: build/ (corpus, out/ cut strips, manifest/, divisi_summary.json), halves.json, render summaries,
xorder_report.json, column_gate.json, a7_gates.json, renders_svg.tar.gz, logs, kernel_status.json.

Local dry run: `--dry-run --work W --scratch S --code-dir D --limit N --cut-pages N --commit-override SHA`.
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
import traceback
from pathlib import Path

ARM = "CL"
COMMIT = "b15582a3b115571ea00682505465c8f83c2d7230"   # full sha of the reviewed commit, filled by the controller; anything else refuses to run
BRANCH = "piya106/stroke-calibration"
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
WORKERS = 4
CANARY_PAGES = 5
SESSION_MINUTES = 700
CORPUS_SEED = "divisi-a7"
PINS = ["numpy==2.5.3", "opencv-python==5.0.0.93", "scipy==1.16.3", "pillow==12.3.0", "psutil==7.2.2",
        "fonttools==4.61.0", "resvg_py==0.5.0", "ultralytics==8.4.144", "music21==10.5.0", "verovio==6.3.0"]
TORCH_PINS = ["torch==2.6.0", "torchvision==0.21.0"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
OPENCV_VARIANTS = ["opencv-python", "opencv-python-headless", "opencv-contrib-python",
                   "opencv-contrib-python-headless"]
HELD_OUT_FONT = "Gootville"
FONTS_PER_SPLIT = {"train": 2, "val": 5}
DIVISI_SUFFIX = "__divisi"
DRY_WORKERS = 1
DRY_CANARY_PAGES = 2

T0 = time.time()
status: dict[str, object] = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "arm": ARM}
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/divisi_a7")


class KernelError(RuntimeError):
    """A stage failed; main() records it as status kernel_error and still exits 0."""


def save_status() -> None:
    (WORK / "kernel_status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")


def abort(msg: str) -> None:
    status["aborted"] = msg
    save_status()
    raise KernelError(msg)


def sh(cmd: list[str], log: Path | None = None, **kw: object) -> None:
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


def subset_corpus(src: Path, dst: Path, pieces: list[str]) -> None:
    (dst / "corpus").mkdir(parents=True, exist_ok=True)
    for p in pieces:
        for suffix in (".mei", ".plan.json"):
            f = src / "corpus" / f"{p}{DIVISI_SUFFIX}{suffix}"
            if f.is_file():   # a skipped piece has no file; build_corpus lists it in pieces_missing_from_build
                shutil.copy2(f, dst / "corpus" / f.name)


def main() -> int:
    global WORK, SCRATCH, COMMIT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--work", type=Path)
    ap.add_argument("--scratch", type=Path)
    ap.add_argument("--code-dir", type=Path)
    ap.add_argument("--commit-override", default="")
    ap.add_argument("--limit", type=int, default=0, help="dry run only: pieces per split")
    ap.add_argument("--cut-pages", type=int, default=0, help="dry run only: pages per cut run")
    args = ap.parse_args()
    if ARM not in ("C", "CL"):
        raise SystemExit(f"ARM {ARM!r}")
    if not args.dry_run and (args.limit or args.cut_pages or args.commit_override or args.code_dir):
        raise SystemExit("--limit/--cut-pages/--commit-override/--code-dir need --dry-run")
    if args.dry_run:
        if args.work is None or args.scratch is None or args.code_dir is None:
            raise SystemExit("--dry-run needs --work, --scratch and --code-dir")
        WORK, SCRATCH = args.work, args.scratch
        COMMIT = args.commit_override or COMMIT
    if not COMMIT_SHA.fullmatch(COMMIT):
        raise SystemExit(f"COMMIT is not a full sha ({COMMIT!r}): the controller fills it after review")
    WORK.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    status.update({"commit": COMMIT, "dry_run": args.dry_run})
    try:
        status["status"] = run(args)
    except Exception:  # noqa: BLE001 (the kernel must still exit 0 and say what broke)
        status["status"] = "kernel_error"
        status["traceback"] = traceback.format_exc()
        print(status["traceback"], flush=True)
    status["total_minutes"] = round((time.time() - T0) / 60, 1)
    save_status()
    print(json.dumps({k: v for k, v in status.items() if k != "traceback"}, indent=1))
    return 0


def run(args: argparse.Namespace) -> str:  # noqa: C901 (a linear kernel; stages are numbered)
    dry = args.dry_run
    workers = DRY_WORKERS if dry else WORKERS
    canary_pages = DRY_CANARY_PAGES if dry else CANARY_PAGES

    # 1. Pinned environment (Kaggle only).
    if not dry:
        sh([sys.executable, "-m", "pip", "uninstall", "-y", "-q", *OPENCV_VARIANTS])
        sh([sys.executable, "-m", "pip", "install", "-q", *TORCH_PINS, "--index-url", TORCH_INDEX])
        sh([sys.executable, "-m", "pip", "install", "-q", *PINS])

    # 2. Code at the reviewed commit.
    if dry:
        code_dir = args.code_dir
        repo = Path(__file__).resolve().parents[4]
    else:
        code_dir = find_one("repo.bundle").parent
        repo = SCRATCH / "repo"
        sh(["git", "clone", "-q", "-b", BRANCH, str(code_dir / "repo.bundle"), str(repo)],
           env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"})
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    status["repo_head"] = head
    if not dry and head != COMMIT:
        abort(f"bundle HEAD {head} != reviewed commit {COMMIT}")
    manifest = code_dir / "phase2_manifest.jsonl"
    env_run = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "PYTHONUTF8": "1"}
    p1, p2 = repo / "training" / "phase1", repo / "training" / "phase2"
    sys.path.insert(0, str(p1))
    sys.path.insert(0, str(code_dir))
    from parity_digest import compare, digest  # noqa: PLC0415

    def render(out: Path, fonts: int, exclude: tuple[str, ...] = ()) -> None:
        extra = [x for f in exclude for x in ("--exclude-font", f)]
        sh([sys.executable, str(p1 / "render_corpus.py"), "--out", str(out), "--composers", "bach",
            "--fonts-per-piece", str(fonts), "--vocab-a7", *extra], WORK / f"render_{out.name}.log",
           cwd=str(repo), env=env_run)

    def cut(out: Path, renders: Path, limit: int, n_workers: int, max_minutes: float = 0.0) -> None:
        cmd = [sys.executable, str(p1 / "cut_corpus.py"), "run", "--out", str(out), "--renders", str(renders),
               "--yolo", str(code_dir / "best.pt"), "--camera", str(code_dir / "camera_page_stats.json"), "--stats",
               "--workers", str(n_workers)]
        if limit:
            cmd += ["--limit", str(limit)]
        if max_minutes:
            cmd += ["--max-minutes", str(max_minutes)]
        sh(cmd, WORK / f"cut_{out.parent.name}_{out.name}.log", cwd=str(repo), env=env_run)

    # 3. Pieces and splits of the Phase 2 manifest.
    split_of: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        split_of[row["piece"]] = row["split"]
    train = sorted(p for p, s in split_of.items() if s == "train")
    val = sorted(p for p, s in split_of.items() if s == "val")
    if args.limit:
        train, val = train[:args.limit], val[:args.limit]
    # Tune-group halves, as the A6 kernel froze them (ml-cv-lead 2026-10-30, change 1): train_phase2 needs halves.json
    # so per-epoch divisi val scores the tuning half only; the synthetic test half (Gootville included) never touches
    # selection and carries the layer / 2+ ledger buckets the real 10-piece set cannot power.
    import divisi_halves  # noqa: PLC0415
    pieces_all = sorted(p for p, sp in split_of.items() if sp in ("train", "val"))
    sources = divisi_halves.bach_sources()
    unknown = [p for p in pieces_all if p not in sources]
    if unknown:
        abort(f"{len(unknown)} manifest pieces have no music21 source (first: {unknown[:3]}); cannot group tunes")
    intervals, titles = divisi_halves.source_features(sources, pieces_all)
    groups = divisi_halves.tune_groups(pieces_all, intervals, titles)
    halves = divisi_halves.halves_report(groups, split_of)
    halves["melodyless_pieces"] = sorted(p for p in pieces_all if not intervals.get(p))
    (WORK / "halves.json").write_text(json.dumps(halves, indent=1), encoding="utf-8")
    status["halves"] = halves["counts"]
    status["pieces"] = {"train": len(train), "val": len(val),
                        "test_half": sum(1 for p in val if divisi_halves.is_test_half(p, groups))}
    save_status()

    # 4. Build once (one summary for the gates), then render each split into its own folder.
    corpus_all = SCRATCH / "corpus_all"
    sh([sys.executable, str(p1 / "build_corpus.py"), "--out", str(corpus_all), "--composers", "bach", "--divisi",
        str(manifest), "--divisi-seed", CORPUS_SEED, "--a7", ARM, "--pieces", ",".join(train + val)],
       WORK / "build.log", cwd=str(repo), env=env_run)
    merged = SCRATCH / "renders"
    summaries: list[Path] = []
    for split, pieces in (("train", train), ("val", val)):
        rdir = SCRATCH / f"render_{split}"
        subset_corpus(corpus_all, rdir, pieces)
        render(rdir, FONTS_PER_SPLIT[split], (HELD_OUT_FONT,) if split == "train" else ())
        shutil.copytree(rdir / "renders", merged, dirs_exist_ok=True)
        dst = WORK / f"render_summary_{split}.json"
        shutil.copy2(rdir / "render_summary.json", dst)
        summaries.append(dst)
    bdir = WORK / "build"
    shutil.copytree(corpus_all / "corpus", bdir / "corpus", dirs_exist_ok=True)
    for f in corpus_all.glob("*.json"):
        shutil.copy2(f, bdir / f.name)
    status["build_render_minutes"] = round((time.time() - T0) / 60, 1)
    save_status()

    # 5. Worker determinism canary before the main cut.
    cut(SCRATCH / "canary_workersN", merged, canary_pages, workers)
    cut(SCRATCH / "canary_workers1", merged, canary_pages, 1)
    check = compare(digest(SCRATCH / "canary_workers1"), digest(SCRATCH / "canary_workersN"))
    status["workers1_vs_workersN"] = {**check, "workers_compared": [1, workers]}
    save_status()
    if not check["identical"]:
        abort("worker check differs: cut NOT started")

    # 6. Main cut, completeness, manifest.
    cut(bdir / "out", merged, args.cut_pages, workers, SESSION_MINUTES - (time.time() - T0) / 60)
    pages_in = len(list(merged.rglob("page_*.svg")))
    pages_out = len(list((bdir / "out" / "pages").rglob("*.json"))) if (bdir / "out" / "pages").exists() else 0
    status["build_pages"] = {"rendered_pages": pages_in, "cut_results": pages_out}
    if not args.cut_pages and pages_out < pages_in:
        abort(f"{pages_out} page results for {pages_in} rendered pages (cut incomplete)")
    sh([sys.executable, str(p2 / "build_manifest.py"), str(bdir / "out"), str(bdir / "manifest")],
       WORK / "manifest.log", cwd=str(repo), env=env_run)
    rows = [json.loads(x) for x in (bdir / "manifest" / "phase2_manifest.jsonl").read_text(encoding="utf-8")
            .splitlines() if x]
    wrong = [r["piece"] for r in rows if split_of[r["piece"].removesuffix(DIVISI_SUFFIX)] != r["split"]]
    if wrong:
        abort(f"{len(set(wrong))} pieces whose split differs from the Phase 2 manifest, e.g. {wrong[:3]}")
    status["gootville_train_rows"] = sum(1 for r in rows if r["split"] == "train" and r["font"] == HELD_OUT_FONT)
    status["cut_finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_status()

    # 7. Audits and archive.
    sh([sys.executable, str(p1 / "chord_xorder_audit.py"), "--renders", str(merged), "--out",
        str(WORK / "xorder_report.json")], cwd=str(repo), env=env_run)
    colgate = SCRATCH / "colgate"
    for src, dst in ((bdir / "manifest", colgate / "manifest"), (bdir / "out", colgate / "out"),
                     (merged, colgate / "renders_svg" / "renders")):
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(src, dst, target_is_directory=True)
        except OSError:
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.png") if src == merged else None)
    with (WORK / "column_gate.json").open("w", encoding="utf-8") as f:
        col = subprocess.run([sys.executable, str(p1 / "divisi_column_gate.py"), str(colgate)], stdout=f,
                             stderr=subprocess.STDOUT, cwd=str(repo), env=env_run, check=False)
    status["column_gate_exit"] = col.returncode
    with tarfile.open(WORK / "renders_svg.tar.gz", "w:gz") as t:
        for f in sorted(merged.rglob("*")):
            if f.is_file() and f.suffix in (".svg", ".json"):
                t.add(f, arcname=str(Path("renders") / f.relative_to(merged)))
    save_status()

    # 8. A7 corpus gates.
    gates = subprocess.run([sys.executable, str(p1 / "divisi_a7_gates.py"), "--build", str(bdir), "--out",
                            str(WORK / "a7_gates.json"), "--a5-manifest", str(manifest), "--render-summary",
                            *map(str, summaries)], cwd=str(repo), env=env_run, check=False)
    status["gates_exit"] = gates.returncode
    report_path = WORK / "a7_gates.json"
    if gates.returncode not in (0, 1) or not report_path.is_file():
        raise KernelError(f"gates script crashed (exit {gates.returncode}); no verdict")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    status["failing_gates"] = [g["name"] for g in report["gates"]
                               if g["status"] not in ("pass", "warn", "not_run", "info")]
    if status["gootville_train_rows"]:
        status["failing_gates"].append("gootville_absent_from_train")  # type: ignore[union-attr]
    return "ok" if report["ok"] and not status["gootville_train_rows"] else "gate_fail"


if __name__ == "__main__":
    sys.exit(main())
