"""PIYA-106 A7 divisi Kaggle GPU run: ONE seed-arm per kernel (design piya-106-divisi-a7-design.md sections 6, 14.1, 14.5-14.7).

Follows the A6 launcher (`../divisi_a6/phase2_divisi_a6_kernel.py`); what changed:
* one seed-arm per kernel/session (design 6: one T4 session, 11 h budget). Four kernels are pushed from copies of this
  file that differ only in the ARM and SEED lines (and the metadata id/title/kernel source):
  piyanota-divisi-a7-train-{c,cl}-s{1,2}. `stage_datasets.py` writes them and asserts that.
* A7 training flags: --vocab-a7 --arm ARM (C gets no layered strip), and the real A7-data stream
  (--real-manifest, --real-share 0.05, --real-cap 32). train_phase2 does not take the real manifest's sha, so this
  kernel checks it (EXPECT_REAL_MANIFEST_SHA) before training; the divisi sha goes through
  --expect-divisi-manifest-sha as in A6 and is per arm (the two builds differ).
* the divisi input is that arm's A7 build kernel (`build/out`, `halves.json`), and the kernel checks it really is the
  arm's build: arm C's build manifest has no layer.split token, arm CL's has at least one (a swapped attach would
  otherwise train the wrong arm silently; train_phase2 also rejects layers under arm C).
* COMMIT and the divisi shas are PLACEHOLDER until the controller fills them (after the build kernels finish); the
  kernel refuses to run on a PLACEHOLDER or a non-40-hex commit.
Inputs (kernel-metadata.json), nothing re-cut:
* kernel sources piamac/piyanota-recut-full-1 (Phase 1 `out/`, pinned by EXPECT_MANIFEST_SHA) and
  piamac/piyanota-divisi-a7-{c|cl} (build/out, build/manifest, halves.json).
* datasets piamac/cameraprimus and piamac/cpm-font-augmented2 (CPM replay and canary, as in A6);
  piamac/piyanota-divisi-a7-train-code (repo.bundle of BRANCH at COMMIT plus phase2_seed{1,2}.pt, checked against
  INIT_SHA256; seed k starts from Phase 2 seed k); piamac/piyanota-divisi-a7-real (real strips + manifest.jsonl).
Outputs under /kaggle/working/a7_<arm>_s<seed>/: run_info.json, metrics.json, summary.json, one checkpoint per epoch
(selection is offline). GPU numbers are not bit-reproducible (cuDNN), so both seeds are reported as a range.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ARM = "CL"                          # "C" (chords only) or "CL" (chords + layers); with SEED, the only lines that differ per kernel
SEED = 1                            # 1 or 2
COMMIT = "PLACEHOLDER"              # full 40-hex sha of the reviewed commit; the kernel refuses to train on anything else
BRANCH = "piya106/stroke-calibration"
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
SESSION_BUDGET_MIN = 11 * 60        # Kaggle GPU sessions stop at 12 h and a killed session keeps no output
INIT_SHA256 = {1: "5c444ad395179dfe6751b8de032d7a34b4a3ccfccebdd7fc28e2404c624eaf93",
               2: "f79892acbcb3a410f8a55c2b4f7289354111a29a7ed439c2990cfd755cbdaed4"}
EXPECT_MANIFEST_SHA = "78165b43251f67751afc91500e812a3ce7fa06d8980a275ddadd7014d8782824"   # Phase 1
EXPECT_DIVISI_MANIFEST_SHA = {"C": "PLACEHOLDER", "CL": "PLACEHOLDER"}   # sha256 of each build's phase2_manifest.jsonl rebuild
EXPECT_REAL_MANIFEST_SHA = "ae7d6ae4acc0de46a5184b136506b75793c2ddd4b52ca8ad0464a34f08b1f91f"
LAYER_TOKEN_JSON = '"layer.split"'   # JSON-quoted so a longer token cannot match
RUN_NAME = f"a7_{ARM.lower()}_s{SEED}"
TRAIN_ARGS: list[str] = ["--augment-synth", "--replay-ratio", "0.5", "--max-epochs", "8", "--select-last", "--lr", "3e-5",
                         "--vocab-a7", "--arm", ARM, "--divisi-share", "0.20", "--holdout-chord-font", "Gootville",
                         "--real-share", "0.05", "--real-cap", "32"]
CPM_FONTS = ("Bravura", "Gootville", "Leland", "Petaluma")
INPUT = Path("/kaggle/input")
SEARCH_DEPTH = 5                    # shallow globs only: CPM alone holds ~87k files
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/phase2")
STATUS = WORK / "kernel_status.json"
T_START = time.time()
status: dict[str, object] = {"commit": COMMIT, "arm": ARM, "seed": SEED, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def save_status() -> None:
    STATUS.write_text(json.dumps(status, indent=1), encoding="utf-8")


def abort(msg: str) -> None:
    status["aborted"] = msg
    save_status()
    raise SystemExit(msg)


def pin_errors() -> list[str]:
    """Unfilled or malformed pins; a launch on any of these would not be the reviewed run."""
    errs: list[str] = []
    if ARM not in ("C", "CL") or SEED not in INIT_SHA256:
        errs.append(f"ARM {ARM!r} / SEED {SEED!r} not one of C|CL / 1|2")
    if not COMMIT_SHA.fullmatch(COMMIT):
        errs.append(f"COMMIT {COMMIT!r} is not a 40-hex sha")
    if not re.fullmatch(r"[0-9a-f]{64}", str(EXPECT_DIVISI_MANIFEST_SHA.get(ARM))):
        errs.append(f"EXPECT_DIVISI_MANIFEST_SHA[{ARM}] is not a 64-hex sha")
    return errs


def sh(cmd: list[str], **kw: object) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def find_shallow(name: str, want_dir: bool) -> Path:
    for depth in range(1, SEARCH_DEPTH + 1):
        hits = sorted(p for p in INPUT.glob("/".join(["*"] * (depth - 1) + [name])) if p.is_dir() == want_dir)
        if hits:
            return hits[0]
    abort(f"{name} not found under {INPUT} (depth {SEARCH_DEPTH}): is the matching dataset/kernel attached?")
    raise AssertionError("unreachable")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    errs = pin_errors()
    if errs:
        abort("pins not set: " + "; ".join(errs))

    code_dir = find_shallow("repo.bundle", want_dir=False).parent
    init = code_dir / f"phase2_seed{SEED}.pt"
    if not init.exists() or sha256_file(init) != INIT_SHA256[SEED]:
        abort(f"init {init.name} missing or not the deployed Phase 2 seed {SEED} checkpoint")
    # Each output has a file the other lacks: the recut its canary digest, the A7 build its x-order audit.
    recut_out = find_shallow("canary_digest.json", want_dir=False).parent / "out"
    a7_root = find_shallow("xorder_report.json", want_dir=False).parent
    divisi_out = a7_root / "build" / "out"
    halves = a7_root / "halves.json"
    build_manifest = a7_root / "build" / "manifest" / "phase2_manifest.jsonl"
    for p in (halves, build_manifest):
        if not p.is_file():
            abort(f"input incomplete: {p}")
    has_layers = LAYER_TOKEN_JSON in build_manifest.read_text(encoding="utf-8")
    if has_layers != (ARM == "CL"):
        abort(f"attached divisi build is not arm {ARM}: layer.split {'present' if has_layers else 'absent'} in {build_manifest}")
    real_dir = find_shallow("piyanota-divisi-a7-real", want_dir=True)
    real_manifest = real_dir / "manifest.jsonl"
    if not real_manifest.is_file() or not (real_dir / "strips").is_dir():
        abort(f"input incomplete: {real_manifest} or {real_dir / 'strips'}")
    real_sha = sha256_file(real_manifest)
    if real_sha != EXPECT_REAL_MANIFEST_SHA:
        abort(f"real manifest sha256 {real_sha} != expected {EXPECT_REAL_MANIFEST_SHA}")
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

    import torch  # noqa: PLC0415  (Kaggle's preinstalled CUDA build; versions recorded, not re-pinned)

    status.update(torch=torch.__version__, cuda=torch.version.cuda,
                  gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                  recut_out=str(recut_out), divisi_out=str(divisi_out), cpm_root=str(cpm_root),
                  cpm_font_root=str(cpm_font_root), halves=str(halves), real_manifest=str(real_manifest),
                  verified_shas={"init": INIT_SHA256[SEED], "real_manifest": real_sha,
                                 "phase1_manifest": EXPECT_MANIFEST_SHA,
                                 "divisi_manifest": EXPECT_DIVISI_MANIFEST_SHA[ARM]},
                  train_args=TRAIN_ARGS)
    save_status()
    if not torch.cuda.is_available():
        abort("no GPU: enable the GPU accelerator for this kernel")

    out = WORK / RUN_NAME
    cmd = [sys.executable, str(repo / "training/phase2/train_phase2.py"), "--recut-out", str(recut_out),
           "--cpm-root", str(cpm_root), "--init", str(init), "--seed", str(SEED), "--out", str(out),
           "--cpm-font-root", str(cpm_font_root), "--expect-manifest-sha", EXPECT_MANIFEST_SHA, *TRAIN_ARGS,
           "--real-manifest", str(real_manifest),
           "--divisi-recut-out", str(divisi_out), "--expect-divisi-manifest-sha", EXPECT_DIVISI_MANIFEST_SHA[ARM],
           "--halves", str(halves)]
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with (out / "train.log").open("w", encoding="utf-8") as log:
        try:
            # Every epoch checkpoint is saved, so a run stopped by the budget still leaves usable output.
            rc: int | str = subprocess.run(cmd, cwd=str(repo), env={**os.environ, "PYTHONUTF8": "1"}, stdout=log,
                                           stderr=subprocess.STDOUT,
                                           timeout=SESSION_BUDGET_MIN * 60 - (t0 - T_START)).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout_budget"
    minutes = (time.time() - t0) / 60
    status["run"] = {"name": RUN_NAME, "seed": SEED, "returncode": rc, "minutes": round(minutes, 1)}
    status["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_status()
    print(f"{RUN_NAME}: rc {rc}, {minutes:.0f} min", flush=True)


if __name__ == "__main__":
    main()
