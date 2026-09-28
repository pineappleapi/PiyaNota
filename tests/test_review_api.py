"""Tests for the review summary the result API exposes (PIYA-103 AC6, backend-lead 2026-09-29).

ClefKeyNet stays the default while it fails its real-photo gate (BUG-021), on the condition that every
event is flagged for review; these tests pin that condition and the client ``review`` shape.

Run with ``python tests/test_review_api.py``. Synthetic tests: they say nothing about accuracy.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage3_clefkey as s3ck  # noqa: E402
import stage5_synthesis as s5  # noqa: E402
from clef_voice_rules import ClefDecision  # noqa: E402
from stage3_transcription import CLEF_KEY_DISABLED_FLAG  # noqa: E402

TOKENS = ["clef.G-L2", "digit.4-S5", "digit.4-S3", "note.quarter-L2", "barline-L1", "note.quarter-S3"]


def _decision(flags: list) -> s3ck.StripDecision:
    clef = ClefDecision(clef_class="G", token="clef.G-L2", octave_shift=0, source="voice_default",
                        classifier_top="G", flags=[])
    return s3ck.StripDecision(clef=clef, key=0, key_source="vote", flags=flags)


def _event(voice: str, page: int, sys_idx: int, flags: list, strip_flags: list = ()) -> dict:
    return {"voice": voice, "page_index": page, "sys_idx": sys_idx, "clef_key_flags": flags,
            "clef_key_strip_flags": list(strip_flags), "review_needed": "review_needed" in flags}


def test_every_classifier_event_flagged_while_gate_not_passed() -> None:
    assert s3ck.CLEF_KEY_GATE_PASSED is False
    events, _, info = s3ck.infer_pitch_b(TOKENS, [1.0] * len(TOKENS), "Soprano", 1, 1, _decision([]))
    assert events
    for e in events:
        assert e["review_needed"] is True
        assert s3ck.CLEF_KEY_UNVALIDATED_FLAG in e["clef_key_flags"]
    # The strip's own flags stay separate so evaluations can still count specific problems.
    assert info["review_needed"] is False and s3ck.CLEF_KEY_UNVALIDATED_FLAG not in info["flags"]


def test_strip_flags_kept_next_to_unvalidated_flag() -> None:
    events, _, info = s3ck.infer_pitch_b(TOKENS, [1.0] * len(TOKENS), "Alto", 2, 3,
                                         _decision(["key_no_majority", "review_needed"]))
    assert set(events[0]["clef_key_flags"]) == {"key_no_majority", "review_needed",
                                                s3ck.CLEF_KEY_UNVALIDATED_FLAG}
    assert events[0]["clef_key_strip_flags"] == ["key_no_majority", "review_needed"]
    assert info["flags"] == ["key_no_majority", "review_needed"]


def test_review_shape_and_job_level_reason() -> None:
    unval = [s3ck.CLEF_KEY_UNVALIDATED_FLAG, "review_needed"]
    stage3 = {"Soprano": [_event("Soprano", 1, 1, unval)] * 3,
              "Tenor": [_event("Tenor", 1, 2, unval + ["key_no_majority"],
                               ["key_no_majority", "review_needed"])] * 2}
    stage4 = [{"kind": "bar_overflow_clipped", "page_index": 1, "sys_idx": 1, "bar": 4, "voice": "Bass",
               "expected_ticks": 1920, "actual_ticks": 2400, "detail": "x", "action": "clip",
               "review_needed": True},
              {"kind": "pickup_detected", "page_index": 1, "sys_idx": 1, "bar": 0, "voice": None,
               "expected_ticks": 0, "actual_ticks": 0, "detail": "", "action": ""}]
    review, full = s5.build_review(stage3, stage4)
    assert set(review) == {"reviewNeeded", "reasons", "items", "truncated"}
    assert review["reviewNeeded"] is True and review["truncated"] is False
    assert review["reasons"] == ["bar_overflow_clipped", s3ck.CLEF_KEY_UNVALIDATED_FLAG, "key_no_majority"]
    # Stage 4 items first; one item per strip and code; job-level reasons and unflagged Stage 4 entries
    # are not items.
    assert review["items"] == [
        {"code": "bar_overflow_clipped", "voice": "bass", "pageIndex": 1, "systemIndex": 1, "bar": 4},
        {"code": "key_no_majority", "voice": "tenor", "pageIndex": 1, "systemIndex": 2, "bar": None},
    ]
    assert full == review["items"]
    # Internal fields never leak into the client object.
    assert "expected_ticks" not in str(review) and "sha256" not in str(review).lower()


def test_informational_strip_flag_is_not_a_review_item() -> None:
    # senior-reviewer B1: a confident plain-G Tenor gets an informational flag without review_needed.
    info = ["plain_treble_on_low_voice_assumed_8vb"]
    review, full = s5.build_review({"Tenor": [_event("Tenor", 1, 1, info, info)]}, [])
    assert review == {"reviewNeeded": False, "reasons": [], "items": [], "truncated": False} and full == []


def test_disabled_classifier_is_a_reason() -> None:
    stage3 = {"Bass": [_event("Bass", 1, 1, [CLEF_KEY_DISABLED_FLAG, "review_needed"])]}
    review, _ = s5.build_review(stage3, [])
    assert review == {"reviewNeeded": True, "reasons": [CLEF_KEY_DISABLED_FLAG], "items": [],
                      "truncated": False}


def test_nothing_flagged() -> None:
    review, full = s5.build_review({"Soprano": [_event("Soprano", 1, 1, [])]}, [])
    assert review == {"reviewNeeded": False, "reasons": [], "items": [], "truncated": False} and full == []


def test_items_capped_with_full_list_kept() -> None:
    stage4 = [{"kind": "bar_underfull", "page_index": 1, "sys_idx": 1, "bar": b, "voice": "Alto",
               "review_needed": True} for b in range(s5.REVIEW_ITEMS_CAP + 5)]
    strips = {"Alto": [_event("Alto", 1, s, ["review_needed"], ["key_no_majority", "review_needed"])
                       for s in range(300)]}
    review, full = s5.build_review(strips, stage4)
    assert len(review["items"]) == s5.REVIEW_ITEMS_CAP and review["truncated"] is True
    assert all(i["code"] == "bar_underfull" for i in review["items"]), "bar items survive the cap"
    assert len(full) == s5.REVIEW_ITEMS_CAP + 5 + 300


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("ok", name)
            except AssertionError as exc:
                failures += 1
                print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
