"""Stage 3 divisi chord pairing (PIYA-106, plan docs/superpowers/plans/2026-10-16-stage3-divisi-pairing.md).

Accidentals and dots are paired with the notehead they were drawn for, including the members of a same-stem
chord (`note.* chordnote-*`, converter order in training/music_to_agnostic.py Converter.chord). Synthetic
token-level tests: they say nothing about CRNN accuracy. Monophonic invariance is proven by the golden harness
(training/phase2/stage3_golden.py), not here.

Treble positions: L-1 A3, S-1 B3, L0 C4, L1 E4, L2 G4, L3 B4, S3 C5, S4 E5. quarter 480 ticks, half 960.
"""

import contextlib
import io
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage3_transcription as s3  # noqa: E402

C = ["clef.G-L2", "metersign.C-L3"]
EB = ["clef.G-L2", "accidental.flat-L3", "accidental.flat-S4", "accidental.flat-S2", "metersign.C-L3"]


def _run(tokens: list[str], voice: str = "Soprano", confidences: Optional[list[float]] = None,
         **kw: Any) -> tuple[list[dict], str, list[dict]]:
    """(events, stdout, mid_changes_out) of infer_pitch."""
    mids: list[dict] = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        events = s3.infer_pitch(tokens, voice=voice, page_index=1, sys_idx=1, confidences=confidences,
                                mid_changes_out=mids, **kw)
    return events, buf.getvalue(), mids


def _notes(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "note"]


def _pitches(events: list[dict]) -> list[int]:
    return [e["pitch"] for e in _notes(events)]


# ── Task 2: onset positions for anchoring ────────────────────────────────────

def test_accidental_on_chordnote_position_is_anchored() -> None:
    events, out, _ = _run(C + ["note.quarter-L2", "accidental.sharp-L1", "note.quarter-S-1", "chordnote-L1"])
    assert not any("unanchored_accidental_dropped" in e for e in events)
    assert "unanchored accidental" not in out


def test_accidental_off_every_member_still_dropped() -> None:
    # The flat on S3 belongs to the chordnote; only the sharp on L3 (no member there) is a phantom.
    events, out, _ = _run(C + ["note.quarter-L2", "accidental.sharp-L3", "accidental.flat-S3", "note.quarter-L1",
                               "chordnote-S3"])
    base = next(e for e in events if e["symbol"] == "note.quarter-L1")
    assert base["unanchored_accidental_dropped"] == "accidental.sharp-L3"
    assert "dropped 1 unanchored" in out


def test_override_chord_accidentals_inline() -> None:
    events, out, _ = _run(["clef.G-L2", "accidental.sharp-L1", "accidental.flat-S3", "note.quarter-L1",
                           "chordnote-S3"], header_override=s3.HeaderOverride("clef.G-L2", 0, 0))
    assert "CRNN header" not in out
    assert not any("unanchored_accidental_dropped" in e for e in events)


def test_post_bar_accidental_on_chordnote_not_key_change() -> None:
    events, out, mids = _run(C + ["note.quarter-L2", "barline-L1", "accidental.sharp-S3", "note.quarter-L1",
                                  "chordnote-S3"])
    assert not [m for m in mids if m["kind"] == "key"]
    assert "mid-piece key change" not in out
    assert not any("unanchored_accidental_dropped" in e for e in events)


def test_post_bar_key_order_burst_ending_on_chordnote_not_key_change() -> None:
    # Two sharps in key order (F5, C5) whose last one sits on a chord member: that sharp is the member's
    # accidental, and one remaining glyph is too few for a key change.
    events, out, mids = _run(C + ["note.quarter-L2", "barline-L1", "accidental.sharp-L5", "accidental.sharp-S3",
                                  "note.quarter-L1", "chordnote-S3"])
    assert not [m for m in mids if m["kind"] == "key"]
    assert "mid-piece key change" not in out


# ── Task 3a: position-keyed pending accidentals ──────────────────────────────

