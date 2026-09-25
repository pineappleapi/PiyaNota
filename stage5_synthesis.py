"""
PiyaNota - Stage 5: MIDI-Based Piano Audio Synthesis
Converts reconstructed SATB voice sequences into four separate MP3 files,
one per voice (Soprano, Alto, Tenor, Bass).

Dependencies:
    pip install midiutil pydub
    Also requires ffmpeg installed on the system for MP3 export.
    For piano soundfont rendering: pip install midi2audio
    Download a piano soundfont (.sf2) e.g. GeneralUser GS or FluidR3.
"""

import os
import sys
import warnings
from pathlib import Path
from midiutil import MIDIFile

from stage4_reconstruction import TICKS_PER_QUARTER

# ── MIDI constants ────────────────────────────────────────────────────────────
PPQ          = 480          # pulses per quarter note (ticks per beat)
DEFAULT_BPM  = 90           # default tempo if not detected
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
        - pydub installed (pip install pydub)
        - ffmpeg installed for MP3 export
        - A valid .sf2 soundfont file

    Returns True on success, False on failure.
    """
    try:
        from midi2audio import FluidSynth
        from pydub import AudioSegment

        sf_path = Path(soundfont_path)
        if not sf_path.exists():
            print(f"  [Stage 5] WARNING: Soundfont not found at {sf_path}. "
                  f"Download a piano .sf2 and set --soundfont.")
            return False

        # MIDI → WAV via FluidSynth
        fs = FluidSynth(sound_font=str(sf_path))
        fs.midi_to_audio(str(midi_path), str(wav_path))

        # WAV → MP3 via pydub + ffmpeg
        audio = AudioSegment.from_wav(str(wav_path))
        audio.export(str(mp3_path), format="mp3", bitrate="192k")

        # Clean up WAV
        wav_path.unlink(missing_ok=True)

        return True

    except ImportError as e:
        print(f"  [Stage 5] Missing dependency: {e}. "
              f"Install with: pip install midi2audio pydub")
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
) -> dict:
    """
    Runs the complete PiyaNota pipeline from raw images to MP3 files.
    Stages 1 → 2 → 3 → 4 → 5.
    """
    from stage1_preprocessing  import preprocess_batch
    from stage2_detection      import detect_staff_regions
    from stage3_transcription  import transcribe_voice_sequences
    from stage4_reconstruction import reconstruct_satb

    print("=" * 60)
    print("PiyaNota — Full Pipeline")
    print("=" * 60)

    # Stage 1
    pages = preprocess_batch(input_dir, prep_dir, save_debug=False)

    # Stage 2
    voice_strips = detect_staff_regions(
        pages,
        model_weights=yolo_weights,
        output_dir=strips_dir,
    )

    # Stage 3
    voice_events = transcribe_voice_sequences(
        voice_strips,
        model_weights=crnn_weights,
        img_height=img_height,
    )

    # Stage 4
    satb = reconstruct_satb(voice_events)

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

    return mp3_files


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
    )

    print(f"\nStage 5 complete. {len(mp3s)} audio file(s) ready.")
