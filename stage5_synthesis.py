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

# DEFENSE INDEX: (Ctrl+F the tag to jump to the explanation)
#   DEFENSE: stage role        - what Stage 5 does in one breath
#   DEFENSE: dry render        - why reverb/chorus are switched off
#   DEFENSE: loudness target   - why every stem is made equally loud
#   DEFENSE: ppq check         - why PPQ must equal Stage 4's resolution
#   DEFENSE: client review     - why only two review codes reach the app
#   DEFENSE: silent track      - why an empty voice still gets a file
#   DEFENSE: midi fallback     - why MIDI is returned when MP3 fails
#   DEFENSE: collapse notes    - why identical notes merge into one
#   DEFENSE: clip overlap      - why same-pitch overlaps are shortened
#   DEFENSE: pad same length   - why all four voices end at the same time
#   DEFENSE: fluidsynth order  - why options come before the soundfont
#   DEFENSE: normalise loudness - where gain is applied to the audio
#   DEFENSE: peak ceiling      - why a peaky stem stays quieter than target
#   DEFENSE: review shape      - why build_review maps flags explicitly
#   DEFENSE: pipeline entry    - how Stages 1-5 chain together

import os
import re
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Optional
from midiutil import MIDIFile

import stage3_clefkey

from stage3_transcription import CLEF_KEY_DISABLED_FLAG
from stage4_reconstruction import TICKS_PER_QUARTER

# DEFENSE: stage role - Stage 5 takes the note lists from Stage 4 and does three simple things per
# voice: write a MIDI file, let FluidSynth "play" it with a piano soundfont into a WAV, then
# turn the WAV into an MP3. One file per voice (Soprano, Alto, Tenor, Bass).
# FluidSynth output sample rate (midi2audio's former default).
RENDER_SAMPLE_RATE = 44100

# DEFENSE: dry render - reverb is the "echo in a church" effect. We turn it off so each voice
# sounds clean and a singer can hear the exact notes; the app can add room sound later.
# FluidSynth turns reverb and chorus on by default, which smeared the voices and sounded wrong on phone
# playback (user phone test 2026-11-07, item E). Off gives a dry piano; the app can add room sound later.
FLUIDSYNTH_DRY_SETTINGS = ["-o", "synth.reverb.active=0", "-o", "synth.chorus.active=0"]

# DEFENSE: loudness target - the four voices are rendered separately, so some come out louder
# than others (a bass part with few notes vs. a busy soprano). We set every stem to the same
# loudness (LUFS = how loud it sounds to a human ear) so the user does not have to fix volumes.
# The peak ceiling stops the loudest instant from distorting after MP3 compression.
# Loudness baked into every stem (the app player volume is capped at 1.0). Values and sources:
# docs/decisions/audio-loudness-2026-11.md.
STEM_TARGET_LUFS = -20.0
STEM_TRUE_PEAK_CEILING_DBTP = -2.0   # headroom for MP3 re-encode overshoot
MIN_MEASURABLE_LUFS = -70.0          # at or below this the stem is silent: no gain

# ── MIDI constants ────────────────────────────────────────────────────────────
PPQ          = 480          # pulses per quarter note (ticks per beat)
DEFAULT_BPM  = 90           # default tempo if not detected
# Client-facing review items are capped; the full list goes to the job record (backend-lead review
# 2026-09-29: Stage 4 bar flags are unbounded, strips are at most 20 pages x 16 staves).
REVIEW_ITEMS_CAP = 200
# DEFENSE: client review - the pipeline raises many internal warnings, but a user can only act on
# one thing: "this voice could not be read, retake the photo". So only those codes go to the app;
# everything else stays in the job record for us to inspect.
# Reasons that apply to the whole job, not to one strip; reported once in `reasons`, never as items.
# The user can only act on a missing or unreadable voice (retake the page); every other flag stays in
# the job record and logs. No Stage 4 "voice dropped" code exists yet; the name is reserved.
CLIENT_REVIEW_CODES: frozenset[str] = frozenset({"voice_unreadable", "voice_dropped"})
JOB_LEVEL_REVIEW_CODES = frozenset({stage3_clefkey.CLEF_KEY_UNVALIDATED_FLAG, CLEF_KEY_DISABLED_FLAG})
MIDI_CHANNEL = 0            # piano channel
MIDI_VOLUME  = 100          # note velocity (0–127)
PIANO_PROGRAM = 0           # General MIDI program 0 = Acoustic Grand Piano
SUSTAIN_PEDAL_CC = 64       # controller used only as an end-of-piece length pin

