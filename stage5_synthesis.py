"""
PiyaNota - Stage 5: MIDI-Based Piano Audio Synthesis
Converts reconstructed SATB voice sequences into four separate MP3 files,
one per voice (Soprano, Alto, Tenor, Bass).

Dependencies:
    pip install midiutil pydub
    Also requires ffmpeg installed on the system for MP3 export.
    For piano soundfont rendering: a system fluidsynth on PATH (called directly)
    Download a piano soundfont (.sf2) e.g. GeneralUser GS or FluidR3.
"""

import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Optional
from midiutil import MIDIFile

import stage3_clefkey

from stage3_transcription import CLEF_KEY_DISABLED_FLAG, DEFAULT_TIME_SIGNATURE
from stage4_reconstruction import (FAILURE_INCOMPLETE_VOICE_SEQUENCE, METER_DEFAULT, METER_UNKNOWN,
                                   TICKS_PER_QUARTER, PipelineFailure)

# FluidSynth output sample rate (midi2audio's former default).
RENDER_SAMPLE_RATE = 44100

# ── MIDI constants ────────────────────────────────────────────────────────────
PPQ          = 480          # pulses per quarter note (ticks per beat)
DEFAULT_BPM  = 90           # default tempo if not detected
MS_PER_MINUTE = 60_000
ROUND_HALF_UP = 0.5         # ms values round half up: int(x + 0.5), same rule as the timing file
# PIYA-103 AC10: the review code for a voice in failedVoices.
VOICE_FAILED_CODE = "voice_failed"
# PIYA-109 AC9 (amended 2026-10-14): every voice failed and ALL four had events after Stage 4, so rendering
# (server side) broke, not the capture; no retake. If any failed voice was empty, a retake can help, so the
# job fails with Stage 4's FAILURE_INCOMPLETE_VOICE_SEQUENCE instead.
FAILURE_SYNTHESIS = "synthesis_failed"
# PIYA-109 AC10 / PIYA-103 AC10 failedVoiceCauses values: the app offers a retake only for UNREADABLE.
CAUSE_UNREADABLE = "unreadable"          # empty after Stage 4 (in its report["failed_voices"])
CAUSE_RENDER_FAILED = "render_failed"    # had events, Stage 5 could not produce its audio
# A pipeline invariant broke (a bug, not the user's photo): retry-later copy,
# never a recapture prompt.
FAILURE_INTERNAL_ERROR = "internal_error"
# Client-facing review items are capped; the full list goes to the job record (backend-lead review
# 2026-09-29: Stage 4 bar flags are unbounded, strips are at most 20 pages x 16 staves).
REVIEW_ITEMS_CAP = 200
# Reasons that apply to the whole job, not to one strip; reported once in `reasons`, never as items.
JOB_LEVEL_REVIEW_CODES = frozenset({stage3_clefkey.CLEF_KEY_UNVALIDATED_FLAG, CLEF_KEY_DISABLED_FLAG})
MIDI_CHANNEL = 0            # piano channel
MIDI_VOLUME  = 100          # note velocity (0–127)
PIANO_PROGRAM = 0           # General MIDI program 0 = Acoustic Grand Piano
SUSTAIN_PEDAL_CC = 64       # controller used only as an end-of-piece length pin

# Stage 4 places events in ticks of TICKS_PER_QUARTER; onset_beats = tick / PPQ
# is only correct while both use the same resolution.
if PPQ != TICKS_PER_QUARTER:
    raise RuntimeError(
        f"Stage 5 PPQ ({PPQ}) != Stage 4 TICKS_PER_QUARTER ({TICKS_PER_QUARTER})")

# Voice → MIDI track index
VOICE_TRACK = {
    "Soprano": 0,
    "Alto":    1,
    "Tenor":   2,
    "Bass":    3,
}

VOICES = ["Soprano", "Alto", "Tenor", "Bass"]


# ── Main synthesis function ───────────────────────────────────────────────────