def test_accidental_paired_by_position() -> None:
    # Eb major: the natural on S4 (E5) belongs to the chordnote; the next S4 in the bar inherits it, the
    # barline cancels it.
    events, _, _ = _run(EB + ["accidental.natural-S4", "note.quarter-L1", "chordnote-S4", "note.quarter-S4",
                              "barline-L1", "note.quarter-S4"])
    assert _pitches(events) == [63, 76, 76, 75]


def test_two_accidentals_two_members() -> None:
    events, _, _ = _run(C + ["note.quarter-L2", "accidental.sharp-L1", "accidental.flat-S3", "note.quarter-L1",
                             "chordnote-S3"])
    assert _pitches(events)[-2:] == [65, 71]


def test_real_g1b_label_sharp_on_upper_member() -> None:
    events, _, _ = _run(C + ["note.quarter-L2", "accidental.sharp-L1", "note.beamedLeft2-S-1", "chordnote-L1"])
    assert _pitches(events)[-2:] == [59, 65]


# ── Task 3b: chordnote events, onset close, orphans, confidence ──────────────

def test_dyad_shares_onset_and_advances_once() -> None:
    for header, top in ((C, 71), (EB, 70)):
        events, _, _ = _run(header + ["note.half-L2", "chordnote-L3", "note.quarter-L2"])
        notes = _notes(events)
        assert [e["pitch"] for e in notes] == [67, top, 67]
        assert notes[0]["tick_onset"] == notes[1]["tick_onset"] == 0
        assert notes[1]["duration_ticks"] == 960
        assert isinstance(notes[0]["chord_id"], int) and notes[0]["chord_id"] == notes[1]["chord_id"]
        assert notes[2]["tick_onset"] == 960 and notes[2]["chord_id"] is None


def test_unison_chordnote_dropped() -> None:
    events, _, _ = _run(C + ["note.quarter-L2", "chordnote-L2"])
    assert len(events) == 1
    assert events[0]["unison_chordnote_dropped"] == "chordnote-L2"
    assert events[0]["review_needed"] is True


def test_orphan_chordnote_after_rest_barline_header() -> None:
    cases = [
        C + ["rest.quarter-L3", "chordnote-L2", "note.quarter-L2"],
        C + ["note.quarter-L2", "barline-L1", "chordnote-L2", "note.quarter-L2"],
        ["clef.G-L2", "chordnote-L2", "metersign.C-L3", "note.quarter-L2"],
        ["chordnote-L2", "clef.G-L2", "metersign.C-L3", "note.quarter-L2"],
        ["clef.G-L2", "chordnote-L2", "note.quarter-L2"],
    ]
    for tokens in cases:
        events, _, _ = _run(tokens)
        assert not any(e["symbol"].startswith("chordnote-") for e in events), tokens
        assert len(events) == sum(t.startswith(("note.", "rest.")) for t in tokens), tokens
        after = events[-1]
        assert after["orphan_chordnote_dropped"] == "chordnote-L2", tokens
        assert after["review_needed"] is True, tokens
        assert all("orphan_chordnote_dropped" not in e for e in events[:-1]), tokens


def test_orphan_chordnote_flag_goes_on_next_rest() -> None:
    events, _, _ = _run(C + ["note.quarter-L2", "barline-L1", "chordnote-L2", "rest.quarter-L3"])
    assert events[-1]["type"] == "rest"
    assert events[-1]["orphan_chordnote_dropped"] == "chordnote-L2"


def test_repeated_orphans_and_unisons_all_recorded() -> None:
    events, _, _ = _run(C + ["rest.quarter-L3", "chordnote-L2", "chordnote-S3", "note.quarter-L2"])
    assert events[-1]["orphan_chordnote_dropped"] == "chordnote-L2 chordnote-S3"
    events, _, _ = _run(C + ["note.quarter-L2", "chordnote-L2", "chordnote-L2"])
    assert events[-1]["unison_chordnote_dropped"] == "chordnote-L2 chordnote-L2"