# DEFENSE: ppq check - a "tick" is a tiny time unit. Stage 4 counts time in ticks and Stage 5
# converts ticks to beats by dividing by PPQ. If the two stages used different tick sizes, every
# note would land at the wrong time, so we crash loudly at import instead of playing wrong music.
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
    soundfont_path:  str  = "models/piano.sf2",
    render_audio:    bool = True,
) -> dict:
    """
    Converts four SATB voice event sequences into four MP3 files.

    Args:
        satb_sequences:  Output of Stage 4 reconstruct_satb().
                         {voice: [event_dict, ...]}
        output_dir:      Directory where MP3 files will be saved.
        bpm:             Playback tempo in beats per minute.
        soundfont_path:  Path to a .sf2 piano soundfont for rendering.
        render_audio:    False writes the per-voice .mid only (the backend ships MIDI, not MP3).

    Returns:
        {voice: mp3_path} dict of output file paths.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n[Stage 5] Synthesizing SATB audio at {bpm} BPM...")

    output_files = {}
    total_ticks = _piece_end_tick(satb_sequences)

    for voice in VOICES:
        # DEFENSE: silent track - if one voice could not be read, we still make its file (silence)
        # so the app always has four tracks of equal length that play in sync.
        # An empty (unreadable) voice still gets a silent track padded to the common length, so the
        # app always has four tracks that stay in sync; Stage 4 reports it via failed_voices.
        events = satb_sequences.get(voice, [])
        if not events:
            msg = f"[Stage 5] No events for {voice}: writing a silent track for this voice."
            print(f"  {msg.replace('[Stage 5]', '[Stage 5] WARNING:', 1)}", file=sys.stderr)
            warnings.warn(msg, RuntimeWarning, stacklevel=2)

        # ── Build single-track MIDI per voice ─────────────────────────────
        midi = build_voice_midi(events, bpm, total_ticks)

        # ── Save MIDI file ─────────────────────────────────────────────────
        midi_path = output_path / f"{voice.lower()}.mid"
        with open(midi_path, "wb") as f:
            midi.writeFile(f)
        print(f"  [Stage 5] {voice}: MIDI saved -> {midi_path}")

        if not render_audio:
            output_files[voice] = str(midi_path)
            continue

        # -- Render MIDI -> WAV -> MP3 --
        mp3_path = output_path / f"{voice.lower()}.mp3"
        wav_path = output_path / f"{voice.lower()}.wav"

        success = _render_to_mp3(midi_path, wav_path, mp3_path, soundfont_path)

        if success:
            output_files[voice] = str(mp3_path)
            print(f"  [Stage 5] {voice}: MP3 saved -> {mp3_path}")
        else:
            # DEFENSE: midi fallback - MP3 needs extra programs (fluidsynth, ffmpeg, a soundfont)
            # that may be missing on a machine. The MIDI file is already written and is the real
            # musical result, so we return it instead of failing the whole conversion.
            # Fall back to returning the MIDI if rendering failed
            output_files[voice] = str(midi_path)
            print(f"  [Stage 5] {voice}: MP3 rendering failed, "
                  f"returning MIDI -> {midi_path}")

    _report(output_files)
    return output_files


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
    # DEFENSE: collapse notes - if the same pitch is listed twice at the same start time (a
    # duplicate from an upstream stage), playing both would sound twice as loud. We keep one,
    # the longest.
    longest: dict = {}
    for e in events:
        if (e["type"] != "note" or e["pitch"] is None
                or e["duration_ticks"] <= 0):
            continue
        key = (e["tick_onset"], e["pitch"])
        longest[key] = max(longest.get(key, 0), e["duration_ticks"])
    # DEFENSE: clip overlap - if the same note starts again before the first one ended, MIDI can
    # mix up which "note off" belongs to which "note on" and a note hangs forever. We cut the
    # first note short at the moment the next one starts; a singer sings one note at a time anyway.
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
    # DEFENSE: pad same length - a MIDI file ends at its last event, so a voice that stops early
    # would be shorter and the four tracks would fall out of sync in the app. The last event
    # below is a do-nothing pedal message placed at the common end time, which stretches every
    # voice to the same length without adding any sound.
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

_LUFS_RE = re.compile(r"^\s*I:\s*(-?[\d.]+|-inf)\s+LUFS", re.MULTILINE)
_PEAK_RE = re.compile(r"^\s*Peak:\s*(-?[\d.]+|-inf)\s+dBFS", re.MULTILINE)


def _measure_loudness(wav_path: Path) -> Optional[tuple[float, float]]:
    """Measures integrated LUFS and true peak (dBTP) with ffmpeg's ebur128 filter.

    ffmpeg is already required for MP3 export, so this avoids a new dependency.

    Args:
        wav_path: WAV file to measure.

    Returns:
        (integrated LUFS, true peak dBTP), or None if ffmpeg failed or its output was unparseable.
    """
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostats", "-i", str(wav_path), "-af", "ebur128=peak=true", "-f", "null", "-"],
            check=True, capture_output=True, text=True,
        )
        # Parse only the final Summary block; earlier lines are per-frame values.
        summary = proc.stderr.rsplit("Summary:", 1)[1]
        lufs = _LUFS_RE.search(summary)
        peak = _PEAK_RE.search(summary)
        if lufs is None or peak is None:
            raise ValueError("no I:/Peak: in ebur128 summary")
        return float(lufs.group(1)), float(peak.group(1))
    except (OSError, subprocess.CalledProcessError, IndexError, ValueError) as e:
        print(f"  [Stage 5] WARNING: loudness measurement failed for {wav_path}: {e}")
        return None


def _loudness_gain_db(lufs: float, true_peak_db: float) -> float:
    """Gain that brings a stem to STEM_TARGET_LUFS without exceeding the true-peak ceiling.

    A peaky stem is left quieter than target rather than clipped after MP3 encoding.
    """
    # DEFENSE: peak ceiling - we want the target loudness, but never so much gain that the
    # loudest spike would crackle. The smaller of the two gains wins: safe beats loud.
    gain = STEM_TARGET_LUFS - lufs
    return min(gain, STEM_TRUE_PEAK_CEILING_DBTP - true_peak_db)


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

        # DEFENSE: fluidsynth order - FluidSynth silently ignores settings written after the
        # soundfont and MIDI file, and then no WAV appears. So settings go first; we also check
        # afterwards that the WAV really exists.
        # MIDI → WAV via FluidSynth. Options must come before the soundfont and MIDI file:
        # FluidSynth 2.x ignores options placed after them (midi2audio's order), which left no WAV.
        subprocess.run(
            [fluidsynth, "-ni", "-F", str(wav_path), "-r", str(RENDER_SAMPLE_RATE),
             *FLUIDSYNTH_DRY_SETTINGS, str(sf_path), str(midi_path)],
            check=True, capture_output=True, text=True,
        )
        if not wav_path.exists():
            print(f"  [Stage 5] Rendering error: fluidsynth wrote no WAV at {wav_path}")
            return False

        # DEFENSE: normalise loudness - measure how loud the WAV is, then raise or lower it to the
        # shared target. Silent files (nothing measurable) are left alone: gain cannot fix silence.
        # WAV → MP3 via pydub + ffmpeg
        audio = AudioSegment.from_wav(str(wav_path))
        loudness = _measure_loudness(wav_path)
        if loudness is not None and loudness[0] > MIN_MEASURABLE_LUFS:
            audio = audio.apply_gain(_loudness_gain_db(*loudness))
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


# ── Review summary (exposed by the result API, PIYA-103 AC6) ──────────────────

def build_review(stage3_events: dict, stage4_flags: list) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Maps Stage 3 strip flags and Stage 4 reconstruction flags onto the API's fixed review shape.

    The mapping is explicit so a change in Stage 3/4's internal flag dicts can't change the public
    contract. ``reviewNeeded: False`` only means nothing was flagged, not that the transcription is right.
    A strip's codes become items only when that strip's own flags carry ``review_needed``: informational
    codes (e.g. ``plain_treble_on_low_voice_assumed_8vb``) must not make a clean score need review once
    the classifier passes its gate. Stage 4 bar items come first so the cap never hides them behind
    per-strip items (a long score has up to 320 strips).

    Args:
        stage3_events: {voice: [event, ...]} from Stage 3 (events carry ``clef_key_flags`` and, with
            ClefKeyNet, ``clef_key_strip_flags``; ``mid_change_flags`` from the system-level mid-strip
            key/meter check; ``header_flags`` when the Stage 3 header filter kept a
            quorum meter change on a continuation system).
            ``code`` is an open, additive set (clients treat unknown codes as generic review items); for
            triage, current per-strip codes come from stage3_clefkey and ``header_meter_change_kept``
            (docs/decisions/piya-106-ser-15-plan.md §3).
        stage4_flags: ``reconstruct_satb_with_report``'s ``flags``; only those with ``review_needed`` count.

    Only CLIENT_REVIEW_CODES reach the client object: the user can only act on a missing or unreadable
    voice, so meter, clef/key and tenor-range flags would be noise.

    Returns:
        (review, full_items): ``review`` is the client object with at most REVIEW_ITEMS_CAP voice items;
        ``full_items`` is the uncapped list of every flag for the job record and logs.
    """
    # DEFENSE: review shape - the app depends on a fixed JSON shape. We copy fields one by one
    # (instead of passing internal dicts through) so changing Stage 3/4 internals cannot
    # silently break the app. "reviewNeeded: False" means nothing was flagged, not "all correct".
    items: list[dict[str, Any]] = []
    for f in stage4_flags:
        if f.get("review_needed"):
            item = {"code": f["kind"], "voice": f["voice"].lower() if f.get("voice") else None,
                    "pageIndex": f.get("page_index"), "systemIndex": f.get("sys_idx"),
                    "bar": f.get("bar")}
            if f.get("pages"):
                item["pages"] = f["pages"]  # 1-based, for the voice-unreadable prompt
            items.append(item)
    seen_strips: set[tuple] = set()
    for voice, events in stage3_events.items():
        for e in events:
            for field in ("clef_key_strip_flags", "header_flags", "mid_change_flags"):
                strip_flags = set(e.get(field, []))
                if "review_needed" not in strip_flags:
                    continue
                for code in sorted(strip_flags - {"review_needed"} - JOB_LEVEL_REVIEW_CODES):
                    key = (voice, e["page_index"], e["sys_idx"], code)
                    if key not in seen_strips:
                        seen_strips.add(key)
                        items.append({"code": code, "voice": voice.lower(), "pageIndex": e["page_index"],
                                      "systemIndex": e["sys_idx"], "bar": None})
    client_items = [i for i in items if i["code"] in CLIENT_REVIEW_CODES]
    reasons = sorted({i["code"] for i in client_items})
    review = {"reviewNeeded": bool(reasons), "reasons": reasons, "items": client_items[:REVIEW_ITEMS_CAP],
              "truncated": len(client_items) > REVIEW_ITEMS_CAP}
    return review, items


