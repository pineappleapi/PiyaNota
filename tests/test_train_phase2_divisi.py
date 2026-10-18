"""ReplaySampler divisi pool (A6 task 6): fresh draw per epoch, and train-1 order unchanged without the new args."""
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase2"))

from train_phase2 import ReplaySampler  # noqa: E402

N_SYNTH, N_POOL, N_CPM, N_DIVISI_POOL, N_DIVISI = 100, 50, 50, 1000, 25
SEED = 7
# Captured from the pre-A6 ReplaySampler(6, 5, 3, seed 7), two epochs: train-1 must keep this exact order.
TRAIN1_EPOCHS = ([4, 0, 9, 2, 7, 6, 1, 3, 5], [0, 1, 4, 3, 5, 2, 10, 9, 8])


def _gen(seed: int = SEED) -> torch.Generator:
    g = torch.Generator()
    g.manual_seed(seed)
    return g


def _divisi(order: list[int]) -> set[int]:
    return {i for i in order if i >= N_SYNTH + N_POOL}


def test_divisi_draw_is_fresh_each_epoch_and_seeded() -> None:
    s = ReplaySampler(N_SYNTH, N_POOL, N_CPM, _gen(), N_DIVISI_POOL, N_DIVISI)
    e1, e2 = list(s), list(s)
    assert len(s) == len(e1) == len(e2) == N_SYNTH + N_CPM + N_DIVISI
    assert len(_divisi(e1)) == len(_divisi(e2)) == N_DIVISI and s.last_epoch_divisi == N_DIVISI
    assert max(e1) < N_SYNTH + N_POOL + N_DIVISI_POOL
    assert _divisi(e1) != _divisi(e2)
    s2 = ReplaySampler(N_SYNTH, N_POOL, N_CPM, _gen(), N_DIVISI_POOL, N_DIVISI)
    assert [list(s2), list(s2)] == [e1, e2]


def test_train1_order_unchanged_without_divisi_args() -> None:
    s = ReplaySampler(6, 5, 3, _gen())
    assert (list(s), list(s)) == TRAIN1_EPOCHS and s.last_epoch_divisi == 0


def test_divisi_val_is_tuning_half_only() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase1"))
    import divisi_halves as dh
    from train_phase2 import tuning_half_rows

    pieces = [f"bach_{i:03d}__divisi" for i in range(30)]
    groups = {p.removesuffix("__divisi"): p.removesuffix("__divisi") for p in pieces}
    rows = [{"piece": p, "n": i} for i, p in enumerate(pieces)]
    kept = tuning_half_rows(rows, groups)
    assert kept and len(kept) < len(rows)
    assert not any(dh.is_test_half(str(r["piece"]), groups) for r in kept)
    assert {r["piece"] for r in rows if dh.is_test_half(str(r["piece"]), groups)}.isdisjoint(r["piece"] for r in kept)
