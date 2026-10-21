"""PIYA-106 A6: build the divisi corpus, the test renders and the corpus gates on Kaggle CPU (design sections 4-5).

One launch, no GPU. Structure follows the full-2 build kernel (`../divisi/piyanota_divisi_full.py`); what changed:
1. No G1b parity canary. That canary compared against the user-reviewed full-2 build, and the A6 generator
   deliberately builds a different corpus. The A6 G1b page is scored by the user outside this kernel.
2. Train renders use 2 fonts chosen from the 4 that are not Gootville (`render_corpus.py --exclude-font`), so no
   Gootville chord strip reaches training; val renders use all 5 fonts. Gootville stays in val and test, which is
   what makes it a held-out chord font.
3. Test renders (A6.1, review round 1): the val pieces in the TEST half of their tune group
   (`training/phase1/divisi_halves.py`: pieces sharing a transposition-invariant hash of the first 12 soprano intervals
   or a hymn title are one group; half = odd crc32 of the group key; never re-rolled). Injection seeds divisi-t1..t20
   are run adaptively and frozen in test_plan.json before the first test render: phase A (5 fonts per seed) until every
   bucket except the 7th has >= 600 unique in-font heads, then phase B (Gootville only) until it has >= 300 unique
   Gootville heads, capped at 20 seeds and by the time budget. Unique heads are counted after cut and manifest from the
   rendered labels (divisi_a6_gates.unique_head_counts). Test folders are never merged into the training renders.
4. Gates (`divisi_a6_gates.py`) run on the finished build and the test folders. A short test bucket is UNDERPOWERED,
   never PASS. The kernel always exits 0 once its directories exist and writes kernel_status.json with `status` in
   ok | gate_fail | kernel_error (an exception is caught and its traceback recorded), the failing gates and the sha256
   of every test manifest (test_plan_result.json; test_plan.json stays as frozen, its hash is in the status). The only non-zero exit is an unreviewed COMMIT, before any directory is made.
5. The worker 1-vs-N determinism canary runs first, before any test-seed build or cut. The main cut runs before the
   test seeds so the adaptive seeds only spend what the cut leaves of the session.

Outputs under /kaggle/working: build/ (corpus, cut strips in out/, manifest/, divisi_summary.json), test_t{1..N}/
(same layout, plus test_phase.json), test_plan.json, halves.json, xorder_report.json, column_gate.json, a6_gates.json, renders_svg.tar.gz, logs, kernel_status.json.

Local dry run (never on Kaggle): `--dry-run` swaps only the path resolution (work/scratch/code dir, the working tree
instead of a bundle clone, no pip) and takes `--limit N` pieces, `--cut-pages N`, `--commit-override`, and
`--no-abort-on-gate` so the stages after the gates still run. Nothing else differs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
from pathlib import Path

# Filled by the controller after review with the full sha of the reviewed commit; the kernel refuses to run on
# anything else (a placeholder must fail loudly, never fall back to "whatever is in the bundle").
COMMIT = "392b25b5a719d9c0512eae1a237a5ffc32024c8e"
BRANCH = "piya106/stroke-calibration"
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
WORKERS = 4
CANARY_PAGES = 5
SESSION_MINUTES = 700       # of Kaggle's 12 h; the main cut stops starting pages when this is used up
KAGGLE_SESSION_MINUTES = 720
TEST_RESERVE_MINUTES = 90   # no new test seed unless this much of the session would remain after it
DEFAULT_PAIRED_SEED_MINUTES = 30.0      # estimate before any seed has run; then the mean of the finished ones
GOOTVILLE_SEED_FRACTION = 5             # a Gootville-only seed renders 1 of 5 fonts
TEST_SEED_CAP = 20
PHASE_A_MIN = 600           # unique in-font heads per bucket (7th exempt) -> phase B
PHASE_B_MIN = 300           # unique Gootville heads per bucket (7th exempt) -> stop
EXEMPT_BUCKET = "7th"
RNG_DRAWS = 8
PAIRED, GOOTVILLE_ONLY = "paired", "gootville_only"
PINS = ["numpy==2.5.3", "opencv-python==5.0.0.93", "scipy==1.16.3", "pillow==12.3.0", "psutil==7.2.2",
        "fonttools==4.61.0", "resvg_py==0.5.0", "ultralytics==8.4.144", "music21==10.5.0", "verovio==6.3.0"]
TORCH_PINS = ["torch==2.6.0", "torchvision==0.21.0"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
OPENCV_VARIANTS = ["opencv-python", "opencv-python-headless", "opencv-contrib-python",
                   "opencv-contrib-python-headless"]
HELD_OUT_FONT = "Gootville"
FONT_NAMES = ("Leipzig", "Bravura", "Gootville", "Leland", "Petaluma")   # render_corpus.FONTS
FONTS_PER_SPLIT = {"train": 2, "val": 5}   # train picks 2 of the 4 non-held-out fonts
TEST_FONTS = 5
CORPUS_SEED = "divisi"
DIVISI_SUFFIX = "__divisi"   # build_corpus.DIVISI_SUFFIX
DRY_WORKERS = 1
DRY_CANARY_PAGES = 2

T0 = time.time()
status: dict[str, object] = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/divisi_a6")


class KernelError(RuntimeError):
    """A stage failed; main() records it as status kernel_error and still exits 0."""


def save_status() -> None:
    (WORK / "kernel_status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")


def abort(msg: str) -> None:
    status["aborted"] = msg
    save_status()
    raise KernelError(msg)


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


def select_pieces(split_of: dict[str, str], groups: dict[str, str], limit: int, is_test_half: object
                  ) -> tuple[list[str], list[str], list[str]]:
    """(train, val, test-half-of-val) piece ids; halves come from the tune groups, never from the piece id.

    `limit` > 0 (dry run only) keeps that many train pieces, that many test-half pieces and that many tuning-half
    pieces, so every stage still sees each kind.
    """
    train = sorted(p for p, s in split_of.items() if s == "train")
    val = sorted(p for p, s in split_of.items() if s == "val")
    test = [p for p in val if is_test_half(p, groups)]  # type: ignore[operator]
    if limit:
        tuning = [p for p in val if not is_test_half(p, groups)][:limit]  # type: ignore[operator]
        train, test = train[:limit], test[:limit]
        val = sorted(tuning + test)
    return train, val, test


def rng_hash(seed: str, piece_id: str) -> str:
    """Hash of the first draws of the injection RNG, derived as build_divisi does: Random(f"{seed}:{piece_id}")."""
    rng = random.Random(f"{seed}:{piece_id}")
    return hashlib.sha256(repr([rng.random() for _ in range(RNG_DRAWS)]).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
            if f.is_file():   # a skipped or unreached piece has no file; build_corpus counts it in
                shutil.copy2(f, dst / "corpus" / f.name)   # pieces_missing_from_build (A6.1) and the gates fail on it


def estimate_seed_minutes(done: list[tuple[str, float]], phase: str) -> float:
    """Minutes the next seed of `phase` is expected to take: mean of finished seeds of that phase, else a derived guess."""
    same = [m for ph, m in done if ph == phase]
    if same:
        return sum(same) / len(same)
    paired = [m for ph, m in done if ph == PAIRED]
    base = sum(paired) / len(paired) if paired else DEFAULT_PAIRED_SEED_MINUTES
    return base if phase == PAIRED else base / GOOTVILLE_SEED_FRACTION


def next_phase(counts: dict[str, dict[str, int]], need_in_font: int, need_held_out: int,
               buckets: list[str]) -> str | None:
    """PAIRED while a bucket is short of unique in-font heads, GOOTVILLE_ONLY while short of Gootville heads, else None.

    `counts` is `unique_head_counts(...)["counts"]` as plain dicts: {"in_font": {bucket: n}, "held_out": {...}}.
    """
    if any(counts["in_font"].get(b, 0) < need_in_font for b in buckets):
        return PAIRED
    if any(counts["held_out"].get(b, 0) < need_held_out for b in buckets):
        return GOOTVILLE_ONLY
    return None


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
    ap.add_argument("--no-abort-on-gate", action="store_true", help="dry run only: accepted for old commands; the "
                    "kernel no longer aborts on a gate failure (status gate_fail, exit 0)")
    ap.add_argument("--max-test-seeds", type=int, default=0, help="dry run only: lower the test seed cap")
    ap.add_argument("--phase-a-min", type=int, default=None, help="dry run only: replaces the 600 in-font target")
    ap.add_argument("--phase-b-min", type=int, default=None, help="dry run only: replaces the 300 Gootville target")
    args = ap.parse_args()
    dry = args.dry_run
    overrides = (args.limit or args.cut_pages or args.no_abort_on_gate or args.commit_override or args.code_dir
                 or args.max_test_seeds or args.phase_a_min is not None or args.phase_b_min is not None)
    if not dry and overrides:
        raise SystemExit("--limit/--cut-pages/--no-abort-on-gate/--commit-override/--code-dir/--max-test-seeds/"
                         "--phase-a-min/--phase-b-min need --dry-run")
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
    try:
        verdict = run(args)
        status["status"] = verdict
    except Exception:  # noqa: BLE001 (the kernel must still exit 0 and say what broke; the traceback is the evidence)
        status["status"] = "kernel_error"
        status["traceback"] = traceback.format_exc()
        print(status["traceback"], flush=True)
    status["total_minutes"] = round((time.time() - T0) / 60, 1)
    save_status()
    print(json.dumps({k: v for k, v in status.items() if k != "traceback"}, indent=1))
    return 0


def run(args: argparse.Namespace) -> str:  # noqa: C901
    """All stages; returns "ok" or "gate_fail", raises on anything else (main turns that into kernel_error)."""
    dry = args.dry_run
    workers = DRY_WORKERS if dry else WORKERS
    canary_pages = DRY_CANARY_PAGES if dry else CANARY_PAGES
    cut_limit = args.cut_pages
    seed_cap = args.max_test_seeds or TEST_SEED_CAP
    need_in_font = PHASE_A_MIN if args.phase_a_min is None else args.phase_a_min
    need_held_out = PHASE_B_MIN if args.phase_b_min is None else args.phase_b_min

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
    env_run = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "PYTHONUTF8": "1"}
    p1, p2 = repo / "training" / "phase1", repo / "training" / "phase2"
    sys.path.insert(0, str(p1))
    from parity_digest import compare, digest  # noqa: PLC0415
    import divisi_a6_gates as gates_mod  # noqa: PLC0415
    import divisi_halves  # noqa: PLC0415

    def build(out: Path, pieces: list[str], seed: str) -> None:
        sh([sys.executable, str(p1 / "build_corpus.py"), "--out", str(out), "--composers", "bach", "--divisi",
            str(manifest), "--divisi-seed", seed, "--pieces", ",".join(pieces)],
           WORK / f"build_{out.name}.log", cwd=str(repo), env=env_run)

    def render(out: Path, fonts: int, exclude: tuple[str, ...] = ()) -> None:
        extra = [x for f in exclude for x in ("--exclude-font", f)]
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

    # 3. Pieces, with the splits of the Phase 2 manifest, and the tune-group halves (frozen into halves.json).
    split_of: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        split_of[row["piece"]] = row["split"]
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
    train, val, test = select_pieces(split_of, groups, args.limit, divisi_halves.is_test_half)
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
        render(rdir, FONTS_PER_SPLIT[split], (HELD_OUT_FONT,) if split == "train" else ())
        shutil.copytree(rdir / "renders", merged, dirs_exist_ok=True)
        shutil.copy2(rdir / "render_summary.json", WORK / f"render_summary_{split}.json")
    bdir = WORK / "build"
    shutil.copytree(corpus_all / "corpus", bdir / "corpus", dirs_exist_ok=True)
    for f in corpus_all.glob("*.json"):
        shutil.copy2(f, bdir / f.name)
    status["build_render_minutes"] = round((time.time() - T0) / 60, 1)
    save_status()

    # 5. Worker check FIRST: before any test-seed build or cut, so a nondeterministic cut stops the run early.
    cut(SCRATCH / "canary_workersN", merged, canary_pages, workers)
    cut(SCRATCH / "canary_workers1", merged, canary_pages, 1)
    check = compare(digest(SCRATCH / "canary_workers1"), digest(SCRATCH / "canary_workersN"))
    status["workers1_vs_workersN"] = {**check, "workers_compared": [1, workers]}
    save_status()
    if not check["identical"]:
        abort("worker check differs: cut NOT started")

    # 6. Main cut, then the build manifest.
    cut(bdir / "out", merged, cut_limit, workers, SESSION_MINUTES - (time.time() - T0) / 60)
    cut_complete(bdir / "out", merged, "build")
    make_manifest(bdir / "out", bdir / "manifest")
    status["cut_finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_status()

    # 7. Test seeds, adaptive and frozen in test_plan.json BEFORE the first test render.
    seeds = [f"divisi-t{n}" for n in range(1, seed_cap + 1)]
    count_buckets = [b for b in gates_mod.TEST_BUCKETS if b != EXEMPT_BUCKET]
    corpus_hash = {p: rng_hash(CORPUS_SEED, p) for p in val}
    clash = sorted({(sd, p) for sd in seeds for p in val if rng_hash(sd, p) == corpus_hash[p]})
    if clash:
        abort(f"test seed RNG equals the corpus seed RNG for {len(clash)} (seed, piece) pairs, e.g. {clash[:3]}")
    plan = {
        "seeds": seeds, "cap": seed_cap,
        "rule": ("seed 1 is always paired (5 fonts). Before each further seed: phase A (paired) while any bucket "
                 f"except {EXEMPT_BUCKET} has < {need_in_font} unique in-font heads; else phase B (gootville_only: "
                 f"1 font, the 4 others excluded) while any bucket except {EXEMPT_BUCKET} has < {need_held_out} "
                 "unique Gootville heads; else stop. Counted after cut and manifest from rendered labels."),
        "time_budget": {"session_minutes": KAGGLE_SESSION_MINUTES, "reserve_minutes": TEST_RESERVE_MINUTES,
                        "rule": "no new seed if elapsed + estimated seed minutes > session - reserve",
                        "estimate": f"mean of finished seeds of the phase; first paired seed "
                                    f"{DEFAULT_PAIRED_SEED_MINUTES} min, first gootville_only seed a "
                                    f"{GOOTVILLE_SEED_FRACTION}th of the paired mean"},
        "duplicate_rule": "unique head key = (piece, voice, system, column index, chord step set, font); first seed "
                          "in seed order wins; duplicate rate reported",
        "targets": {"phase_a_unique_in_font_per_bucket": need_in_font, "phase_b_unique_gootville_per_bucket": need_held_out,
                    "exempt_bucket": EXEMPT_BUCKET},
        "test_pieces": test, "corpus_seed": CORPUS_SEED,
        "rng_hash_check": f"sha256 of the first {RNG_DRAWS} draws of Random('<seed>:<piece>'); all seeds differ from "
                          f"'{CORPUS_SEED}' for all {len(val)} val pieces",
        "dry_run_overrides": bool(dry and (args.max_test_seeds or args.phase_a_min is not None
                                           or args.phase_b_min is not None)),
    }
    plan_path = WORK / "test_plan.json"
    plan_path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    status["test_plan_sha256"] = sha256_file(plan_path)   # the plan as frozen; the outcome goes to test_plan_result.json
    save_status()
    test_dirs: list[Path] = []
    done: list[tuple[str, float]] = []
    phases: dict[str, str] = {}
    stop_reason = "cap"
    for n, seed in enumerate(seeds, start=1):
        if test_dirs:
            counts = gates_mod.unique_head_counts(test_dirs)["counts"]
            plain = {g: dict(c) for g, c in counts.items()}   # type: ignore[union-attr]
            phase = next_phase(plain, need_in_font, need_held_out, count_buckets)
            if phase is None:
                stop_reason = "targets_met"
                break
        else:
            phase = PAIRED
        elapsed = (time.time() - T0) / 60
        est = estimate_seed_minutes(done, phase)
        if elapsed + est > KAGGLE_SESSION_MINUTES - TEST_RESERVE_MINUTES:
            stop_reason = f"time_budget (elapsed {elapsed:.0f} + estimate {est:.0f} min)"
            break
        t_seed = time.time()
        tdir = SCRATCH / f"test_t{n}"
        out_dir = WORK / f"test_t{n}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / gates_mod.PHASE_FILE).write_text(json.dumps({"phase": phase, "seed": seed}), encoding="utf-8")
        build(tdir, test, seed)
        if phase == PAIRED:
            render(tdir, TEST_FONTS)
        else:
            render(tdir, 1, tuple(f for f in FONT_NAMES if f != HELD_OUT_FONT))
        left = KAGGLE_SESSION_MINUTES - TEST_RESERVE_MINUTES - (time.time() - T0) / 60
        if left <= 0:
            abort(f"test seed {seed}: no session time left for its cut (reserve {TEST_RESERVE_MINUTES} min)")
        cut(out_dir / "out", tdir / "renders", cut_limit, workers, left)   # a stuck seed stops here, not at 720 min
        cut_complete(out_dir / "out", tdir / "renders", f"test_t{n}")
        make_manifest(out_dir / "out", out_dir / "manifest")
        shutil.copytree(tdir / "corpus", out_dir / "corpus", dirs_exist_ok=True)
        for f in tdir.glob("*.json"):
            shutil.copy2(f, out_dir / f.name)
        test_dirs.append(out_dir)
        phases[seed] = phase
        done.append((phase, (time.time() - t_seed) / 60))
        rep = gates_mod.unique_head_counts(test_dirs)
        status["test_progress"] = {"seeds_run": len(test_dirs), "phases": phases,
                                   "seed_minutes": [round(m, 1) for _, m in done],
                                   "duplicate_rate": rep["duplicate_rate"]}
        save_status()
    status["test_minutes"] = round((time.time() - T0) / 60, 1)
    final = gates_mod.unique_head_counts(test_dirs)
    result = {
        "seeds_run": [d.name for d in test_dirs], "phases": phases, "stop_reason": stop_reason,
        "unique_heads": {g: dict(c) for g, c in final["counts"].items()},          # type: ignore[union-attr]
        "unique_heads_by_phase": {ph: {g: dict(c) for g, c in grp.items()}          # type: ignore[union-attr]
                                  for ph, grp in final["by_phase"].items()},        # type: ignore[union-attr]
        "chord_columns": final["chord_columns"], "duplicate_columns": final["duplicate_columns"],
        "duplicate_rate": final["duplicate_rate"],
        "manifest_sha256": {d.name: sha256_file(d / "manifest" / "phase2_manifest.jsonl") for d in test_dirs},
        "test_plan_sha256": status["test_plan_sha256"],
    }
    (WORK / "test_plan_result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    status["test_manifest_sha256"] = result["manifest_sha256"]
    status["test_stop_reason"] = stop_reason
    save_status()

    # 8. Held-out font check on the FINAL train manifests: not one Gootville chord strip may be in training.
    leaks = 0
    for mdir in (bdir, *test_dirs):
        rows = [json.loads(x) for x in
                (mdir / "manifest" / "phase2_manifest.jsonl").read_text(encoding="utf-8").splitlines() if x]
        leaks += sum(1 for r in rows if r["split"] == "train" and r["font"] == HELD_OUT_FONT)
    status["gootville_train_rows"] = leaks

    # 9. Audits: chord x-order (A3) and column collapse, then the renders archive (SVG + JSON, no PNG).
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
    if col.returncode != 0:   # a crash of the report script, not a verdict: the column report would be missing
        raise KernelError(f"column gate script exited {col.returncode}; see column_gate.json")

    # 10. Corpus gates (exit 1 on a failed or MISSING gate; UNDERPOWERED test buckets are reported, never PASS).
    gates = subprocess.run([sys.executable, str(p1 / "divisi_a6_gates.py"), "--build", str(bdir), "--test",
                            *map(str, test_dirs), "--out", str(WORK / "a6_gates.json"), "--a5-manifest",
                            str(manifest)], cwd=str(repo), env=env_run, check=False)
    status["gates_exit"] = gates.returncode
    report_path = WORK / "a6_gates.json"
    if gates.returncode not in (0, 1) or not report_path.is_file():
        raise KernelError(f"gates script crashed (exit {gates.returncode}); no verdict")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if "ok" not in report or bool(report["ok"]) != (gates.returncode == 0):
        raise KernelError(f"gate report ok={report.get('ok')!r} disagrees with exit code {gates.returncode}")
    status["failing_gates"] = [g["name"] for g in report["gates"]
                               if g["status"] not in ("pass", "warn", "not_run", "info") and not g.get("exempt")]
    status["underpowered_gates"] = [g["name"] for g in report["gates"] if g["status"] == "underpowered"]
    if leaks:
        status["failing_gates"].append(f"gootville_absent_from_train ({leaks} rows)")   # type: ignore[union-attr]
    return "ok" if report["ok"] and not leaks else "gate_fail"   # the report's verdict, cross-checked above


if __name__ == "__main__":
    sys.exit(main())