def test_override_chord_pitches() -> None:
    events, _, _ = _run(["clef.G-L2", "accidental.sharp-L1", "accidental.flat-S3", "note.quarter-L1",
                         "chordnote-S3"], header_override=s3.HeaderOverride("clef.G-L2", 0, 0))
    assert _pitches(events) == [65, 71]


def test_chordnote_below_base_kept_and_flagged() -> None:
    events, _, _ = _run(C + ["note.quarter-L3", "chordnote-L1"])
    notes = _notes(events)
    assert [e["pitch"] for e in notes] == [71, 64]
    assert notes[0]["chord_id"] == notes[1]["chord_id"] is not None
    assert notes[1]["chordnote_below_base"] == "chordnote-L1"
    assert notes[1]["review_needed"] is True
    assert "chordnote_below_base" not in notes[0]


def test_member_and_chord_confidence() -> None:
    pairs = [("clef.G-L2", 0.99), ("metersign.C-L3", 0.99), ("note.quarter-L2", 0.99), ("accidental.sharp-S3", 0.6),
             ("note.quarter-L1", 0.9), ("chordnote-S3", 0.95)]
    events, _, _ = _run([t for t, _ in pairs], confidences=[c for _, c in pairs])
    base, member = _notes(events)[-2:]
    assert base["confidence"] == 0.9
    assert member["confidence"] == 0.6
    assert base["chord_confidence"] == member["chord_confidence"] == 0.6
    assert "chord_confidence" not in _notes(events)[0]


def test_no_chord_confidence_without_confidences() -> None:
    events, _, _ = _run(C + ["note.quarter-L1", "chordnote-S3"])
    assert len(_notes(events)) == 2
    assert all("chord_confidence" not in e and "confidence" not in e for e in events)


def test_v1_interval_over_twelve_flagged() -> None:
    events, _, _ = _run(C + ["note.quarter-L1", "chordnote-L5", "note.quarter-L1", "chordnote-S4"])
    wide, octave = _notes(events)[:2], _notes(events)[2:]
    assert [e["pitch"] for e in wide] == [64, 77]
    assert all(e.get("chord_interval_over_octave") is True and e["review_needed"] is True for e in wide)
    assert [e["pitch"] for e in octave] == [64, 76]
    assert all("chord_interval_over_octave" not in e for e in octave)


def test_v2_three_members_flagged() -> None:
    events, _, _ = _run(C + ["note.quarter-L1", "chordnote-L2", "chordnote-L3", "note.quarter-L1", "chordnote-L2"])
    triad, dyad = _notes(events)[:3], _notes(events)[3:]
    assert len({e["chord_id"] for e in triad}) == 1
    assert all(e.get("chord_three_plus_members") is True and e["review_needed"] for e in triad)
    assert all("chord_three_plus_members" not in e for e in dyad)


def test_v4_range_only_on_chord_members() -> None:
    # Soprano 58-86: A3 (57) is out of range. A monophonic A3 is not checked (V1/V2/V4 only apply to chords).
    events, _, _ = _run(C + ["note.quarter-L-1", "chordnote-L1", "note.quarter-L-1"])
    low, high, mono = _notes(events)
    assert (low["pitch"], high["pitch"], mono["pitch"]) == (57, 64, 57)
    assert low["chord_member_out_of_range"] is True and low["review_needed"] is True
    assert "chord_member_out_of_range" not in high
    assert "chord_member_out_of_range" not in mono and "review_needed" not in mono


# ── Task 4: dots on chords ───────────────────────────────────────────────────

def test_dotted_dyad_one_dot() -> None:
    events, _, _ = _run(C + ["note.half-L2", "chordnote-L3", "dot-S2", "dot-S3", "note.quarter-L2"])
    notes = _notes(events)
    assert [e["duration_ticks"] for e in notes[:2]] == [1440, 1440]
    assert notes[2]["tick_onset"] == 1440


