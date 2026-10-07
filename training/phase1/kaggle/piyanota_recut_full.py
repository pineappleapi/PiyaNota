"""PIYA-106 Phase 1 Kaggle re-cut, full run, one launch of a chain (amendment 2026-10-07b + smoke review 2026-10-08).

Kaggle CPU is the single platform (BUG-046). The full corpus does not fit one 12 h session, so launches are chained:
launch k takes launch k-1's output as a kernel source, copies it to /kaggle/working/out and resumes (pages that
already have a result are skipped by `cut_corpus.py run`).
* Launch 1 (no previous output found): the first CANARY_PAGES pages are cut with WORKERS workers and with 1 worker;
  every file must be identical, else the launch aborts. The WORKERS digest is saved as canary_digest.json.
* Every later launch first re-cuts the canary pages and must reproduce canary_digest.json byte-for-byte, else it
  aborts before cutting anything (smoke review condition 4: hard abort, not a warning).
* Each launch records the page keys it cut (launch_pages_k.txt) so the gate can be evaluated per chunk.
* Optional backup: if the Kaggle Secret `rclone_conf` (an rclone.conf with a Drive remote named `gdrive`) is attached,
  the cumulative output is copied to gdrive:PiyaNota/recut_full. Without it the copy is skipped; Kaggle's own output
  stays the primary copy. The config is written to /tmp only and never printed.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

COMMIT = "0498b4942b0a4e58dfe2a7b1c298ae2cf7e5e1fc"
BRANCH = "piya106/stroke-calibration"
WORKERS = 4
CANARY_PAGES = 5
MAX_MINUTES = 630           # cutting budget; leaves ~1.5 h of the 12 h session for setup, canary, backup and save
PINS = ["numpy==2.5.3", "opencv-python==5.0.0.93", "scipy==1.16.3", "pillow==12.3.0", "psutil==7.2.2",
        "fonttools==4.61.0", "resvg_py==0.5.0", "ultralytics==8.4.144"]
TORCH_PINS = ["torch==2.6.0", "torchvision==0.21.0"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
OPENCV_VARIANTS = ["opencv-python", "opencv-python-headless", "opencv-contrib-python",
                   "opencv-contrib-python-headless"]
RCLONE_ZIP = "https://downloads.rclone.org/rclone-current-linux-amd64.zip"   # backup tool only; not pinned
DRIVE_DEST = "gdrive:PiyaNota/recut_full"

WORK = Path("/kaggle/working")
OUT = WORK / "out"
SCRATCH = Path("/tmp/recut")
STATUS = WORK / "kernel_status.json"
status: dict[str, object] = {"commit": COMMIT, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def save_status() -> None:
    STATUS.write_text(json.dumps(status, indent=1), encoding="utf-8")


def abort(msg: str) -> None:
    status["aborted"] = msg
    save_status()
    raise SystemExit(msg)


def sh(cmd: list[str], **kw: object) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def find_one(name: str) -> Path:
    hits = sorted(Path("/kaggle/input").rglob(name))
    if not hits:
        abort(f"{name} not found under /kaggle/input")
    return hits[0]


def page_keys(out: Path) -> set[str]:
    return {str(p.relative_to(out / "pages")) for p in (out / "pages").rglob("*.json")} if (out / "pages").exists() \
        else set()


# 1. Pinned environment (same versions as the smoke).
sh([sys.executable, "-m", "pip", "uninstall", "-y", "-q", *OPENCV_VARIANTS])
sh([sys.executable, "-m", "pip", "install", "-q", *TORCH_PINS, "--index-url", TORCH_INDEX])
sh([sys.executable, "-m", "pip", "install", "-q", *PINS])

# 2. Code at the reviewed commit.
code_dir = find_one("repo.bundle").parent
repo = SCRATCH / "repo"
SCRATCH.mkdir(parents=True, exist_ok=True)
sh(["git", "clone", "-q", "-b", BRANCH, str(code_dir / "repo.bundle"), str(repo)],
   env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"})
head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=True).stdout.strip()
if head != COMMIT:
    abort(f"bundle HEAD {head} != reviewed commit {COMMIT}")

# 3. Renders.
tar_hits = sorted(Path("/kaggle/input").rglob("renders.tar.gz"))
if tar_hits:
    with tarfile.open(tar_hits[0]) as t:
        t.extractall(SCRATCH, filter="data")
    renders = SCRATCH / "renders"
else:
    renders = find_one("meta.json").parents[2]

sys.path.insert(0, str(code_dir))
from parity_digest import compare, digest  # noqa: E402

env_run = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "PYTHONUTF8": "1"}


def cut(out: Path, limit: int, workers: int, max_minutes: float = 0.0) -> None:
    cmd = [sys.executable, str(repo / "training/phase1/cut_corpus.py"), "run", "--out", str(out),
           "--renders", str(renders), "--yolo", str(code_dir / "best.pt"),
           "--camera", str(code_dir / "camera_page_stats.json"), "--stats", "--workers", str(workers)]
    if limit:
        cmd += ["--limit", str(limit)]
    if max_minutes:
        cmd += ["--max-minutes", str(max_minutes)]
    with (WORK / f"{out.name}.log").open("a", encoding="utf-8") as log:
        sh(cmd, cwd=str(repo), env=env_run, stdout=log, stderr=subprocess.STDOUT)


# 4. Launch number and canary.
prev = sorted(Path("/kaggle/input").rglob("canary_digest.json"))
if not prev:
    status["launch"] = 1
    cut(SCRATCH / "canary_workersN", CANARY_PAGES, WORKERS)
    cut(SCRATCH / "canary_workers1", CANARY_PAGES, 1)
    check = compare(digest(SCRATCH / "canary_workers1"), digest(SCRATCH / "canary_workersN"))
    status["workers1_vs_workersN"] = check
    if not check["identical"]:
        abort("worker check differs: run NOT started")
    canary = digest(SCRATCH / "canary_workersN")
    (WORK / "canary_digest.json").write_text(json.dumps(canary, indent=1, sort_keys=True), encoding="utf-8")
else:
    prev_dir = prev[0].parent
    prev_status = json.loads((prev_dir / "kernel_status.json").read_text(encoding="utf-8"))
    status["launch"] = int(prev_status["launch"]) + 1
    if prev_status.get("commit") != COMMIT:
        abort(f"previous launch commit {prev_status.get('commit')} != {COMMIT}")
    cut(SCRATCH / "canary_rerun", CANARY_PAGES, WORKERS)
    canary = json.loads(prev[0].read_text(encoding="utf-8"))
    check = compare(digest(SCRATCH / "canary_rerun"), canary)
    status["canary_vs_launch1"] = check
    if not check["identical"]:
        abort("canary differs from launch 1: run NOT resumed")
    shutil.copy2(prev[0], WORK / "canary_digest.json")
    for f in prev_dir.glob("launch_pages_*.txt"):
        shutil.copy2(f, WORK / f.name)
    shutil.copytree(prev_dir / "out", OUT)
status["canary_sha256"] = hashlib.sha256((WORK / "canary_digest.json").read_bytes()).hexdigest()
save_status()

# 5. The run (resumes; stops starting pages after MAX_MINUTES).
before = page_keys(OUT)
cut(OUT, 0, WORKERS, MAX_MINUTES)
new = sorted(page_keys(OUT) - before)
(WORK / f"launch_pages_{status['launch']}.txt").write_text("\n".join(new) + "\n", encoding="utf-8")
status.update({"pages_before": len(before), "pages_this_launch": len(new), "pages_total": len(before) + len(new),
               "cut_finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
save_status()

# 6. Optional Drive backup; a failure here never fails the launch.
try:
    from kaggle_secrets import UserSecretsClient  # noqa: PLC0415  (Kaggle-only)
    conf = UserSecretsClient().get_secret("rclone_conf")
except Exception as e:  # noqa: BLE001  (secret absent or not attached: the backup is optional by design)
    status["drive_backup"] = f"skipped: secret unavailable ({type(e).__name__})"
else:
    try:
        conf_path = Path("/tmp/rclone.conf")
        conf_path.write_text(conf, encoding="utf-8")
        conf_path.chmod(0o600)
        urllib.request.urlretrieve(RCLONE_ZIP, "/tmp/rclone.zip")
        with zipfile.ZipFile("/tmp/rclone.zip") as z:
            member = next(n for n in z.namelist() if n.endswith("/rclone"))
            Path("/tmp/rclone").write_bytes(z.read(member))
        Path("/tmp/rclone").chmod(0o755)
        for src, dst in ((OUT, f"{DRIVE_DEST}/out"), (WORK, DRIVE_DEST)):
            args = ["/tmp/rclone", "--config", str(conf_path), "copy", str(src), dst, "--transfers", "8"]
            if src == WORK:
                args += ["--max-depth", "1"]
            subprocess.run(args, check=True)
        status["drive_backup"] = f"copied to {DRIVE_DEST}"
    except (OSError, subprocess.CalledProcessError, StopIteration, zipfile.BadZipFile) as e:
        status["drive_backup"] = f"failed: {type(e).__name__}"
    finally:
        Path("/tmp/rclone.conf").unlink(missing_ok=True)
save_status()
print(json.dumps(status, indent=1))