def synthesize_satb(
    satb_sequences:  dict,
    output_dir:      str  = "output/audio",
    bpm:             int  = DEFAULT_BPM,
    soundfont_path:  str  = "soundfont/piano.sf2",
    muted_spans:     Optional[dict[str, list[tuple[int, int]]]] = None,
) -> dict:
    """
    Converts four SATB voice event sequences into four MP3 files.

    Kept for the CLI and older callers: a voice whose MP3 cannot be rendered
    falls back to its MIDI path here. The API path uses
    ``synthesize_satb_with_failures``, where that voice fails instead
    (PIYA-109 AC9), because a client cannot play a .mid track.

    Args:
        satb_sequences:  Output of Stage 4 reconstruct_satb().
                         {voice: [event_dict, ...]}
        output_dir:      Directory where MP3 files will be saved.
        bpm:             Playback tempo in beats per minute.
        soundfont_path:  Path to a .sf2 piano soundfont for rendering.
        muted_spans:     {voice: [(start_tick, end_tick), ...]} to render as
                         silence (PIYA-109 AC8); see ``muted_spans_by_voice``.

    Returns:
        {voice: mp3_path} dict of output file paths.
    """
    files, _ = _synthesize(satb_sequences, output_dir, bpm, soundfont_path, muted_spans or {},
                           midi_fallback=True)
    return files


def synthesize_satb_with_failures(
    satb_sequences:  dict,
    output_dir:      str,
    bpm:             int,
    soundfont_path:  str,
    muted_spans:     dict[str, list[tuple[int, int]]],
) -> tuple[dict[str, str], list[str]]:
    """Renders every voice it can; returns ({voice: mp3_path}, failed voices in SATB order).

    A voice fails when it has no events or its MP3 cannot be rendered
    (PIYA-109 AC9); the other voices still render. Raising when all four fail
    is the caller's job, so this stays usable for partial re-renders.
    """
    return _synthesize(satb_sequences, output_dir, bpm, soundfont_path, muted_spans,
                       midi_fallback=False)


def _synthesize(
    satb_sequences: dict,
    output_dir:     str,
    bpm:            int,
    soundfont_path: str,
    muted_spans:    dict[str, list[tuple[int, int]]],
    midi_fallback:  bool,
) -> tuple[dict[str, str], list[str]]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n[Stage 5] Synthesizing SATB audio at {bpm} BPM...")

    output_files: dict[str, str] = {}
    failed: list[str] = []
    # Taken before muting so a silenced final bar does not shorten the track.
    total_ticks = _piece_end_tick(satb_sequences)

    for voice in VOICES:
        events = satb_sequences.get(voice, [])
        if not events:
            # Loud on purpose: the caller gets fewer than four tracks, which
            # downstream playback would otherwise treat as a valid result.
            msg = (f"[Stage 5] No events for {voice}: NO audio file will be "
                   f"produced for this voice ({len(output_files)} of "
                   f"{len(VOICES)} so far).")
            print(f"  {msg.replace('[Stage 5]', '[Stage 5] WARNING:', 1)}",
                  file=sys.stderr)
            warnings.warn(msg, RuntimeWarning, stacklevel=3)
            failed.append(voice)
            continue

        spans = muted_spans.get(voice, [])
        if spans:
            events = apply_muted_spans(events, spans)
            print(f"  [Stage 5] {voice}: {len(spans)} damaged span(s) rendered as silence")

        # ── Build single-track MIDI per voice ─────────────────────────────
        midi = build_voice_midi(events, bpm, total_ticks)

        # ── Save MIDI file ─────────────────────────────────────────────────
        midi_path = output_path / f"{voice.lower()}.mid"
        with open(midi_path, "wb") as f:
            midi.writeFile(f)
        print(f"  [Stage 5] {voice}: MIDI saved -> {midi_path}")

        # -- Render MIDI -> WAV -> MP3 --
        mp3_path = output_path / f"{voice.lower()}.mp3"
        wav_path = output_path / f"{voice.lower()}.wav"

        success = _render_to_mp3(midi_path, wav_path, mp3_path, soundfont_path)

        if success:
            output_files[voice] = str(mp3_path)
            print(f"  [Stage 5] {voice}: MP3 saved -> {mp3_path}")
        elif midi_fallback:
            output_files[voice] = str(midi_path)
            print(f"  [Stage 5] {voice}: MP3 rendering failed, "
                  f"returning MIDI -> {midi_path}")
        else:
            failed.append(voice)
            print(f"  [Stage 5] WARNING: {voice}: MP3 rendering failed; voice listed as failed",
                  file=sys.stderr)

    _report(output_files)
    return output_files, failed


# ── MIDI construction ─────────────────────────────────────────────────────────

