"""Client review object carries voice flags only (Task 2, 2026-11-04 plan); internal flags stay in full_items."""

import os
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage5_synthesis as s5  # noqa: E402

INTERNAL = ["clef_key_unvalidated", "tenor_range_suspect", "mid_strip_meter_change"]


def _event(flags: list[str]) -> dict:
    return {"page_index": 1, "sys_idx": 1, "clef_key_flags": flags, "clef_key_strip_flags": flags,
            "mid_change_flags": ["mid_strip_meter_change", "review_needed"]}


def test_client_review_only_voice_codes() -> None:
    stage4 = [{"kind": "voice_unreadable", "voice": "Tenor", "pages": [1], "page_index": None,
               "sys_idx": None, "bar": None, "review_needed": True},
              {"kind": "tenor_range_suspect", "voice": "Tenor", "page_index": 1, "sys_idx": 1, "bar": 2,
               "review_needed": True}]
    review, _ = s5.build_review({"Alto": [_event(INTERNAL + ["review_needed"])]}, stage4)
    assert review["reasons"] == ["voice_unreadable"] and review["reviewNeeded"] is True


def test_no_voice_flags_means_review_not_needed() -> None:
    review, _ = s5.build_review({"Alto": [_event(INTERNAL + ["review_needed"])]}, [])
    assert review["reviewNeeded"] is False and review["items"] == []


def test_full_items_keep_internal_flags() -> None:
    _, full = s5.build_review({"Alto": [_event(INTERNAL + ["review_needed"])]}, [])
    assert "mid_strip_meter_change" in {i["code"] for i in full}
