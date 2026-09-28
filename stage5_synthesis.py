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

from stage3_transcription import CLEF_KEY_DISABLED_FLAG
from stage4_reconstruction import TICKS_PER_QUARTER

# FluidSynth output sample rate (midi2audio's former default).
RENDER_SAMPLE_RATE = 44100

# ── MIDI constants ────────────────────────────────────────────────────────────
PPQ          = 480          # pulses per quarter note (ticks per beat)
DEFAULT_BPM  = 90           # default tempo if not detected
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
) -> dict:
    """
    Converts four SATB voice event sequences into four MP3 files.

    Args:
        satb_sequences:  Output of Stage 4 reconstruct_satb().
                         {voice: [event_dict, ...]}
        output_dir:      Directory where MP3 files will be saved.
        bpm:             Playback tempo in beats per minute.
        soundfont_path:  Path to a .sf2 piano soundfont for rendering.

    Returns:
        {voice: mp3_path} dict of output file paths.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n[Stage 5] Synthesizing SATB audio at {bpm} BPM...")

    output_files = {}
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
            warnings.warn(msg, RuntimeWarning, stacklevel=2)
            continue

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
        else:
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
            ClefKeyNet, ``clef_key_strip_flags``).
        stage4_flags: ``reconstruct_satb_with_report``'s ``flags``; only those with ``review_needed`` count.

    Returns:
        (review, full_items): ``review`` is the client object with at most REVIEW_ITEMS_CAP items;
        ``full_items`` is the uncapped list for the job record.
    """
    job_reasons: set[str] = set()
    items: list[dict[str, Any]] = []
    for f in stage4_flags:
        if f.get("review_needed"):
            items.append({"code": f["kind"], "voice": f["voice"].lower() if f.get("voice") else None,
                          "pageIndex": f.get("page_index"), "systemIndex": f.get("sys_idx"),
                          "bar": f.get("bar")})
    seen_strips: set[tuple] = set()
    for voice, events in stage3_events.items():
        for e in events:
            job_reasons |= set(e.get("clef_key_flags", [])) & JOB_LEVEL_REVIEW_CODES
            strip_flags = set(e.get("clef_key_strip_flags", []))
            if "review_needed" not in strip_flags:
                continue
            for code in sorted(strip_flags - {"review_needed"} - JOB_LEVEL_REVIEW_CODES):
                key = (voice, e["page_index"], e["sys_idx"], code)
                if key not in seen_strips:
                    seen_strips.add(key)
                    items.append({"code": code, "voice": voice.lower(), "pageIndex": e["page_index"],
                                  "systemIndex": e["sys_idx"], "bar": None})
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
