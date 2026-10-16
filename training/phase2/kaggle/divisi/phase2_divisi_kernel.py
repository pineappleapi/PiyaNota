"""PIYA-106 divisi arm Kaggle GPU run (docs/decisions/piya-106-divisi-arm-freeze.md sections 2-5, A2, A4).

Same launcher as training/phase2/kaggle/phase2_kernel.py; only the inputs and the run table differ.
Inputs (kernel-metadata.json), nothing re-cut:
* kernel source piamac/piyanota-recut-full-1: the Phase 1 re-cut (`out/`), pinned by EXPECT_MANIFEST_SHA.
* kernel source piamac/piyanota-divisi-full-2: the divisi corpus (`out/`), pinned by EXPECT_DIVISI_MANIFEST_SHA.
* datasets piamac/cameraprimus and piamac/cpm-font-augmented2: CPM replay and the canary, as in Phase 2.
* dataset piamac/piyanota-divisi-train-code: repo.bundle (BRANCH at COMMIT) plus the Phase 2 inits
  phase2_seed{1,2}.pt, checked against INIT_SHA256 (freeze section 2: seed k starts from Phase 2 seed k).
Outputs under /kaggle/working/<run>/: run_info.json, metrics.json, summary.json, per-epoch checkpoints.
GPU numbers are not bit-reproducible (cuDNN), so both seeds are reported as a range.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

COMMIT = "22c49b24b5b132436bf629c4a9f0a94ab01f4921"  # full sha of the reviewed commit; the kernel refuses to train on anything else
BRANCH = "piya106/stroke-calibration"
CONTROL_ROWS = 6314   # A4: realised kept train chord strips of the full-2 manifest
# (output folder, seed, arm). Freeze A2 order; head-only last so the budget guard drops it first.
RUNS = (("arm_s1", 1, "arm"), ("arm_s2", 2, "arm"), ("control_s1", 1, "control"), ("control_s2", 2, "control"),
        ("head_s1", 1, "head"), ("head_s2", 2, "head"))
ARM_ARGS = {
    "arm": ["--lr", "3e-5", "--vocab-ext", "--divisi"],
    "control": ["--lr", "3e-5", "--control-rows", str(CONTROL_ROWS)],
    "head": ["--lr", "1e-3", "--vocab-ext", "--head-only", "--divisi"],
}
SESSION_BUDGET_MIN = 11 * 60        # Kaggle GPU sessions stop at 12 h and a killed session keeps no output
INIT_SHA256 = {1: "5c444ad395179dfe6751b8de032d7a34b4a3ccfccebdd7fc28e2404c624eaf93",
               2: "f79892acbcb3a410f8a55c2b4f7289354111a29a7ed439c2990cfd755cbdaed4"}
EXPECT_MANIFEST_SHA = "78165b43251f67751afc91500e812a3ce7fa06d8980a275ddadd7014d8782824"
EXPECT_DIVISI_MANIFEST_SHA = "4c369c27a2adf56e96bdf5adcb8263d8193c6dd08109011d0c388b6494c18ba6"
# Freeze section 4: 3 fixed epochs, last epoch selected, Phase 2's augmentation and replay.
TRAIN_ARGS: list[str] = ["--augment-synth", "--replay-ratio", "0.5", "--max-epochs", "3", "--select-last"]
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
    abort("COMMIT not set: put the reviewed commit sha in phase2_divisi_kernel.py before pushing")

code_dir = find_shallow("repo.bundle", want_dir=False).parent
inits = {s: code_dir / f"phase2_seed{s}.pt" for s in INIT_SHA256}
for s, p in inits.items():
    if not p.exists() or sha256_file(p) != INIT_SHA256[s]:
        abort(f"init {p.name} missing or not the deployed Phase 2 seed {s} checkpoint")
# Each output has a file the other lacks: the recut its canary digest, the divisi build its x-order audit.
recut_out = find_shallow("canary_digest.json", want_dir=False).parent / "out"
divisi_out = find_shallow("xorder_report.json", want_dir=False).parent / "out"
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
              cpm_root=str(cpm_root), cpm_font_root=str(cpm_font_root), train_args=TRAIN_ARGS, arm_args=ARM_ARGS)
save_status()
if not torch.cuda.is_available():
    abort("no GPU: enable the GPU accelerator for this kernel")

longest_min = 0.0
for name, seed, arm in RUNS:
    elapsed_min = (time.time() - T_START) / 60
    if elapsed_min + longest_min > SESSION_BUDGET_MIN:
        status["runs"][name] = {"skipped": f"budget: {elapsed_min:.0f} min used, longest run {longest_min:.0f} min"}  # type: ignore[index]
        save_status()
        continue
    out = WORK / name
    divisi = ["--divisi-recut-out", str(divisi_out), "--expect-divisi-manifest-sha", EXPECT_DIVISI_MANIFEST_SHA]
    arm_args: list[str] = []
    for x in ARM_ARGS[arm]:
        arm_args += divisi if x == "--divisi" else [x]
    cmd = [sys.executable, str(repo / "training/phase2/train_phase2.py"), "--recut-out", str(recut_out),
           "--cpm-root", str(cpm_root), "--init", str(inits[seed]), "--seed", str(seed), "--out", str(out),
           "--cpm-font-root", str(cpm_font_root), "--expect-manifest-sha", EXPECT_MANIFEST_SHA, *TRAIN_ARGS,
           *arm_args]
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
    status["runs"][name] = {"seed": seed, "arm": arm, "returncode": rc, "minutes": round(minutes, 1)}  # type: ignore[index]
    save_status()
    print(f"{name}: rc {rc}, {minutes:.0f} min", flush=True)
status["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
save_status()
