"""PIYA-106 A6 divisi Kaggle GPU run (freeze doc A6; plan docs/superpowers/plans/2026-10-18-divisi-a6.md Task 9).

Same launcher as the train-1 kernel (`../divisi/phase2_divisi_kernel.py`); what changed:
* one arm, two seeds, 8 epochs, divisi share 0.20, Gootville held out of the divisi train rows;
* the divisi corpus is the A6 build kernel's `build/out/` (not `out/`), and its `halves.json` is passed so the
  per-epoch divisi val scores only the tuning half (test-half pieces are never scored during training).
Inputs (kernel-metadata.json), nothing re-cut:
* kernel source piamac/piyanota-recut-full-1: the Phase 1 re-cut (`out/`), pinned by EXPECT_MANIFEST_SHA.
* kernel source piamac/piyanota-divisi-a6-build: the A6 corpus, pinned by EXPECT_DIVISI_MANIFEST_SHA (the sha256 of
  the build's own build/manifest/phase2_manifest.jsonl, which train_phase2 rebuilds byte for byte).
* datasets piamac/cameraprimus and piamac/cpm-font-augmented2: CPM replay and the canary, as in Phase 2.
* dataset piamac/piyanota-divisi-a6-train-code: repo.bundle (BRANCH at COMMIT) plus the Phase 2 inits
  phase2_seed{1,2}.pt, checked against INIT_SHA256 (seed k starts from Phase 2 seed k, as in train-1).
Outputs under /kaggle/working/<run>/: run_info.json, metrics.json, summary.json, per-epoch checkpoints (epoch
selection is offline, eval_divisi_a6.py on the tuning half). GPU numbers are not bit-reproducible (cuDNN), so both
seeds are reported as a range.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

COMMIT = "169d4f0a81d8945d1c38f9d01d562f1081a22d8f"  # full sha of the reviewed commit; the kernel refuses to train on anything else
BRANCH = "piya106/stroke-calibration"
# (output folder, seed). One session: train-1's arm took ~29 min/epoch on a 54.6k-strip epoch; A6's is 55.9k
# (30311 Phase 1 + 7578 divisi + 17980 CPM, replay capped at the pool), so 2 x 8 epochs is ~8 h of the 11 h budget.
# v1 (2026-10-21) ran a6_s1 in 560 min and skipped a6_s2 on budget; v2 runs a6_s2 alone in its own session.
RUNS = (("a6_s2", 2),)
SESSION_BUDGET_MIN = 11 * 60        # Kaggle GPU sessions stop at 12 h and a killed session keeps no output
INIT_SHA256 = {1: "5c444ad395179dfe6751b8de032d7a34b4a3ccfccebdd7fc28e2404c624eaf93",
               2: "f79892acbcb3a410f8a55c2b4f7289354111a29a7ed439c2990cfd755cbdaed4"}
EXPECT_MANIFEST_SHA = "78165b43251f67751afc91500e812a3ce7fa06d8980a275ddadd7014d8782824"
EXPECT_DIVISI_MANIFEST_SHA = "deb09dcf6422950b3fecfd374aca2d883c6cbc3d45e5e9236e25bed8b809c1b3"   # A6 build v2
# A6: 8 fixed epochs, every epoch checkpointed, last-epoch flag (selection is offline on the tuning half).
TRAIN_ARGS: list[str] = ["--augment-synth", "--replay-ratio", "0.5", "--max-epochs", "8", "--select-last", "--lr", "3e-5",
                         "--vocab-ext", "--divisi-share", "0.20", "--holdout-chord-font", "Gootville"]
CPM_FONTS = ("Bravura", "Gootville", "Leland", "Petaluma")
INPUT = Path("/kaggle/input")
SEARCH_DEPTH = 5                    # shallow globs only: CPM alone holds ~87k files
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/phase2")
STATUS = WORK / "kernel_status.json"
status: dict[str, object] = {"commit": COMMIT, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "runs": {}}
T_START = time.time()


def save_status() -> None:
    STATUS.write_text(json.dumps(status, indent=1), encoding="utf-8")


def abort(msg: str) -> None:
    status["aborted"] = msg
    save_status()
    raise SystemExit(msg)


def sh(cmd: list[str], **kw: object) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def find_shallow(name: str, want_dir: bool) -> Path:
    for depth in range(1, SEARCH_DEPTH + 1):
        hits = sorted(p for p in INPUT.glob("/".join(["*"] * (depth - 1) + [name])) if p.is_dir() == want_dir)
        if hits:
            return hits[0]
    abort(f"{name} not found under {INPUT} (depth {SEARCH_DEPTH})")
    raise AssertionError("unreachable")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


if COMMIT.startswith("SET_"):
    abort("COMMIT not set: put the reviewed commit sha in phase2_divisi_a6_kernel.py before pushing")

code_dir = find_shallow("repo.bundle", want_dir=False).parent
inits = {s: code_dir / f"phase2_seed{s}.pt" for s in INIT_SHA256}
for s, p in inits.items():
    if not p.exists() or sha256_file(p) != INIT_SHA256[s]:
        abort(f"init {p.name} missing or not the deployed Phase 2 seed {s} checkpoint")
# Each output has a file the other lacks: the recut its canary digest, the A6 build its x-order audit.
recut_out = find_shallow("canary_digest.json", want_dir=False).parent / "out"
a6_root = find_shallow("xorder_report.json", want_dir=False).parent
divisi_out = a6_root / "build" / "out"
halves = a6_root / "halves.json"
if not halves.is_file():
    abort(f"input incomplete: {halves}")
cpm_root = find_shallow("CameraPrIMuS - Copy", want_dir=True)
cpm_font_root = find_shallow("cpm-font-augmented2", want_dir=True)
for p in (recut_out / "pages", recut_out / "strips", divisi_out / "pages", divisi_out / "strips",
          *(cpm_font_root / f for f in CPM_FONTS)):
    if not p.is_dir():
        abort(f"input incomplete: {p}")

repo = SCRATCH / "repo"
SCRATCH.mkdir(parents=True, exist_ok=True)
sh(["git", "clone", "-q", "-b", BRANCH, str(code_dir / "repo.bundle"), str(repo)],
   env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"})
head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=True).stdout.strip()
if head != COMMIT:
    abort(f"bundle HEAD {head} != reviewed commit {COMMIT}")

import torch  # noqa: E402  (Kaggle's preinstalled CUDA build; versions recorded, not re-pinned)

status.update(torch=torch.__version__, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0)
              if torch.cuda.is_available() else None, recut_out=str(recut_out), divisi_out=str(divisi_out),
              cpm_root=str(cpm_root), cpm_font_root=str(cpm_font_root), halves=str(halves), train_args=TRAIN_ARGS)
save_status()
if not torch.cuda.is_available():
    abort("no GPU: enable the GPU accelerator for this kernel")

longest_min = 0.0
for name, seed in RUNS:
    elapsed_min = (time.time() - T_START) / 60
    if elapsed_min + longest_min > SESSION_BUDGET_MIN:
        status["runs"][name] = {"skipped": f"budget: {elapsed_min:.0f} min used, longest run {longest_min:.0f} min"}  # type: ignore[index]
        save_status()
        continue
    out = WORK / name
    cmd = [sys.executable, str(repo / "training/phase2/train_phase2.py"), "--recut-out", str(recut_out),
           "--cpm-root", str(cpm_root), "--init", str(inits[seed]), "--seed", str(seed), "--out", str(out),
           "--cpm-font-root", str(cpm_font_root), "--expect-manifest-sha", EXPECT_MANIFEST_SHA, *TRAIN_ARGS,
           "--divisi-recut-out", str(divisi_out), "--expect-divisi-manifest-sha", EXPECT_DIVISI_MANIFEST_SHA,
           "--halves", str(halves)]
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with (out / "train.log").open("w", encoding="utf-8") as log:
        try:
            # Every epoch checkpoint is saved, so a run stopped by the budget still leaves usable output.
            rc: int | str = subprocess.run(cmd, cwd=str(repo), env={**os.environ, "PYTHONUTF8": "1"}, stdout=log,
                                           stderr=subprocess.STDOUT,
                                           timeout=(SESSION_BUDGET_MIN - elapsed_min) * 60).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout_budget"
    minutes = (time.time() - t0) / 60
    longest_min = max(longest_min, minutes)
    status["runs"][name] = {"seed": seed, "returncode": rc, "minutes": round(minutes, 1)}  # type: ignore[index]
    save_status()
    print(f"{name}: rc {rc}, {minutes:.0f} min", flush=True)
status["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
save_status()
