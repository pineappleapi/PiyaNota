"""Regression tests for three fixes found in the DSMN evaluation (ml-cv-lead).

1. Stage 3 dot handling must advance the tick cursor by the dotted duration.
2. Stage 3 must carry a header ``slur.end`` (cross-system tie arrival) to the
   first note without inventing a ``slur.start``; Stage 4 must merge the tie.
3. Stage 5 must never leave a note-on without a note-off when a voice has
   same-pitch overlapping notes, and must warn on an empty voice.

Run with ``python -m pytest tests`` (or ``python tests/test_stage3_5_regressions.py``).
These are synthetic, token-level tests: they say nothing about CRNN accuracy.
"""

import contextlib
import io
import struct
import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage3_transcription as s3  # noqa: E402
import stage4_reconstruction as s4  # noqa: E402
import stage5_synthesis as s5  # noqa: E402

QUARTER = 480
DOTTED_QUARTER = 720
HEADER = ["clef.G-L2"]
VOICES = ["Soprano", "Alto", "Tenor", "Bass"]
SMF_NOTE_OFF = 0x80
SMF_NOTE_ON = 0x90


def _infer(tokens: list, voice: str = "Soprano", sys_idx: int = 1) -> list:
    with contextlib.redirect_stdout(io.StringIO()):
        return s3.infer_pitch(tokens, voice=voice, page_index=1, sys_idx=sys_idx)


# ── 1. dot advances the cursor ───────────────────────────────────────────────

def test_dot_advances_tick_cursor() -> None:
    ev = _infer(HEADER + ["note.quarter-L2", "dot-S2", "note.eighth-L3", "note.quarter-L3"])
    assert [e["duration_ticks"] for e in ev] == [DOTTED_QUARTER, 240, QUARTER]
    assert [e["tick_onset"] for e in ev] == [0, DOTTED_QUARTER, DOTTED_QUARTER + 240]


def test_dot_on_rest_advances_tick_cursor() -> None:
    ev = _infer(HEADER + ["rest.quarter-L3", "dot-S3", "note.eighth-L3"])
    assert ev[1]["tick_onset"] == DOTTED_QUARTER


def test_no_event_overlaps_next_in_dotted_voice() -> None:
    ev = _infer(HEADER + ["note.half-L2", "dot-S2", "note.quarter-L3", "barline-L1",
                          "note.quarter-L2", "dot-S2", "note.eighth-L2", "note.half-L2"])
    for a, b in zip(ev, ev[1:]):
        assert a["tick_onset"] + a["duration_ticks"] <= b["tick_onset"]


def test_undotted_sequence_unchanged() -> None:
    ev = _infer(HEADER + ["note.quarter-L2", "note.quarter-L3", "note.half-L3"])
    assert [e["tick_onset"] for e in ev] == [0, QUARTER, 2 * QUARTER]


# ── 2. orphan slur.end ───────────────────────────────────────────────────────

def test_header_slur_end_carried_to_first_note_without_start() -> None:
    ev = _infer(HEADER + ["slur.end-L2", "note.quarter-L2", "note.quarter-L3"])
    assert [e["slur"] for e in ev] == ["end", None]


def test_header_slur_end_before_clef_carried() -> None:
    ev = _infer(["slur.end-L2", "clef.G-L2", "note.quarter-L2"])
    assert ev[0]["slur"] == "end"


def test_header_slur_start_still_not_invented() -> None:
    ev = _infer(HEADER + ["slur.start-L2", "note.quarter-L2"])
    assert ev[0]["slur"] != "end"


def test_slur_end_pending_cleared_by_rest() -> None:
    ev = _infer(HEADER + ["slur.end-L2", "rest.quarter-L3", "note.quarter-L2"])
    assert [e["slur"] for e in ev if e["type"] == "note"] == [None]


def _two_system_feed(sys1_last: list, sys2_first: list) -> dict:
    feed = {}
    for voice in VOICES:
        a = _infer(HEADER + ["note.quarter-L2", "note.quarter-L3", "note.quarter-L3"]
                   + sys1_last + ["barline-L1"], voice, sys_idx=1)
        b = _infer(HEADER + sys2_first + ["note.quarter-L3", "note.quarter-L3",
                                          "note.quarter-L2", "barline-L1"], voice, sys_idx=2)
        feed[voice] = a + b
    return feed


def _reconstruct(feed: dict) -> tuple:
    with contextlib.redirect_stdout(io.StringIO()):
        return s4.reconstruct_satb_with_report(feed)


