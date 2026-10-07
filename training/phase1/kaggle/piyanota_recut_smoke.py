"""PIYA-106 Phase 1 Kaggle re-cut, smoke session (amendments 2026-10-07 and 2026-10-07b).

Kaggle CPU is the single platform (BUG-046), so there is no local comparison. Each step uses its own
/kaggle/working folder:
1. workersN and workers1: the first 5 smoke pages (seed 20261011, round robin by font), cut with WORKERS workers
   and with 1 worker. Every file must be identical (a precondition, not a gate result). workersN's digest is saved
   as canary_digest.json, which every later launch of the run must reproduce.
2. smoke120: the pre-registered 120-page smoke, run ONLY if the worker check is identical. Otherwise nothing is run,
   so the one-attempt smoke is not spent.
The gate report is run locally afterwards on the downloaded output. Everything runs on CPU.
"""
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

COMMIT = "2d3c8964c62b03c2b1e18979921577b7ec49ff52"
BRANCH = "piya106/stroke-calibration"
WORKERS = 4
SMOKE_PAGES = 120
WORKER_CHECK_PAGES = 5
PINS = ["numpy==2.5.3", "opencv-python==5.0.0.93", "scipy==1.16.3", "pillow==12.3.0", "psutil==7.2.2",
        "fonttools==4.61.0", "resvg_py==0.5.0", "ultralytics==8.4.144"]
TORCH_PINS = ["torch==2.6.0", "torchvision==0.21.0"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
OPENCV_VARIANTS = ["opencv-python", "opencv-python-headless", "opencv-contrib-python",
                   "opencv-contrib-python-headless"]

WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/recut")
STATUS = WORK / "kernel_status.json"
status: dict[str, object] = {"commit": COMMIT, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def save_status() -> None:
    STATUS.write_text(json.dumps(status, indent=1), encoding="utf-8")


def sh(cmd: list[str], **kw: object) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def find_one(name: str) -> Path:
    hits = sorted(Path("/kaggle/input").rglob(name))
    if not hits:
        raise SystemExit(f"{name} not found under /kaggle/input")
    return hits[0]


# 1. Pinned environment (same versions as the local reference; torch CPU build).
sh([sys.executable, "-m", "pip", "uninstall", "-y", "-q", *OPENCV_VARIANTS])
sh([sys.executable, "-m", "pip", "install", "-q", *TORCH_PINS, "--index-url", TORCH_INDEX])
sh([sys.executable, "-m", "pip", "install", "-q", *PINS])

# 2. Code at the reviewed commit; LFS pointers are not needed (weights come from the dataset).
code_dir = find_one("repo.bundle").parent
repo = SCRATCH / "repo"
SCRATCH.mkdir(parents=True, exist_ok=True)
env_git = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
sh(["git", "clone", "-q", "-b", BRANCH, str(code_dir / "repo.bundle"), str(repo)], env=env_git)
head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=True).stdout.strip()
if head != COMMIT:
    raise SystemExit(f"bundle HEAD {head} != reviewed commit {COMMIT}")

# 3. Renders (the dataset may hold the tarball or an already-extracted folder).
tar_hits = sorted(Path("/kaggle/input").rglob("renders.tar.gz"))
if tar_hits:
    with tarfile.open(tar_hits[0]) as t:
        t.extractall(SCRATCH, filter="data")
    renders = SCRATCH / "renders"
else:
    renders = find_one("meta.json").parents[2]
status["renders"] = str(renders)
save_status()

sys.path.insert(0, str(code_dir))
from parity_digest import compare, digest  # noqa: E402

env_run = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "PYTHONUTF8": "1"}


def cut(out: Path, limit: int, workers: int) -> None:
    cmd = [sys.executable, str(repo / "training/phase1/cut_corpus.py"), "run", "--out", str(out),
           "--renders", str(renders), "--yolo", str(code_dir / "best.pt"),
           "--camera", str(code_dir / "camera_page_stats.json"), "--smoke", str(SMOKE_PAGES), "--stats",
           "--workers", str(workers)]
    if limit:
        cmd += ["--limit", str(limit)]
    with (WORK / f"{out.name}.log").open("w", encoding="utf-8") as log:
        sh(cmd, cwd=str(repo), env=env_run, stdout=log, stderr=subprocess.STDOUT)


# 4. Amendment 2026-10-07b: Kaggle is the single platform (BUG-046), so no local comparison. Worker count must not
# change any output file in this session.
cut(WORK / "workersN", WORKER_CHECK_PAGES, WORKERS)
cut(WORK / "workers1", WORKER_CHECK_PAGES, 1)
status["workers1_vs_workersN"] = compare(digest(WORK / "workers1"), digest(WORK / "workersN"))
# The canary for every later launch of this run (amendment 2026-10-07b): its 5 pages must re-cut to these bytes.
(WORK / "canary_digest.json").write_text(json.dumps(digest(WORK / "workersN"), indent=1, sort_keys=True),
                                         encoding="utf-8")
save_status()

# 5. The smoke, only if the worker check is identical.
ok = status["workers1_vs_workersN"]["identical"]
status["smoke_run"] = bool(ok)
save_status()
if ok:
    cut(WORK / "smoke120", 0, WORKERS)
    status["smoke_finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
else:
    print("worker check differs: smoke NOT run", flush=True)
save_status()
print(json.dumps(status, indent=1))