def _piece_end_tick(satb_sequences: dict) -> int:
    """Latest event end (onset + duration, rests included) over all voices."""
    return max(
        (e["tick_onset"] + e["duration_ticks"]
         for voice in VOICES for e in satb_sequences.get(voice, [])),
        default=0)


def voice_notes(events: list) -> list:
    """
    Audible notes of one voice as (onset_beats, duration_beats, pitch).

    tick_onset is Stage 4's global tick (PPQ per quarter), so beats are a
    plain division -- rests need no output, their time is the gap between
    onsets. Kept separate from MIDIFile construction so tests can assert on
    it without parsing MIDI bytes.
    Identical (onset, pitch) notes collapse to one (the longest), so a
    duplicated chord note never sounds twice at double velocity.
    """
    longest: dict = {}
    for e in events:
        if (e["type"] != "note" or e["pitch"] is None
                or e["duration_ticks"] <= 0):
            continue
        key = (e["tick_onset"], e["pitch"])
        longest[key] = max(longest.get(key, 0), e["duration_ticks"])
    # Same-pitch overlap within one voice: the earlier note is clipped to the
    # next same-pitch onset. Left overlapping, a MIDI writer/synth can pair
    # note-offs with the wrong note-on and leave a note hanging (observed:
    # 44 note-ons vs 43 note-offs). A monophonic voice never needs two
    # sounding copies of one pitch, so clipping loses nothing audible.
    by_pitch: dict = {}
    for (tick, pitch), dur in sorted(longest.items()):
        by_pitch.setdefault(pitch, []).append([tick, dur])
    clipped = 0
    for runs in by_pitch.values():
        for cur, nxt in zip(runs, runs[1:]):
            if cur[0] + cur[1] > nxt[0]:
                cur[1] = nxt[0] - cur[0]      # nxt onset > cur onset: dict keys are unique
                clipped += 1
    if clipped:
        warnings.warn(
            f"[Stage 5] {clipped} same-pitch overlapping note(s) clipped to "
            "the next same-pitch onset (upstream tick/duration inconsistency)",
            RuntimeWarning, stacklevel=2)
    return sorted((tick / PPQ, dur / PPQ, pitch)
                  for pitch, runs in by_pitch.items() for tick, dur in runs)


def build_voice_midi(events: list, bpm: int, total_ticks: int) -> MIDIFile:
    """
    Single-track MIDI for one voice, padded to `total_ticks`.

    midiutil ends a track at its last event, so a voice that rests while
    others still sing (or ends earlier) would otherwise be shorter and drift
    out of sync when the four files are played together. A harmless
    sustain-pedal-off controller event at `total_ticks` pins every voice's
    track to the same length. Note: callers pass _piece_end_tick(), which is
    the end of the LAST EVENT over all voices, not the last full bar's end, so
    the padding can stop short of a bar line when the final bar is underfull.
    """
    midi = MIDIFile(1, ticks_per_quarternote=PPQ)
    track = 0
    midi.addTempo(track, 0, bpm)
    midi.addProgramChange(track, MIDI_CHANNEL, 0, PIANO_PROGRAM)
    for onset_beats, duration_beats, pitch in voice_notes(events):
        midi.addNote(
            track    = track,
            channel  = MIDI_CHANNEL,
            pitch    = pitch,
            time     = onset_beats,
            duration = duration_beats,
            volume   = MIDI_VOLUME,
        )
    midi.addControllerEvent(track, MIDI_CHANNEL, total_ticks / PPQ,
                            SUSTAIN_PEDAL_CC, 0)
    return midi


# ── Audio rendering ───────────────────────────────────────────────────────────

