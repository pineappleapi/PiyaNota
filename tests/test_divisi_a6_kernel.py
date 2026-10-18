"""Pure helpers of the A6 build kernel: the adaptive seed phase rule and the time estimate."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "piyanota_divisi_a6",
    Path(__file__).resolve().parents[1] / "training" / "phase1" / "kaggle" / "divisi_a6" / "piyanota_divisi_a6.py")
kernel = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kernel)

BUCKETS = ["3rd", "4th"]


def _counts(in_font: int, held_out: int) -> dict:
    return {"in_font": {b: in_font for b in BUCKETS}, "held_out": {b: held_out for b in BUCKETS}}


def test_phase_a_until_every_bucket_has_in_font_heads_then_b_then_stop():
    assert kernel.next_phase(_counts(599, 0), 600, 300, BUCKETS) == kernel.PAIRED
    short = {"in_font": {"3rd": 600, "4th": 10}, "held_out": {}}
    assert kernel.next_phase(short, 600, 300, BUCKETS) == kernel.PAIRED
    assert kernel.next_phase(_counts(600, 299), 600, 300, BUCKETS) == kernel.GOOTVILLE_ONLY
    assert kernel.next_phase(_counts(900, 300), 600, 300, BUCKETS) is None


def test_time_budget_estimate_and_cutoff():
    assert kernel.estimate_seed_minutes([], kernel.PAIRED) == kernel.DEFAULT_PAIRED_SEED_MINUTES
    assert kernel.estimate_seed_minutes([], kernel.GOOTVILLE_ONLY) == (
        kernel.DEFAULT_PAIRED_SEED_MINUTES / kernel.GOOTVILLE_SEED_FRACTION)
    done = [(kernel.PAIRED, 40.0), (kernel.PAIRED, 20.0)]
    assert kernel.estimate_seed_minutes(done, kernel.PAIRED) == 30.0
    assert kernel.estimate_seed_minutes(done, kernel.GOOTVILLE_ONLY) == 6.0
    budget = kernel.KAGGLE_SESSION_MINUTES - kernel.TEST_RESERVE_MINUTES
    assert 600 + 30.0 <= budget < 600 + 31.0 + 30.0     # the loop stops once elapsed + estimate exceeds the budget
    assert 590 + 30.0 <= budget and not (610 + 30.0 <= budget)
