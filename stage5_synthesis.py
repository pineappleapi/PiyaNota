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
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from midiutil import MIDIFile

if TYPE_CHECKING:
    from run_manifest import RunManifest

# ── MIDI constants ────────────────────────────────────────────────────────────
PPQ          = 480          # pulses per quarter note (ticks per beat)
DEFAULT_BPM  = 90           # default tempo if not detected
MIDI_CHANNEL = 0            # piano channel
MIDI_VOLUME  = 100          # note velocity (0–127)
PIANO_PROGRAM = 0           # General MIDI program 0 = Acoustic Grand Piano

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

    for voice in VOICES:
        events = satb_sequences.get(voice, [])
        if not events:
            print(f"  [Stage 5] WARNING: No events for {voice}, skipping.")
            continue

        # ── Build single-track MIDI per voice ─────────────────────────────
        midi     = MIDIFile(1, ticks_per_quarternote=PPQ)
        track    = 0
        midi.addTempo(track, 0, bpm)
        midi.addProgramChange(track, MIDI_CHANNEL, 0, PIANO_PROGRAM)

        current_tick = 0

        # Group events by tick_onset to handle chords correctly
        from collections import defaultdict
        tick_map = defaultdict(list)
        for ev in events:
            tick_map[ev["tick_onset"]].append(ev)

        for tick_onset in sorted(tick_map.keys()):
            tick_events = tick_map[tick_onset]

            for ev in tick_events:
                if ev["type"] == "rest" or ev["pitch"] is None:
                    # Rests just advance time — no MIDI event needed
                    continue

                pitch    = ev["pitch"]
                duration = ev["duration_ticks"]

                if duration <= 0:
                    continue

                # midiutil uses beats, not ticks — convert
                onset_beats    = tick_onset / PPQ
                duration_beats = duration   / PPQ

                midi.addNote(
                    track    = track,
                    channel  = MIDI_CHANNEL,
                    pitch    = pitch,
                    time     = onset_beats,
                    duration = duration_beats,
                    volume   = MIDI_VOLUME,
                )

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
    manifest:       Optional["RunManifest"] = None,
) -> dict:
    """
    Runs the complete PiyaNota pipeline from raw images to MP3 files.
    Stages 1 → 2 → 3 → 4 → 5.

    Args:
        manifest: Optional run-provenance recorder. When given, each stage is
          timed and the checkpoints/soundfont/inputs/outputs are hashed into it;
          the caller owns writing it (use it as a context manager).
    """
    from stage1_preprocessing  import preprocess_batch
    from stage2_detection      import detect_staff_regions
    from stage3_transcription  import transcribe_voice_sequences
    from stage4_reconstruction import reconstruct_satb

    print("=" * 60)
    print("PiyaNota — Full Pipeline")
    print("=" * 60)

    # Without a manifest, stage timing is a no-op so the flow below stays single-path.
    stage = manifest.stage if manifest is not None else (lambda _name: nullcontext())

    # Stage 1
    with stage("stage1_preprocessing"):
        pages = preprocess_batch(input_dir, prep_dir, save_debug=False,
                                 manifest=manifest)

    # Stage 2
    with stage("stage2_detection"):
        voice_strips = detect_staff_regions(
            pages,
            model_weights=yolo_weights,
            output_dir=strips_dir,
            manifest=manifest,
        )

    # Stage 3
    with stage("stage3_transcription"):
        voice_events = transcribe_voice_sequences(
            voice_strips,
            model_weights=crnn_weights,
            img_height=img_height,
            manifest=manifest,
        )

    # Stage 4
    with stage("stage4_reconstruction"):
        satb = reconstruct_satb(voice_events)

    # Stage 5
    if manifest is not None:
        manifest.add_stage_info("stage4_reconstruction",
                                events_per_voice={v: len(e) for v, e in satb.items()})
        manifest.add_asset("soundfont", soundfont_path)
        manifest.set_params(bpm=bpm)
    with stage("stage5_synthesis"):
        mp3_files = synthesize_satb(
            satb,
            output_dir=output_dir,
            bpm=bpm,
            soundfont_path=soundfont_path,
        )
    if manifest is not None:
        # May be .mid rather than .mp3 when audio rendering deps are missing.
        for voice, path in mp3_files.items():
            manifest.add_output(f"audio_{voice.lower()}", path)

    print("=" * 60)
    print("PiyaNota complete.")
    for voice, path in mp3_files.items():
        print(f"  {voice}: {path}")
    print("=" * 60)

    return mp3_files


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from run_manifest import DEFAULT_RUNS_ROOT, RunManifest

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
    parser.add_argument("--runs-dir",  default=DEFAULT_RUNS_ROOT,
                        help="Where per-run manifest.json provenance files are written")
    args = parser.parse_args()

    with RunManifest(runs_root=args.runs_dir, args=vars(args)) as manifest:
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
            manifest       = manifest,
        )

    print(f"\nStage 5 complete. {len(mp3s)} audio file(s) ready.")