def _render_to_mp3(
    midi_path:     Path,
    wav_path:      Path,
    mp3_path:      Path,
    soundfont_path: str,
) -> bool:
    """
    Renders a MIDI file to MP3 using FluidSynth + pydub.

    Requires:
        - FluidSynth installed (fluidsynth command available)
        - pydub installed (pip install pydub; on Python 3.13+ also audioop-lts)
        - ffmpeg installed for MP3 export
        - A valid .sf2 soundfont file

    Returns True on success, False on failure.
    """
    try:
        from pydub import AudioSegment

        sf_path = Path(soundfont_path)
        if not sf_path.exists():
            print(f"  [Stage 5] WARNING: Soundfont not found at {sf_path}. "
                  f"Download a piano .sf2 and set --soundfont.")
            return False

        fluidsynth = shutil.which("fluidsynth")
        if fluidsynth is None:
            print("  [Stage 5] WARNING: fluidsynth not found on PATH.")
            return False

        # MIDI → WAV via FluidSynth. Options must come before the soundfont and MIDI file:
        # FluidSynth 2.x ignores options placed after them (midi2audio's order), which left no WAV.
        subprocess.run(
            [fluidsynth, "-ni", "-F", str(wav_path), "-r", str(RENDER_SAMPLE_RATE),
             str(sf_path), str(midi_path)],
            check=True, capture_output=True, text=True,
        )
        if not wav_path.exists():
            print(f"  [Stage 5] Rendering error: fluidsynth wrote no WAV at {wav_path}")
            return False

        # WAV → MP3 via pydub + ffmpeg
        audio = AudioSegment.from_wav(str(wav_path))
        audio.export(str(mp3_path), format="mp3", bitrate="192k")

        # Clean up WAV
        wav_path.unlink(missing_ok=True)

        return True

    except ImportError as e:
        print(f"  [Stage 5] Missing dependency: {e}. "
              f"Install with: pip install pydub")
        return False
    except subprocess.CalledProcessError as e:
        print(f"  [Stage 5] fluidsynth failed ({e.returncode}): {e.stderr.strip()}")
        return False
    except Exception as e:
        print(f"  [Stage 5] Rendering error: {e}")
        return False


# ── Reporting ─────────────────────────────────────────────────────────────────

def _report(output_files: dict):
    print("\n[Stage 5] Output files:")
    for voice, path in output_files.items():
        ext = Path(path).suffix.upper().lstrip(".")
        print(f"  {voice}: {path} [{ext}]")
    print()


# ── Muted measures, failed voices, measure table (PIYA-103 AC9/AC10, PIYA-109 AC8/AC9, PIYA-117 AC9) ──

def tick_to_ms(tick: int, bpm: int) -> int:
    """Global tick -> milliseconds at ``bpm`` quarter notes per minute, rounded half up.

    One rounding rule for the bars table, mutedMeasures and the timing file keeps
    every ms value in the API on the same clock.
    """
    return int(tick * MS_PER_MINUTE / (PPQ * bpm) + ROUND_HALF_UP)