def _first_ties(sat: dict) -> list:
    return [e["tie_span"] for e in sat["Soprano"] if e["type"] == "note"]


def test_cross_system_tie_merges_with_start_and_end() -> None:
    """Corpus token order: slur.start after the last note, slur.end before the first."""
    feed = _two_system_feed(["note.quarter-L4", "slur.start-L4"],
                            ["slur.end-L4", "note.quarter-L4"])
    sat, _ = _reconstruct(feed)
    assert max(_first_ties(sat)) == 2
    merged = [e for e in sat["Soprano"] if e.get("tie_span") == 2][0]
    assert merged["duration_ticks"] == 2 * QUARTER


def test_orphan_end_alone_does_not_invent_a_tie() -> None:
    """slur.end with no slur.start on the previous system must not merge anything."""
    feed = _two_system_feed(["note.quarter-L4"], ["slur.end-L4", "note.quarter-L4"])
    sat, _ = _reconstruct(feed)
    assert max(_first_ties(sat)) == 1
    assert feed["Soprano"][-4]["slur"] == "end"  # marker was carried, not dropped


# ── 3. Stage 5 hanging note-on ───────────────────────────────────────────────

def _note(onset: int, dur: int, pitch: int) -> dict:
    return {"type": "note", "pitch": pitch, "duration_ticks": dur, "tick_onset": onset}


def _count_note_events(path: Path) -> dict:
    """Minimal SMF reader -> {pitch: (n_on, n_off)}; running status handled."""
    data = path.read_bytes()
    pos, counts = 14, {}
    assert data[:4] == b"MThd"
    while pos < len(data):
        assert data[pos:pos + 4] == b"MTrk"
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        chunk, pos = data[pos + 8:pos + 8 + length], pos + 8 + length
        i, run = 0, None
        while i < len(chunk):
            while chunk[i] & 0x80:      # delta-time VLQ
                i += 1
            i += 1
            status = chunk[i]
            if status == 0xFF:
                i += 2
                ln = 0
                while chunk[i] & 0x80:
                    ln = (ln << 7) | (chunk[i] & 0x7F)
                    i += 1
                ln = (ln << 7) | chunk[i]
                i += 1 + ln
                continue
            if status & 0x80:
                run, i = status, i + 1
            kind = run & 0xF0
            n_data = 1 if kind in (0xC0, 0xD0) else 2
            a, b = chunk[i], (chunk[i + 1] if n_data == 2 else 0)
            i += n_data
            if kind == SMF_NOTE_ON and b > 0:
                counts.setdefault(a, [0, 0])[0] += 1
            elif kind == SMF_NOTE_OFF or (kind == SMF_NOTE_ON and b == 0):
                counts.setdefault(a, [0, 0])[1] += 1
    return counts


def _write_and_count(events: list) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        midi = s5.build_voice_midi(events, 90, s5._piece_end_tick({"Soprano": events}))
        path = Path(tmp) / "v.mid"
        with open(path, "wb") as fh:
            midi.writeFile(fh)
        return _count_note_events(path)


def test_same_pitch_overlap_is_clipped_and_balanced() -> None:
    # Reproduces the DSMN shape: a 3-beat note overlapped by the next same-pitch note.
    events = [_note(0, 1440, 65), _note(960, 480, 65), _note(1440, 480, 60)]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        notes = s5.voice_notes(events)
    assert any(issubclass(w.category, RuntimeWarning) for w in caught)
    assert notes[0][1] * s5.PPQ == 960          # clipped to next same-pitch onset
    for n_on, n_off in _write_and_count(events).values():
        assert n_on == n_off


def test_non_overlapping_notes_untouched_and_silent() -> None:
    events = [_note(0, 480, 65), _note(480, 480, 65), _note(960, 480, 60)]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        notes = s5.voice_notes(events)
    assert not caught
    assert [round(d * s5.PPQ) for _, d, _ in notes] == [480, 480, 480]


def test_empty_voice_warns_loudly() -> None:
    seqs = {v: [_note(0, 480, 60)] for v in VOICES}
    seqs["Alto"] = []
    with tempfile.TemporaryDirectory() as tmp, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            files = s5.synthesize_satb(seqs, output_dir=tmp, soundfont_path="missing.sf2")
    assert "Alto" not in files
    assert any("Alto" in str(w.message) for w in caught)
    assert "WARNING" in err.getvalue() and "Alto" in err.getvalue()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