def test_double_dotted_dyad() -> None:
    events, _, _ = _run(C + ["note.half-L2", "chordnote-L3", "dot-S2", "dot-S2", "dot-S3", "dot-S3",
                             "note.quarter-L2"])
    notes = _notes(events)
    assert [e["duration_ticks"] for e in notes[:2]] == [1680, 1680]
    assert notes[2]["tick_onset"] == 1680


def test_mono_misplaced_double_dot_unchanged() -> None:
    events, _, _ = _run(C + ["note.half-L2", "dot-S2", "dot-S3", "note.quarter-L2"])
    notes = _notes(events)
    assert notes[0]["duration_ticks"] == 1680
    assert notes[1]["tick_onset"] == 1680


# ── Task 5: decode with the model's own vocabulary ───────────────────────────

def _ckpt(vocab: Optional[list[str]], rows: int) -> dict[str, Any]:
    state = {"fc.weight": torch.zeros(rows, 4), "fc.bias": torch.zeros(rows)}
    return {"model_state": state} if vocab is None else {"model_state": state, "vocab": vocab}


def test_vocab_for_checkpoint_ext_and_default() -> None:
    ext = s3.VOCAB_EXT_CHORD_TUPLET
    assert s3._vocab_for_checkpoint(_ckpt(list(ext), len(ext))) == ext
    assert s3._vocab_for_checkpoint(_ckpt(None, len(s3.VOCAB))) == s3.VOCAB


def test_vocab_for_checkpoint_rejects_mismatch() -> None:
    shuffled = list(s3.VOCAB)
    shuffled[1], shuffled[2] = shuffled[2], shuffled[1]
    with pytest.raises(ValueError):
        s3._vocab_for_checkpoint(_ckpt(shuffled, len(shuffled)))
    with pytest.raises(ValueError):
        s3._vocab_for_checkpoint(_ckpt(list(s3.VOCAB), len(s3.VOCAB_EXT_CHORD_TUPLET)))
    with pytest.raises(ValueError):
        s3._vocab_for_checkpoint(_ckpt(None, len(s3.VOCAB_EXT_CHORD_TUPLET)))


def _biased_model(vocab_size: int, top_index: int) -> s3.CRNN:
    """A CRNN whose every frame predicts ``top_index``, so the decode is exactly that one token."""
    model = s3.CRNN(vocab_size)
    with torch.no_grad():
        model.fc.weight.zero_()
        model.fc.bias.zero_()
        model.fc.bias[top_index] = 100.0
    return model.eval()


def test_transcribe_strip_ext_model_decodes_chordnote() -> None:
    ext = s3.VOCAB_EXT_CHORD_TUPLET
    model = _biased_model(len(ext), len(ext) - 1)
    img = np.full((64, 256), 255, dtype=np.uint8)
    assert s3.transcribe_strip(img, model, torch.device("cpu")) == [ext[-1]]
    scored = s3.transcribe_strip(img, model, torch.device("cpu"), return_confidence=True)
    assert [t for t, _ in scored] == [ext[-1]]


def test_transcribe_strip_rejects_unknown_head_size() -> None:
    model = _biased_model(len(s3.VOCAB) + 1, 1)
    with pytest.raises(ValueError):
        s3.transcribe_strip(np.full((64, 256), 255, dtype=np.uint8), model, torch.device("cpu"))


def test_load_model_builds_head_from_checkpoint_vocab(tmp_path: Path) -> None:
    ext = s3.VOCAB_EXT_CHORD_TUPLET
    path = tmp_path / "ext.pt"
    torch.save({"model_state": s3.CRNN(len(ext)).state_dict(), "vocab": list(ext), "epoch": 1}, path)
    model, _ = s3.load_model(str(path), torch.device("cpu"))
    assert model.fc.out_features == len(ext)