def muted_spans_by_voice(stage4_flags: list[dict[str, Any]]) -> dict[str, list[tuple[int, int]]]:
    """{voice: [(start_tick, end_tick), ...]} for every Stage 4 flag marked muted (PIYA-108 AC8)."""
    spans: dict[str, list[tuple[int, int]]] = {}
    for f in stage4_flags:
        if f.get("muted") and f.get("voice") in VOICE_TRACK:
            spans.setdefault(f["voice"], []).append((int(f["start_tick"]), int(f["end_tick"])))
    return spans


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def apply_muted_spans(events: list[dict[str, Any]],
                      spans: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Copies of ``events`` with every span silenced (PIYA-109 AC8).

    Each note is split at the span edges: the part before a span plays, the
    part inside is dropped, and the part after is struck again at the span
    end. Stage 4 merges ties before this runs, so one event can be a tie chain
    from a damaged bar into a clean one (or across a whole damaged bar); only
    the damaged bar may go silent (senior-reviewer / choral-conductor
    2026-10-09). A note wholly inside a span is dropped. Rests and other
    events are kept so the timeline is unchanged. Output is ordered by onset.

    A split note becomes several events, so the output can hold MORE events
    than the input (every member of a chord is split the same way). The
    timing file (PIYA-117) must therefore be built from the pre-mute ``satb``,
    never from this output: the client shows the written notes and silences
    the muted spans itself from ``mutedMeasures``. ``restruck_after_mute`` on a
    piece is internal to rendering (it marks a re-attack the score does not
    have) and is not part of any API payload.
    """
    merged = _merge_spans(spans)
    out: list[dict[str, Any]] = []
    for e in events:
        if e["type"] != "note" or not merged:
            out.append(e)
            continue
        onset, end = e["tick_onset"], e["tick_onset"] + e["duration_ticks"]
        pieces: list[tuple[int, int]] = []
        cur = onset
        for start, stop in merged:
            if stop <= cur or start >= end:
                continue
            if start > cur:
                pieces.append((cur, start))
            cur = stop
            if cur >= end:
                break
        if cur < end:
            pieces.append((cur, end))
        if pieces == [(onset, end)]:
            out.append(e)
            continue
        for piece_start, piece_end in pieces:
            piece = {**e, "tick_onset": piece_start, "duration_ticks": piece_end - piece_start}
            if piece_start != onset:
                piece["restruck_after_mute"] = True
            out.append(piece)
    out.sort(key=lambda ev: ev["tick_onset"])
    return out


def _is_muted_entry(flag: dict[str, Any], failed_lower: set[str]) -> bool:
    """True if a Stage 4 flag becomes a ``mutedMeasures`` entry (a failed voice has none, AC10)."""
    return (bool(flag.get("muted")) and flag.get("voice") in VOICE_TRACK
            and flag["voice"].lower() not in failed_lower)


def _zero_based(index: Optional[int]) -> Optional[int]:
    """Pipeline indices count from 1; API indices count from 0 (PIYA-117 "Index bases")."""
    return None if index is None else index - 1


def build_muted_measures(stage4_flags: list[dict[str, Any]], bpm: int,
                         failed_voices: list[str]) -> list[dict[str, Any]]:
    """PIYA-103 AC9 ``mutedMeasures``: one entry per silenced span, by start tick then SATB order.

    A failed voice has no entries (AC10): nothing of it plays, so nothing was muted.
    """
    failed = {v.lower() for v in failed_voices}
    entries = []
    for f in sorted((f for f in stage4_flags if _is_muted_entry(f, failed)), key=_muted_order):
        entries.append({
            "voice": f["voice"].lower(), "bar": f.get("bar"),
            "pageIndex": _zero_based(f.get("page_index")),
            "systemIndex": _zero_based(f.get("sys_idx")),
            "startMs": tick_to_ms(f["start_tick"], bpm), "endMs": tick_to_ms(f["end_tick"], bpm),
            "reason": f["kind"]})
    return entries


def _muted_order(flag: dict[str, Any]) -> tuple[int, int]:
    """Shared sort key so ``mutedMeasures`` and the muted ``review.items`` list in the same order.

    Ticks, not ms: two spans can round to the same ms and then tie-break differently.
    """
    return flag["start_tick"], VOICES.index(flag["voice"])


def _meter_parts(time_signature: str) -> tuple[Optional[int], Optional[int]]:
    try:
        num, den = (int(part) for part in time_signature.split("/"))
    except (ValueError, AttributeError):
        return None, None
    return num, den


def build_bars_table(report: dict[str, Any], bpm: int) -> list[dict[str, Any]]:
    """PIYA-117 AC9 ``bars`` from Stage 4's report: one entry per measure, tiling from tick 0.

    Built from the layout, not from events, so a measure where a voice rests,
    failed or was muted still has its entry. ``durMs`` is the next entry's
    ``startMs`` minus this one's, so rounding never opens a gap. The table
    ends at the last layout bar; the audio can run slightly past it (a note
    held over the final barline).

    Raises:
        PipelineFailure: ``internal_error`` when the tiled startTicks disagree
            with a system's ``start_tick`` (the table and the audio would drift
            apart). That is a Stage 4 invariant breaking, not a capture problem.
    """
    rows: list[tuple[int, int, int, dict[str, Any]]] = []      # (bar, startTick, durTicks, meter bar)
    systems = sorted(report.get("systems", []), key=lambda s: s["start_tick"])
    all_bars = [(sys["first_bar"] + i, bar) for sys in systems for i, bar in enumerate(sys.get("bars", []))]
    pickup = int(report.get("pickup_ticks") or 0)
    tick = 0
    if pickup > 0:
        # The pickup carries the meter it was engraved under (the opening meter, which Stage 4 measured
        # it against), so the client places its clicks as the end of a full bar.
        opening = systems[0].get("opening_meter") if systems else None
        first = opening or (all_bars[0][1] if all_bars else {"time_signature": DEFAULT_TIME_SIGNATURE,
                                                             "meter_source": METER_DEFAULT})
        rows.append((0, 0, pickup, first))
        tick = pickup
    starts = {sys["first_bar"]: sys["start_tick"] for sys in systems}
    for bar_no, bar in all_bars:
        if bar_no in starts and starts[bar_no] != tick:
            raise PipelineFailure(FAILURE_INTERNAL_ERROR,
                                  f"bars table drift: bar {bar_no} tiles to tick {tick}, "
                                  f"Stage 4 starts its system at {starts[bar_no]}")
        dur = int(bar.get("actual_ticks", bar["ticks"]))
        rows.append((bar_no, tick, dur, bar))
        tick += dur

    table = []
    for i, (bar_no, start, dur, bar) in enumerate(rows):
        source = bar.get("meter_source", METER_DEFAULT)
        num, den = (None, None) if source == METER_UNKNOWN else _meter_parts(bar["time_signature"])
        start_ms = tick_to_ms(start, bpm)
        end_ms = tick_to_ms(rows[i + 1][1], bpm) if i + 1 < len(rows) else tick_to_ms(start + dur, bpm)
        table.append({"bar": bar_no, "startMs": start_ms, "durMs": end_ms - start_ms,
                      "startTick": start, "durTicks": dur, "numerator": num, "denominator": den,
                      "meterSource": source, "pickup": bar_no == 0, "groups": None})
    return table


# ── Review summary (exposed by the result API, PIYA-103 AC6) ──────────────────

def build_review(stage3_events: dict, stage4_flags: list, failed_voices: Optional[list[str]] = None,
                 eventless_strip_flags: Optional[list[dict[str, Any]]] = None,
                 ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Maps Stage 3 strip flags and Stage 4 reconstruction flags onto the API's fixed review shape.

    The mapping is explicit so a change in Stage 3/4's internal flag dicts can't change the public
    contract. ``reviewNeeded: False`` only means nothing was flagged, not that the transcription is right.
    A strip's codes become items only when that strip's own flags carry ``review_needed``: informational
    codes (e.g. ``plain_treble_on_low_voice_assumed_8vb``) must not make a clean score need review once
    the classifier passes its gate. Stage 3 ``meter_flags`` (digits the parser could not place) always
    need review.

    Item order decides what the REVIEW_ITEMS_CAP can hide (a long score has up to 320 strips and
    unbounded bar flags): failed voices first (a whole part is gone, PIYA-103 AC10), then muted
    measures in ``mutedMeasures`` order (so every one has its item unless ``truncated``, AC9), then
    other Stage 4 bar flags, then per-strip flags.

    Index bases (PIYA-117 "Index bases"): snake_case ``page_index`` / ``sys_idx`` are the pipeline's
    1-based values; every camelCase ``pageIndex`` / ``systemIndex`` written here is 0-based, converted
    where the name changes. That includes ``full_items``, which goes to the job record; the backend
    must not convert again.

    Args:
        stage3_events: {voice: [event, ...]} from Stage 3 (events carry ``clef_key_flags`` and, with
            ClefKeyNet, ``clef_key_strip_flags``).
        stage4_flags: ``reconstruct_satb_with_report``'s ``flags``; only those with ``review_needed`` count.
        failed_voices: voices (any case) listed in ``failedVoices``.
        eventless_strip_flags: Stage 3's ``strip_flags_out``: meter flags of strips that produced no
            events, which therefore cannot ride on an event.

    Returns:
        (review, full_items): ``review`` is the client object with at most REVIEW_ITEMS_CAP items;
        ``full_items`` is the uncapped list for the job record.
    """
    job_reasons: set[str] = set()
    failed = {v.lower() for v in failed_voices or []}

    def stage4_item(f: dict[str, Any]) -> dict[str, Any]:
        return {"code": f["kind"], "voice": f["voice"].lower() if f.get("voice") else None,
                "pageIndex": _zero_based(f.get("page_index")),
                "systemIndex": _zero_based(f.get("sys_idx")), "bar": f.get("bar")}

    items: list[dict[str, Any]] = [
        {"code": VOICE_FAILED_CODE, "voice": v.lower(), "pageIndex": None, "systemIndex": None, "bar": None}
        for v in VOICES if v.lower() in failed]
    flagged = [f for f in stage4_flags if f.get("review_needed")]
    muted = [f for f in flagged if _is_muted_entry(f, failed)]
    muted.sort(key=_muted_order)
    items += [stage4_item(f) for f in muted]
    items += [stage4_item(f) for f in flagged if not _is_muted_entry(f, failed)]

    seen_strips: set[tuple] = set()

    def strip_items(voice: str, page_index: int, sys_idx: int, codes: set[str]) -> None:
        for code in sorted(codes):
            key = (voice, page_index, sys_idx, code)
            if key not in seen_strips:
                seen_strips.add(key)
                items.append({"code": code, "voice": voice.lower(), "pageIndex": _zero_based(page_index),
                              "systemIndex": _zero_based(sys_idx), "bar": None})

    for voice, events in stage3_events.items():
        for e in events:
            job_reasons |= set(e.get("clef_key_flags", [])) & JOB_LEVEL_REVIEW_CODES
            strip_flags = set(e.get("clef_key_strip_flags", []))
            codes = set(e.get("meter_flags", []))
            if "review_needed" in strip_flags:
                codes |= strip_flags - {"review_needed"} - JOB_LEVEL_REVIEW_CODES
            strip_items(voice, e["page_index"], e["sys_idx"], codes)
    for strip in eventless_strip_flags or []:
        strip_items(strip["voice"], strip["page_index"], strip["sys_idx"], set(strip["meter_flags"]))
    reasons = sorted(job_reasons | {i["code"] for i in items})
    review = {"reviewNeeded": bool(reasons), "reasons": reasons, "items": items[:REVIEW_ITEMS_CAP],
              "truncated": len(items) > REVIEW_ITEMS_CAP}
    return review, items


