"""A7 checks between the build kernels and the GPU kernels (design 14.7 "Before GPU"); fills the divisi sha pins.

    python training/phase2/kaggle/divisi_a7/pre_gpu_check.py --build C=<fetched arm C build> \
        --build CL=<fetched arm CL build> --out a7_pre_gpu.json [--write-pins]

Each --build is a fetch of piamac/piyanota-divisi-a7-{c,cl} (training/phase1/kaggle/fetch_output.py); only the small
files are read: kernel_status.json, a7_gates.json, halves.json, build/manifest/phase2_manifest.jsonl and
build/corpus/*.plan.json. Fails (exit 1) on anything that would stop or silently corrupt a GPU run:
* the build kernel did not finish ok, or its a7_gates.json is not ok;
* the build is not the arm it claims (layer.split absent for CL / present for C, the kernel's own check);
* a divisi or real token outside VOCAB_EXT_A7 (train_phase2 would KeyError mid-load);
* the non-Gootville divisi train pool is smaller than the strips train_phase2 draws per epoch (its SystemExit);
* the Phase 1 manifest rebuilt from --phase1-out is not the kernel's EXPECT_MANIFEST_SHA.
Reported, not failed (14.7): C vs CL per-bucket chord train counts (a gap over 10% is named as a confound), and per arm
the real stream's realised share per epoch, staff-systems at cap and per-piece view shares. The real draw is simulated
with train_phase2.RealDraw alone; on GPU the same generator also feeds the CPM/divisi permutations, so the draw order
differs but the cap arithmetic (per epoch, per run) is the same.

The divisi pin is the sha256 of the build's phase2_manifest.jsonl: build_manifest.py writes the same bytes that
train_phase2 hashes when it rebuilds the manifest from build/out. --write-pins writes both arms' shas into the kernel
template, only when every check passes; COMMIT is set by the launch order in stage_datasets.py.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "training" / "phase2"))
import train_phase2 as tp  # noqa: E402

KERNEL_TEMPLATE = HERE / "phase2_divisi_a7_kernel.py"
ARMS = ("C", "CL")
CONFOUND_GAP = 0.10                 # 14.7: C vs CL per-bucket chord train counts within 10%, else a named confound
PIN_LINE = re.compile(r"^EXPECT_DIVISI_MANIFEST_SHA = \{[^}]*\}", re.M)


def load_kernel():  # type: ignore[no-untyped-def]
    """The template's constants (shares, cap, epochs, shas) are the run's, so they are read, never copied here."""
    spec = importlib.util.spec_from_file_location("a7_kernel_template", KERNEL_TEMPLATE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def flag(train_args: list[str], name: str) -> str:
    return train_args[train_args.index(name) + 1]


def jsonl(p: Path) -> list[dict[str, object]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def chord_train_counts(build: Path) -> collections.Counter[str]:
    """Chord columns per interval bucket in train plans, as divisi_a7_gates.dyad_train_gates counts them."""
    got: collections.Counter[str] = collections.Counter()
    for f in (build / "build" / "corpus").glob("*.plan.json"):
        plan = json.loads(f.read_text(encoding="utf-8"))
        if plan.get("split") == "train":
            for k, v in plan["divisi"]["class"].items():
                got[k.split(":")[1]] += v
    return got


def check_arm(arm: str, build: Path, n_divisi_epoch: int, holdout_font: str) -> tuple[dict[str, object], list[str]]:
    errs: list[str] = []
    status = json.loads((build / "kernel_status.json").read_text(encoding="utf-8"))
    if status.get("status") != "ok":
        errs.append(f"{arm}: build kernel status {status.get('status')!r} ({status.get('aborted', '')})")
    gates_path = build / "a7_gates.json"
    gates = json.loads(gates_path.read_text(encoding="utf-8")) if gates_path.is_file() else {}
    if gates.get("ok") is not True:
        failed = [g["name"] for g in gates.get("gates", []) if g.get("status") not in ("pass", "warn", "not_run", "info")]
        errs.append(f"{arm}: a7_gates.json not ok (missing or failed: {failed[:6]})")
    if not (build / "halves.json").is_file():
        errs.append(f"{arm}: halves.json missing")
    manifest = build / "build" / "manifest" / "phase2_manifest.jsonl"
    if not manifest.is_file():
        errs.append(f"{arm}: {manifest} missing")
        return {"status": status.get("status")}, errs
    rows = jsonl(manifest)
    has_layers = any(tp.LAYER_SPLIT_TOKEN in r["tokens"] for r in rows)  # type: ignore[operator]
    if has_layers != (arm == "CL"):
        errs.append(f"{arm}: layer.split {'present' if has_layers else 'absent'}: not an arm {arm} build")
    oov = sorted({str(t) for r in rows for t in r["tokens"] if t not in tp.SYM_TO_IDX})  # type: ignore[union-attr]
    if oov:
        errs.append(f"{arm}: divisi tokens outside VOCAB_EXT_A7: {oov[:5]}")
    pool = sum(r["split"] == "train" and str(r["font"]).casefold() != holdout_font.casefold() for r in rows)
    if pool < n_divisi_epoch:
        errs.append(f"{arm}: divisi train pool {pool} (without {holdout_font}) < {n_divisi_epoch} per epoch")
    info = {"status": status.get("status"), "commit": status.get("commit"), "manifest_sha256": tp.sha256_file(manifest),
            "rows": len(rows), "train_pool_without_holdout": pool, "layer_split_strips":
            sum(tp.LAYER_SPLIT_TOKEN in r["tokens"] for r in rows)}  # type: ignore[operator]
    return info, errs


def simulate_real(arm: str, real_rows: list[dict[str, object]], n_real_epoch: int, n_divisi_epoch: int, cap: int,
                  epochs: int, seed: int) -> dict[str, object]:
    """train_phase2's real-row filter and RealDraw, without the rest of the sampler (see the module docstring)."""
    rows = [r for r in real_rows if r["train_ok"] and r["split"] == "train" and not (arm == "C" and r["layered"])]
    groups: dict[tuple[object, ...], list[int]] = collections.defaultdict(list)
    for k, r in enumerate(rows):
        groups[(r["piece"], r["page"], r["sys"], r["staff"])].append(k)
    draw = tp.RealDraw(list(groups.values()), max(1, cap // epochs), cap, [str(k[0]) for k in groups])
    gen = torch.Generator()
    gen.manual_seed(seed)
    shares = []
    for _ in range(epochs):
        n = len(draw.draw(n_real_epoch, gen))
        shares.append(round(n / max(1, n + n_divisi_epoch), 4))
    by_piece = draw.views_by_piece()
    return {"strips": len(rows), "staff_systems": len(groups), "layered": sum(bool(r["layered"]) for r in rows),
            "per_epoch_target": n_real_epoch, "realised_share_by_epoch": shares, "at_cap_end": draw.at_cap(),
            "views_total": sum(draw.views), "views_by_piece": by_piece,
            "max_piece": max(by_piece.items(), key=lambda kv: kv[1]) if by_piece else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", action="append", required=True, help="ARM=dir, once per arm (C and CL)")
    ap.add_argument("--phase1-out", type=Path, default=Path("D:/PiyaNota/datasets/phase1_recut_full/out"))
    ap.add_argument("--real-manifest", type=Path, default=Path("D:/PiyaNota/datasets/divisi_a7_real/manifest.jsonl"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--write-pins", action="store_true", help="write both arms' divisi shas into the kernel template")
    a = ap.parse_args()
    builds = dict(b.split("=", 1) for b in a.build)
    if sorted(builds) != sorted(ARMS):
        raise SystemExit(f"--build needs exactly C=... and CL=..., got {sorted(builds)}")
    k = load_kernel()
    tp.use_ext_vocab(tp.VOCAB_EXT_A7)
    divisi_share = float(flag(k.TRAIN_ARGS, "--divisi-share"))
    real_share, cap = float(flag(k.TRAIN_ARGS, "--real-share")), int(flag(k.TRAIN_ARGS, "--real-cap"))
    epochs, holdout = int(flag(k.TRAIN_ARGS, "--max-epochs")), flag(k.TRAIN_ARGS, "--holdout-chord-font")
    errs: list[str] = []

    # Phase 1 train count fixes the per-epoch divisi and real sizes; rebuilt exactly as train_phase2 does.
    p1_rows, _ = tp.build(a.phase1_out)
    body = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in p1_rows).encode("utf-8")
    p1_sha = hashlib.sha256(body).hexdigest()
    if p1_sha != k.EXPECT_MANIFEST_SHA:
        errs.append(f"Phase 1 manifest sha256 {p1_sha} != kernel EXPECT_MANIFEST_SHA {k.EXPECT_MANIFEST_SHA}")
    n_p1 = sum(r["split"] == "train" for r in p1_rows)
    n_divisi_epoch = round(divisi_share * n_p1 / (1.0 - divisi_share))
    n_real_epoch = round(real_share * n_divisi_epoch / (1.0 - real_share))

    real_rows = jsonl(a.real_manifest)
    if tp.sha256_file(a.real_manifest) != k.EXPECT_REAL_MANIFEST_SHA:
        errs.append("real manifest sha256 != kernel EXPECT_REAL_MANIFEST_SHA")
    real_oov = sorted({str(t) for r in real_rows if r["train_ok"] for t in r["tokens"] if t not in tp.SYM_TO_IDX})  # type: ignore[union-attr]
    if real_oov:
        errs.append(f"real tokens outside VOCAB_EXT_A7: {real_oov[:5]}")

    arms: dict[str, object] = {}
    for arm in ARMS:
        info, e = check_arm(arm, Path(builds[arm]), n_divisi_epoch, holdout)
        errs += e
        info["real"] = {f"seed{s}": simulate_real(arm, real_rows, n_real_epoch, n_divisi_epoch, cap, epochs, s)
                        for s in k.INIT_SHA256}
        arms[arm] = info

    counts = {arm: chord_train_counts(Path(builds[arm])) for arm in ARMS}
    buckets = sorted(set(counts["C"]) | set(counts["CL"]))
    compare = {b: {"C": counts["C"][b], "CL": counts["CL"][b],
                   "gap": round(abs(counts["C"][b] - counts["CL"][b]) / max(1, counts["C"][b], counts["CL"][b]), 4)}
               for b in buckets}
    confounds = [b for b, v in compare.items() if v["gap"] > CONFOUND_GAP]

    report = {"ok": not errs, "errors": errs, "phase1_train_rows": n_p1, "phase1_manifest_sha256": p1_sha,
              "divisi_per_epoch": n_divisi_epoch, "real_per_epoch_target": n_real_epoch, "arms": arms,
              "chord_train_counts": compare, "confounds_over_10pct": confounds}
    a.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"Phase 1 train {n_p1}; divisi/epoch {n_divisi_epoch}; real/epoch target {n_real_epoch}")
    for arm in ARMS:
        info = arms[arm]
        r1 = info["real"]["seed1"]  # type: ignore[index]
        print(f"{arm}: sha {info.get('manifest_sha256')} real share/epoch {r1['realised_share_by_epoch']} "  # type: ignore[union-attr]
              f"at cap {r1['at_cap_end']}/{r1['staff_systems']} max piece {r1['max_piece']}")
    print("confounds (>10% C vs CL): " + (", ".join(confounds) or "none"))
    if errs:
        print("PRE-GPU CHECK FAILED:\n  " + "\n  ".join(errs))
        return 1
    if a.write_pins:
        pins = {arm: arms[arm]["manifest_sha256"] for arm in ARMS}  # type: ignore[index]
        text = KERNEL_TEMPLATE.read_text(encoding="utf-8")
        new, n = PIN_LINE.subn(f'EXPECT_DIVISI_MANIFEST_SHA = {{"C": "{pins["C"]}", "CL": "{pins["CL"]}"}}', text)
        if n != 1:
            raise SystemExit(f"expected one EXPECT_DIVISI_MANIFEST_SHA line in {KERNEL_TEMPLATE}, found {n}")
        KERNEL_TEMPLATE.write_text(new, encoding="utf-8", newline="\n")
        print(f"pins written to {KERNEL_TEMPLATE.name}: {pins}")
    print("PRE-GPU CHECK PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
