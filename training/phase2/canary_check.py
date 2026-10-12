"""Report-only canary check (PIYA-106 G2, rules section 3). Scores checkpoints on the pinned 399 CPM canary stems
with the trainer's own functions, so numbers are like-for-like with the training log (mean per-sample SER)."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_phase2 as t  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpm-root", required=True)
    ap.add_argument("--weights", action="append", required=True, help="name=path (repeatable)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    cpm = t.cpm_samples(a.cpm_root)
    canary = cpm[: int(t.CANARY_FRACTION * len(cpm))]
    sha = hashlib.sha256("\n".join(Path(s[0]).stem for s in canary).encode("utf-8")).hexdigest()
    if (len(canary), sha) != (t.CANARY_COUNT, t.CANARY_STEMS_SHA256):
        raise SystemExit(f"canary is not the pinned slice: {len(canary)} stems, sha256 {sha}")
    print(f"canary OK: {len(canary)} stems, sha256 {sha[:8]}...")

    device = torch.device("cpu")
    kw = {"batch_size": t.BATCH_SIZE, "shuffle": False, "collate_fn": t.ctc_collate, "num_workers": 0}
    res = {"canary_sha256": sha, "n_stems": len(canary), "metric": "mean per-sample SER (trainer mean_ser)", "ser": {}}
    for spec in a.weights:
        name, path = spec.split("=", 1)
        model, _ = t.load_model(Path(path), device)
        for cond in ("clean", "distorted"):
            random.seed(0); np.random.seed(0); torch.manual_seed(0)
            loader = DataLoader(t.StripDataset(canary, force_distorted=(cond == "distorted")), **kw)
            res["ser"][f"{name}|{cond}"] = t.mean_ser(t.decode_batches(model, loader, device))
            print(f"{name:12s} {cond:9s} SER {100 * res['ser'][f'{name}|{cond}']:.2f}%", flush=True)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "canary_check.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())