# ── Full pipeline helper ──────────────────────────────────────────────────────

def run_full_pipeline(
    input_dir:      str = "data/raw",
    prep_dir:       str = "data/preprocessed",
    strips_dir:     str = "data/strips",
    output_dir:     str = "output/audio",
    crnn_weights:   str = "crnn_weights/best.pt",
    yolo_weights:   str = "staff_detector_files/weights/best.pt",
    soundfont_path: str = "soundfont/piano.sf2",
    bpm:            int = DEFAULT_BPM,
    img_height:     int = 64,
    clef_key_weights: Optional[str] = str(stage3_clefkey.DEFAULT_CLEF_KEY_CHECKPOINT),
) -> dict:
    """
    Runs the complete PiyaNota pipeline from raw images to MP3 files.
    Stages 1 → 2 → 3 → 4 → 5. Returns {voice: path}; the API uses run_full_pipeline_with_report.

    clef_key_weights: ClefKeyNet checkpoint for Stage 3's clef/key/octave (default: the pinned
    checkpoint; a missing file raises). None opts out: clef/key come from the CRNN (BUG-011) and every
    event is flagged clef_key_disabled / review_needed.
    """
    return run_full_pipeline_with_report(input_dir, prep_dir, strips_dir, output_dir, crnn_weights,
                                         yolo_weights, soundfont_path, bpm, img_height,
                                         clef_key_weights)["audio"]


