"""Unreadable voices are a partial success (Stage 4 report, Stage 5 silent track, client review item).

Run with ``python -m pytest tests/test_failed_voices.py``. Tokens are hand-written; no model, GPU or soundfont.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage3_transcription as s3  # noqa: E402
import stage4_reconstruction as s4  # noqa: E402
import stage5_synthesis as s5  # noqa: E402

VOICES = ["Soprano", "Alto", "Tenor", "Bass"]
BAR_TOKENS = ["clef.G-L2", "note.quarter-L2", "note.quarter-L3", "note.half-L2", "barline-L1",
              "note.whole-L2", "barline-L1"]


def _voice(voice: str, page: int) -> list[dict]:
    return s3.infer_pitch(list(BAR_TOKENS), voice=voice, page_index=page, sys_idx=1)


def _events(pages: dict[str, tuple[int, ...]]) -> dict[str, list[dict]]:
    return {v: [e for p in pages.get(v, ()) for e in _voice(v, p)] for v in VOICES}


def _unreadable(report: dict, voice: str) -> dict:
    return next(f for f in report["flags"] if f["kind"] == "voice_unreadable" and f["voice"] == voice)


def test_one_empty_voice_returns_partial() -> None:
    satb, report = s4.reconstruct_satb_with_report(
        _events({v: (1, 2) for v in VOICES if v != "Tenor"}))
    assert satb["Tenor"] == [] and report["failed_voices"] == ["Tenor"]
    flag = _unreadable(report, "Tenor")
    assert flag["pages"] == [1, 2] and flag["review_needed"] is True


def test_voice_missing_on_one_page_only_names_that_page() -> None:
    pages = {v: (1, 2) for v in VOICES}
    pages["Alto"] = (1,)
    satb, report = s4.reconstruct_satb_with_report(_events(pages))
    assert report["failed_voices"] == [] and satb["Alto"]
    assert _unreadable(report, "Alto")["pages"] == [2]
    assert not [f for f in report["flags"] if f["kind"] == "voice_unreadable" and f["voice"] != "Alto"]


def test_all_four_empty_raises_value_error() -> None:
    with pytest.raises(ValueError):
        s4.reconstruct_satb_with_report({v: [] for v in VOICES})


def test_unreadable_voice_does_not_shift_other_voices_ticks() -> None:
    full, _ = s4.reconstruct_satb_with_report(_events({v: (1, 2) for v in VOICES}))
    part, _ = s4.reconstruct_satb_with_report(_events({v: (1, 2) for v in VOICES if v != "Alto"}))
    for v in ("Soprano", "Tenor", "Bass"):
        assert [(e["tick_onset"], e["pitch"]) for e in part[v]] == [(e["tick_onset"], e["pitch"]) for e in full[v]]


def test_empty_voice_synthesized_as_silent_track(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    satb, _ = s4.reconstruct_satb_with_report(_events({v: (1,) for v in VOICES if v != "Tenor"}))
    monkeypatch.setattr(s5, "_render_to_mp3", lambda midi, wav, mp3, sf: mp3.write_bytes(b"x") or True)
    paths = s5.synthesize_satb(satb, str(tmp_path), 90, "x.sf2")
    assert set(paths) == set(VOICES)


def test_build_review_keeps_voice_unreadable_with_pages() -> None:
    flag = {"kind": "voice_unreadable", "voice": "Tenor", "pages": [2], "review_needed": True}
    review, _ = s5.build_review({}, [flag])
    assert review["items"][0]["code"] == "voice_unreadable" and review["items"][0]["voice"] == "tenor"
    assert review["items"][0]["pages"] == [2]
