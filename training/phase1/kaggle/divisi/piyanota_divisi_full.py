"""PIYA-106 divisi arm: build, render and cut the full divisi corpus on Kaggle CPU (freeze build order step 5).

One launch. The user moved the build off the dev PC (2026-10-16) because the host kills large local jobs for low
memory. Steps:
1. Pinned environment: the recut pins plus music21 and Verovio at the dev PC versions the G1/G1b checks ran on.
2. G1b parity canary: the 12 G1b pieces are rebuilt and re-rendered in all 5 fonts and must match the reviewed
   dev-PC build (MEI after id/date normalisation, plan.json without `source`, every labels.json, every check
   pass). Any difference aborts before the full build, because the user-approved G1b would no longer describe it.
3. Build train and val separately (`--pieces`), render train in 2 fonts and val in 5 (freeze section 3), merge.
4. Cut, after the recut's 1-vs-N worker check on 5 pages. Then the chord x-order audit (A3) on the merged renders.
5. Outputs: out/ (cut strips), corpus_{train,val}/ (MEI, plans, logs, divisi summaries), render summaries,
   renders_svg.tar.gz (SVG + JSON, no PNG), xorder_report.json, kernel_status.json.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

COMMIT = "0ebc5321fce7085cbfb76053e18d08411cd75f56"
BRANCH = "piya106/stroke-calibration"
WORKERS = 4
CANARY_PAGES = 5
SESSION_MINUTES = 700       # of Kaggle's 12 h; the cut stops starting pages when this is used up
PINS = ["numpy==2.5.3", "opencv-python==5.0.0.93", "scipy==1.16.3", "pillow==12.3.0", "psutil==7.2.2",
        "fonttools==4.61.0", "resvg_py==0.5.0", "ultralytics==8.4.144", "music21==10.5.0", "verovio==6.3.0"]
TORCH_PINS = ["torch==2.6.0", "torchvision==0.21.0"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
OPENCV_VARIANTS = ["opencv-python", "opencv-python-headless", "opencv-contrib-python",
                   "opencv-contrib-python-headless"]
G1B_PIECES = ["bach_bwv104.6", "bach_bwv165.6", "bach_bwv177.5", "bach_bwv244.40", "bach_bwv280", "bach_bwv281",
              "bach_bwv340", "bach_bwv342", "bach_bwv363", "bach_bwv367", "bach_bwv399", "bach_bwv427"]
FONTS_PER_SPLIT = {"train": 2, "val": 5}

WORK = Path("/kaggle/working")
OUT = WORK / "out"
SCRATCH = Path("/tmp/divisi")
STATUS = WORK / "kernel_status.json"
T0 = time.time()
status: dict[str, object] = {"commit": COMMIT, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def save_status() -> None:
    STATUS.write_text(json.dumps(status, indent=1), encoding="utf-8")


def abort(msg: str) -> None:
    status["aborted"] = msg
    save_status()
    raise SystemExit(msg)


def sh(cmd: list[str], log: Path | None = None, **kw: object) -> None:
    print("+", " ".join(cmd[:8]), "..." if len(cmd) > 8 else "", flush=True)
    if log is None:
        subprocess.run(cmd, check=True, **kw)
        return
    with log.open("a", encoding="utf-8") as f:
        subprocess.run(cmd, check=True, stdout=f, stderr=subprocess.STDOUT, **kw)


def find_one(name: str) -> Path:
    hits = sorted(Path("/kaggle/input").rglob(name))
    if not hits:
        abort(f"{name} not found under /kaggle/input")
    return hits[0]


# 1. Pinned environment.
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
manifest = code_dir / "phase2_manifest.jsonl"
# Kaggle unpacks uploaded archives into a folder of the same name; take the archive only if it is still there.
if (code_dir / "g1b_ref.tar.gz").is_file():
    with tarfile.open(code_dir / "g1b_ref.tar.gz") as t:
        t.extractall(SCRATCH, filter="data")
    g1b_ref = SCRATCH / "g1b_ref"
else:
    refs = [p.parent for p in Path("/kaggle/input").rglob("corpus")
            if p.parent.name == "g1b_ref" and (p.parent / "renders").is_dir()]
    if len(refs) != 1:
        abort(f"G1b reference not found unambiguously: {refs}")
    g1b_ref = refs[0]

sys.path.insert(0, str(code_dir))
from parity_digest import compare, digest  # noqa: E402

env_run = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "PYTHONUTF8": "1"}
P1 = repo / "training" / "phase1"


def build(out: Path, pieces: list[str]) -> None:
    sh([sys.executable, str(P1 / "build_corpus.py"), "--out", str(out), "--composers", "bach", "--divisi",
        str(manifest), "--pieces", ",".join(pieces)], WORK / f"build_{out.name}.log", cwd=str(repo), env=env_run)


def render(out: Path, fonts: int) -> None:
    sh([sys.executable, str(P1 / "render_corpus.py"), "--out", str(out), "--composers", "bach", "--fonts-per-piece",
        str(fonts), "--vocab-ext"], WORK / f"render_{out.name}.log", cwd=str(repo), env=env_run)


# Verovio writes random xml:ids and the build date into every MEI (freeze section 10, flag-off identity method).
ID = re.compile(r'xml:id="([^"]+)"')
DATE = re.compile(r'(isodate|<date)[^>]*>[^<]*|isodate="[^"]*"')


def norm_mei(text: str) -> str:
    ids: dict[str, str] = {}
    for m in ID.finditer(text):
        ids.setdefault(m.group(1), f"id{len(ids)}")
    return DATE.sub("DATE", re.sub(r"[\w-]+", lambda m: ids.get(m.group(), m.group()), text))


def g1b_diff(built: Path, ref: Path) -> list[str]:
    bad = []
    for r in sorted((ref / "corpus").iterdir()):
        b = built / "corpus" / r.name
        if not b.exists():
            bad.append(f"missing {r.name}")
        elif r.suffix == ".mei" and norm_mei(r.read_text(encoding="utf-8")) != norm_mei(b.read_text(encoding="utf-8")):
            bad.append(r.name)
        elif r.name.endswith(".plan.json"):
            ja, jb = (json.loads(p.read_text(encoding="utf-8")) for p in (r, b))
            if {k: v for k, v in ja.items() if k != "source"} != {k: v for k, v in jb.items() if k != "source"}:
                bad.append(r.name)
    for r in sorted((ref / "renders").rglob("labels.json")):
        rel = r.relative_to(ref)
        b = built / rel
        if not b.exists() or json.loads(r.read_text(encoding="utf-8")) != json.loads(b.read_text(encoding="utf-8")):
            bad.append(str(rel))
        elif not json.loads((b.parent / "check.json").read_text(encoding="utf-8"))["pass"]:
            bad.append(f"{rel.parent} check failed")
    return bad


# 3. G1b parity canary.
canary = SCRATCH / "g1b_canary"
build(canary, G1B_PIECES)
render(canary, 5)
diff = g1b_diff(canary, g1b_ref)
status["g1b_parity"] = {"identical": not diff, "differences": diff[:30], "n_differences": len(diff)}
save_status()
if diff:
    abort("G1b canary differs from the reviewed dev-PC build: full build NOT started")

# 4. Full build and render.
split_of: dict[str, str] = {}
for line in manifest.read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    split_of[row["piece"]] = row["split"]
merged = SCRATCH / "renders"
for split, fonts in FONTS_PER_SPLIT.items():
    out = SCRATCH / f"corpus_{split}"
    build(out, sorted(p for p, s in split_of.items() if s == split))
    render(out, fonts)
    shutil.copytree(out / "renders", merged, dirs_exist_ok=True)
    keep = WORK / f"corpus_{split}"
    shutil.copytree(out / "corpus", keep / "corpus")
    for f in out.glob("*.json"):
        shutil.copy2(f, keep / f.name)
status["build_render_minutes"] = round((time.time() - T0) / 60, 1)
save_status()


def cut(out: Path, limit: int, workers: int, max_minutes: float = 0.0) -> None:
    cmd = [sys.executable, str(P1 / "cut_corpus.py"), "run", "--out", str(out), "--renders", str(merged),
           "--yolo", str(code_dir / "best.pt"), "--camera", str(code_dir / "camera_page_stats.json"), "--stats",
           "--workers", str(workers)]
    if limit:
        cmd += ["--limit", str(limit)]
    if max_minutes:
        cmd += ["--max-minutes", str(max_minutes)]
    sh(cmd, WORK / f"{out.name}.log", cwd=str(repo), env=env_run)


# 5. Worker check, cut, x-order audit.
cut(SCRATCH / "canary_workersN", CANARY_PAGES, WORKERS)
cut(SCRATCH / "canary_workers1", CANARY_PAGES, 1)
check = compare(digest(SCRATCH / "canary_workers1"), digest(SCRATCH / "canary_workersN"))
status["workers1_vs_workersN"] = check
if not check["identical"]:
    abort("worker check differs: cut NOT started")
cut(OUT, 0, WORKERS, SESSION_MINUTES - (time.time() - T0) / 60)
pages = sorted((OUT / "pages").rglob("*.json")) if (OUT / "pages").exists() else []
status.update({"pages_cut": len(pages), "cut_finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
save_status()
sh([sys.executable, str(P1 / "chord_xorder_audit.py"), "--renders", str(merged), "--out",
    str(WORK / "xorder_report.json")], cwd=str(repo), env=env_run)
with tarfile.open(WORK / "renders_svg.tar.gz", "w:gz") as t:
    for f in sorted(merged.rglob("*")):
        if f.is_file() and f.suffix in (".svg", ".json"):
            t.add(f, arcname=str(Path("renders") / f.relative_to(merged)))
status["total_minutes"] = round((time.time() - T0) / 60, 1)
save_status()
print(json.dumps(status, indent=1))