def run_full_pipeline_with_report(
    input_dir:      str = "data/raw",
    prep_dir:       str = "data/preprocessed",
    strips_dir:     str = "data/strips",
    output_dir:     str = "output/audio",
    crnn_weights:   str = "crnn_weights/best.pt",
    yolo_weights:   str = "staff_detector_files/weights/best.pt",
    soundfont_path: str = "soundfont/piano.sf2",
    bpm:            int = DEFAULT_BPM,
    img_height:     int = 64,
    clef_key_weights: Optional[str] = str(stage3_clefkey.DEFAULT_CLEF_KEY_CHECKPOINT),
) -> dict[str, Any]:
    """Runs Stages 1-5 and returns the audio plus what the result API and job record need.

    A voice that is empty after Stage 4 or cannot be rendered is listed in
    ``failedVoices`` and the job still completes. It fails only when all four
    voices fail (PIYA-108 AC4/AC5, PIYA-109 AC9), with a PipelineFailure whose
    ``failure_reason`` is ``incomplete_voice_sequence`` when at least one of
    them was empty after Stage 4 (whole-score retake), else
    ``synthesis_failed`` (all four were read; a server-side rendering fault,
    no retake).

    Returns:
        {"audio": {voice: mp3 path}, failed voices left out,
         "bars": PIYA-117 AC9 measure table (see build_bars_table),
         "mutedMeasures": PIYA-103 AC9 (see build_muted_measures),
         "failedVoices": PIYA-103 AC10, lowercase, SATB order,
         "failedVoiceCauses": PIYA-109 AC10, {lowercase voice: CAUSE_UNREADABLE | CAUSE_RENDER_FAILED},
                              keys exactly failedVoices ({} when none),
         "review": client object for PIYA-103 (see build_review),
         "review_detail": uncapped review items for the job record,
         "provenance": INTERNAL ONLY (job record and logs, never the client response; backend-lead
                       2026-09-29): classifier on/off, checkpoint sha256, gate status}.
    """
    from stage3_transcription  import run_stages_1_to_3
    from stage4_reconstruction import reconstruct_satb_with_report

    print("=" * 60)
    print("PiyaNota — Full Pipeline")
    print("=" * 60)

    # Stages 1-3
    eventless_strip_flags: list[dict[str, Any]] = []
    voice_events = run_stages_1_to_3(input_dir, prep_dir, strips_dir, yolo_weights, crnn_weights,
                                     clef_key_weights, img_height=img_height,
                                     strip_flags_out=eventless_strip_flags)

    # Stage 4
    satb, recon_report = reconstruct_satb_with_report(voice_events)
    provenance = {
        "clefKeyEnabled": clef_key_weights is not None,
        "clefKeyCheckpointSha256": (stage3_clefkey.file_sha256(Path(clef_key_weights))
                                    if clef_key_weights is not None else None),
        "clefKeyGatePassed": stage3_clefkey.CLEF_KEY_GATE_PASSED,
    }

    # Stage 5
    mp3_files, failed = synthesize_satb_with_failures(
        satb, output_dir, bpm, soundfont_path, muted_spans_by_voice(recon_report["flags"]))
    unreadable = {v.lower() for v in recon_report.get("failed_voices", [])}
    failed_voice_causes = {v.lower(): CAUSE_UNREADABLE if v.lower() in unreadable else CAUSE_RENDER_FAILED
                           for v in failed}
    if len(failed) == len(VOICES):
        rendered_but_failed = [v for v in failed if failed_voice_causes[v.lower()] == CAUSE_RENDER_FAILED]
        reason = (FAILURE_INCOMPLETE_VOICE_SEQUENCE if CAUSE_UNREADABLE in failed_voice_causes.values()
                  else FAILURE_SYNTHESIS)
        raise PipelineFailure(reason, f"no voice could be rendered (render failures: "
                                      f"{', '.join(rendered_but_failed) or 'none'})")
    failed_voices = [v.lower() for v in failed]
    review, review_detail = build_review(voice_events, recon_report["flags"], failed_voices,
                                         eventless_strip_flags)

    print("=" * 60)
    print("PiyaNota complete.")
    for voice, path in mp3_files.items():
        print(f"  {voice}: {path}")
    print("=" * 60)

    return {"audio": mp3_files,
            "bars": build_bars_table(recon_report, bpm),
            "mutedMeasures": build_muted_measures(recon_report["flags"], bpm, failed_voices),
            "failedVoices": failed_voices,
            "failedVoiceCauses": failed_voice_causes,
            "review": review, "review_detail": review_detail, "provenance": provenance}


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="PiyaNota Stage 5 — MIDI-Based Piano Audio Synthesis")
    parser.add_argument("--input",     default="data/raw",
                        help="Raw score images directory")
    parser.add_argument("--prep",      default="data/preprocessed")
    parser.add_argument("--strips",    default="data/strips")
    parser.add_argument("--output",    default="output/audio",
                        help="Output directory for MP3 files")
    parser.add_argument("--weights",   default="crnn_weights/best.pt")
    parser.add_argument("--yolo",      default="staff_detector_files/weights/best.pt")
    parser.add_argument("--soundfont", default="soundfont/piano.sf2",
                        help="Path to .sf2 piano soundfont")
    parser.add_argument("--bpm",       type=int, default=DEFAULT_BPM,
                        help="Playback tempo in BPM")
    parser.add_argument("--img-height", type=int, default=64)
    stage3_clefkey.add_clef_key_args(parser)
    args = parser.parse_args()

    mp3s = run_full_pipeline(
        input_dir      = args.input,
        prep_dir       = args.prep,
        strips_dir     = args.strips,
        output_dir     = args.output,
        crnn_weights   = args.weights,
        yolo_weights   = args.yolo,
        soundfont_path = args.soundfont,
        bpm            = args.bpm,
        img_height     = args.img_height,
        clef_key_weights = stage3_clefkey.clef_key_arg(args),
    )

    print(f"\nStage 5 complete. {len(mp3s)} audio file(s) ready.")
