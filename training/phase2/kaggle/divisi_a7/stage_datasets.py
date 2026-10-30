"""Stage the A7 GPU training inputs locally (nothing is uploaded; the controller runs `kaggle datasets/kernels` later).

Writes under --out:
* real/        dataset piamac/piyanota-divisi-a7-real: manifest.jsonl + only the strips it references, same relative paths.
* train-code/  dataset piamac/piyanota-divisi-a7-train-code: repo.bundle (BRANCH at --commit) + phase2_seed{1,2}.pt.
* kernels/piyanota-divisi-a7-train-{c,cl}-s{1,2}/: the kernel script (a copy of the template that differs only in the
  ARM and SEED lines, asserted) and a kernel-metadata.json differing only in id/title/arm kernel source.
The kernel's COMMIT/EXPECT_DIVISI_MANIFEST_SHA stay PLACEHOLDER here: fill them in the template first, then stage.

Launch order (the bundle must hold the reviewed commit as its branch tip, and COMMIT cannot name the commit that pins
it): commit the reviewed code; fill COMMIT (= that commit) and both build shas in the template as an UNCOMMITTED
change; run this with --commit HEAD (the bundle is cut at the reviewed commit, the kernel copies are read from the
working tree); then commit the pins. Push the four kernels only after piyanota-divisi-a7-c / -cl have finished.
"""
import argparse
import difflib
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL_TEMPLATE = HERE / "phase2_divisi_a7_kernel.py"
META_TEMPLATE = HERE / "kernel-metadata.json"
REAL_ID = "piamac/piyanota-divisi-a7-real"
CODE_ID = "piamac/piyanota-divisi-a7-train-code"
ARMS = ("C", "CL")
SEEDS = (1, 2)
ARM_LINE = re.compile(r'^ARM = "[A-Z]+"', re.M)
SEED_LINE = re.compile(r"^SEED = \d+", re.M)
BASE_KERNEL_SOURCE = "piamac/piyanota-recut-full-1"
LICENSES = [{"name": "other"}]


def load_kernel_module():  # type: ignore[no-untyped-def]
    """Import the template for its constants; it has no import-time side effects (main() is guarded)."""
    spec = importlib.util.spec_from_file_location("a7_kernel_template", KERNEL_TEMPLATE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_dataset_metadata(folder: Path, dataset_id: str) -> None:
    meta = {"title": dataset_id.split("/")[1], "id": dataset_id, "licenses": LICENSES}
    (folder / "dataset-metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def stage_real(src: Path, out: Path) -> int:
    """Copy manifest.jsonl and exactly the strips its rows name; returns the strip count."""
    manifest = src / "manifest.jsonl"
    rows = [json.loads(x) for x in manifest.read_text(encoding="utf-8").splitlines() if x.strip()]
    files = sorted({r["file"] for r in rows})
    missing = [f for f in files if not (src / f).is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} strips named by {manifest} are missing, e.g. {missing[:2]}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest, out / "manifest.jsonl")
    for f in files:
        dst = out / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / f, dst)
    write_dataset_metadata(out, REAL_ID)
    return len(files)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def stage_code(repo: Path, commit: str, inits: Path, out: Path, branch: str, init_sha: dict[int, str]) -> None:
    """Bundle BRANCH and require its tip == commit: the kernel clones the branch and compares HEAD to COMMIT."""
    sha = git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}")
    tip = git(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
    if tip != sha:
        raise ValueError(f"branch {branch} tip {tip} != --commit {sha}; the bundle's HEAD would not be the reviewed commit")
    for seed, want in init_sha.items():
        p = inits / f"phase2_seed{seed}.pt"
        if not p.is_file() or sha256_file(p) != want:
            raise ValueError(f"{p} missing or sha256 differs from INIT_SHA256[{seed}]")
    out.mkdir(parents=True, exist_ok=True)
    git(repo, "bundle", "create", str(out / "repo.bundle"), f"refs/heads/{branch}")
    for seed in init_sha:
        shutil.copy2(inits / f"phase2_seed{seed}.pt", out / f"phase2_seed{seed}.pt")
    write_dataset_metadata(out, CODE_ID)


def kernel_text(template: str, arm: str, seed: int) -> str:
    text = ARM_LINE.sub(f'ARM = "{arm}"', template, count=1)
    return SEED_LINE.sub(f"SEED = {seed}", text, count=1)


def assert_only_arm_seed_differ(template: str, text: str) -> None:
    changed = [ln for ln in difflib.unified_diff(template.splitlines(), text.splitlines(), lineterm="", n=0)
               if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    bad = [ln for ln in changed if not re.match(r'^[+-](ARM = "|SEED = \d)', ln)]
    if bad:
        raise AssertionError(f"kernel copy differs outside ARM/SEED lines: {bad[:4]}")


def stage_kernels(out: Path) -> list[str]:
    template = KERNEL_TEMPLATE.read_text(encoding="utf-8")
    meta = json.loads(META_TEMPLATE.read_text(encoding="utf-8"))
    names: list[str] = []
    for arm in ARMS:
        for seed in SEEDS:
            slug = f"piyanota-divisi-a7-train-{arm.lower()}-s{seed}"
            text = kernel_text(template, arm, seed)
            assert_only_arm_seed_differ(template, text)
            folder = out / slug
            folder.mkdir(parents=True, exist_ok=True)
            (folder / KERNEL_TEMPLATE.name).write_text(text, encoding="utf-8", newline="\n")
            m = dict(meta, id=f"piamac/{slug}", title=slug,
                     kernel_sources=[BASE_KERNEL_SOURCE, f"piamac/piyanota-divisi-a7-{arm.lower()}"])
            (folder / "kernel-metadata.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
            names.append(slug)
    return names


def tree_stats(p: Path) -> tuple[int, float]:
    files = [f for f in p.rglob("*") if f.is_file()]
    return len(files), sum(f.stat().st_size for f in files) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--repo", type=Path, default=HERE.parents[3])
    ap.add_argument("--commit", required=True, help="reviewed commit (HEAD ok); must be the tip of the kernel's BRANCH")
    ap.add_argument("--inits", type=Path, required=True, help="folder holding phase2_seed{1,2}.pt")
    ap.add_argument("--real-src", type=Path, default=Path("D:/PiyaNota/datasets/divisi_a7_real"))
    a = ap.parse_args()
    k = load_kernel_module()
    n = stage_real(a.real_src, a.out / "real")
    stage_code(a.repo, a.commit, a.inits, a.out / "train-code", k.BRANCH, k.INIT_SHA256)
    names = stage_kernels(a.out / "kernels")
    if sha256_file(a.out / "real" / "manifest.jsonl") != k.EXPECT_REAL_MANIFEST_SHA:
        raise ValueError("staged real manifest sha256 != EXPECT_REAL_MANIFEST_SHA in the kernel")
    for sub in ("real", "train-code", "kernels"):
        c, mb = tree_stats(a.out / sub)
        print(f"{sub}: {c} files, {mb:.1f} MB")
    print(f"real strips copied: {n}; kernels: {', '.join(names)}")


if __name__ == "__main__":
    main()
