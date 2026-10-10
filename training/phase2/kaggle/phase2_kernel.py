"""PIYA-106 Phase 2 Kaggle GPU run: training/phase2/train_phase2.py for each seed, on the frozen Phase 1 re-cut.

Inputs (kernel-metadata.json), nothing re-uploaded:
* kernel source piamac/piyanota-recut-full-1: the re-cut output (`out/pages`, `out/strips`), mounted read-only.
  train_phase2 rebuilds the manifest from it and must reproduce EXPECT_MANIFEST_SHA (built locally from the frozen
  copy, D:/PiyaNota/datasets/phase2_manifest), else it stops before training.
* dataset piamac/cameraprimus: CPM replay and the canary (first 10% of the sorted glob, as in the notebook).
* dataset piamac/piyanota-phase2-code: repo.bundle (git bundle of BRANCH) plus the init checkpoint INIT_NAME.
  The kernel clones the bundle and aborts unless HEAD == COMMIT, so only reviewed code trains.
Outputs under /kaggle/working/<run name from RUNS>/: run_info.json, metrics.json (every epoch), summary.json, per-epoch and best
checkpoints. Fetch only what G2 needs with training/phase1/kaggle/fetch_output.py --pattern (see the runbook).
GPU numbers are not bit-reproducible (cuDNN; see CLAUDE.md), so both seeds are reported as a range.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

COMMIT = "SET_TO_REVIEWED_COMMIT"   # full sha of the reviewed commit; the kernel refuses to train on anything else
BRANCH = "piya106/stroke-calibration"
# (output folder, seed, drop camera augmentation). The aug-off seed-1 arm is ml-cv-lead's P5 condition before any G2
# gain is credited to augmentation. Runs go in order; edit this tuple (no new bundle needed) to rerun a skipped one.
RUNS = (("seed1", 1, False), ("seed2", 2, False), ("seed1_noaug", 1, True))
SESSION_BUDGET_MIN = 11 * 60        # Kaggle GPU sessions stop at 12 h and a killed session keeps no output
INIT_NAME = "crnn_cameraprimus_transcription.pt"   # P5 decision; any file name inside the code dataset
EXPECT_MANIFEST_SHA = "78165b43251f67751afc91500e812a3ce7fa06d8980a275ddadd7014d8782824"   # tune-grouped split
# ml-cv-lead P5 ruling (2026-10-11): CPM base init for both seeds, camera augmentation on, font-rerendered CPM in the
# replay pool. --cpm-font-root is appended below because its path is only known once the inputs are mounted.
TRAIN_ARGS: list[str] = ["--augment-synth", "--replay-ratio", "0.5", "--lr", "3e-5", "--max-epochs", "6",
                         "--patience", "3"]
CPM_FONTS = ("Bravura", "Gootville", "Leland", "Petaluma")   # the step-1 renders; Leland is no longer a LOFO probe
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


if COMMIT.startswith("SET_"):
    abort("COMMIT not set: put the reviewed commit sha in phase2_kernel.py before pushing")

code_dir = find_shallow("repo.bundle", want_dir=False).parent
init_ckpt = code_dir / INIT_NAME
if not init_ckpt.exists():
    abort(f"init checkpoint {INIT_NAME} missing from the code dataset")
recut_out = find_shallow("canary_digest.json", want_dir=False).parent / "out"
cpm_root = find_shallow("CameraPrIMuS - Copy", want_dir=True)
# Mounted as /kaggle/input/cpm-font-augmented2 or /kaggle/input/datasets/piamac/cpm-font-augmented2 (the notebook's
# path); the font folders sit directly under it.
cpm_font_root = find_shallow("cpm-font-augmented2", want_dir=True)
for p in (recut_out / "pages", recut_out / "strips", *(cpm_font_root / f for f in CPM_FONTS)):
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
              if torch.cuda.is_available() else None, recut_out=str(recut_out), cpm_root=str(cpm_root),
              cpm_font_root=str(cpm_font_root),
              init=INIT_NAME, train_args=TRAIN_ARGS)
save_status()
if not torch.cuda.is_available():
    abort("no GPU: enable the GPU accelerator for this kernel")

longest_min = 0.0
for name, seed, no_aug in RUNS:
    elapsed_min = (time.time() - T_START) / 60
    if elapsed_min + longest_min > SESSION_BUDGET_MIN:
        status["runs"][name] = {"skipped": f"budget: {elapsed_min:.0f} min used, longest run {longest_min:.0f} min"}  # type: ignore[index]
        save_status()
        continue
    out = WORK / name
    args = [a for a in TRAIN_ARGS if not (no_aug and a == "--augment-synth")]
    cmd = [sys.executable, str(repo / "training/phase2/train_phase2.py"), "--recut-out", str(recut_out),
           "--cpm-root", str(cpm_root), "--init", str(init_ckpt), "--seed", str(seed), "--out", str(out),
           "--cpm-font-root", str(cpm_font_root), "--expect-manifest-sha", EXPECT_MANIFEST_SHA, *args]
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with (out / "train.log").open("w", encoding="utf-8") as log:
        try:
            # The best checkpoint is saved every epoch, so a run stopped by the budget still leaves usable output.
            rc: int | str = subprocess.run(cmd, cwd=str(repo), env={**os.environ, "PYTHONUTF8": "1"}, stdout=log,
                                           stderr=subprocess.STDOUT,
                                           timeout=(SESSION_BUDGET_MIN - elapsed_min) * 60).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout_budget"
    minutes = (time.time() - t0) / 60
    longest_min = max(longest_min, minutes)
    status["runs"][name] = {"seed": seed, "augment_synth": not no_aug, "returncode": rc,  # type: ignore[index]
                            "minutes": round(minutes, 1)}
    save_status()
    print(f"{name}: rc {rc}, {minutes:.0f} min", flush=True)
status["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
save_status()