# ── Full pipeline helper ──────────────────────────────────────────────────────

def run_full_pipeline(
    input_dir:      str = "data/raw",
    prep_dir:       str = "data/preprocessed",
    strips_dir:     str = "data/strips",
    output_dir:     str = "output/audio",
    crnn_weights:   str = "models/symbol_transcriber_crnn_seed1.pt",
    yolo_weights:   str = "models/staff_detector_yolov8.pt",
    soundfont_path: str = "models/piano.sf2",
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
    crnn_weights:   str = "models/symbol_transcriber_crnn_seed1.pt",
    yolo_weights:   str = "models/staff_detector_yolov8.pt",
    soundfont_path: str = "models/piano.sf2",
    bpm:            int = DEFAULT_BPM,
    img_height:     int = 64,
    clef_key_weights: Optional[str] = str(stage3_clefkey.DEFAULT_CLEF_KEY_CHECKPOINT),
) -> dict[str, Any]:
    """Runs Stages 1-5 and returns the audio plus what the result API and job record need.

    Returns:
        {"audio": {voice: path},
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

    # DEFENSE: pipeline entry - this is the one function that chains everything: photo ->
    # Stages 1-3 (find staves, read symbols) -> Stage 4 (put voices on one timeline) ->
    # Stage 5 (make audio). It also builds the review report and a record of which
    # clef/key checkpoint was used.
    # Stages 1-3
    voice_events = run_stages_1_to_3(input_dir, prep_dir, strips_dir, yolo_weights, crnn_weights,
                                     clef_key_weights, img_height=img_height)

    # Stage 4
    satb, recon_report = reconstruct_satb_with_report(voice_events)
    review, review_detail = build_review(voice_events, recon_report["flags"])
    provenance = {
        "clefKeyEnabled": clef_key_weights is not None,
        "clefKeyCheckpointSha256": (stage3_clefkey.file_sha256(Path(clef_key_weights))
                                    if clef_key_weights is not None else None),
        "clefKeyGatePassed": stage3_clefkey.CLEF_KEY_GATE_PASSED,
    }

    # Stage 5
    mp3_files = synthesize_satb(
        satb,
        output_dir=output_dir,
        bpm=bpm,
        soundfont_path=soundfont_path,
    )

    print("=" * 60)
    print("PiyaNota complete.")
    for voice, path in mp3_files.items():
        print(f"  {voice}: {path}")
    print("=" * 60)

    return {"audio": mp3_files, "review": review, "review_detail": review_detail, "provenance": provenance}


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
    parser.add_argument("--weights",   default="models/symbol_transcriber_crnn_seed1.pt")
    parser.add_argument("--yolo",      default="models/staff_detector_yolov8.pt")
    parser.add_argument("--soundfont", default="models/piano.sf2",
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
