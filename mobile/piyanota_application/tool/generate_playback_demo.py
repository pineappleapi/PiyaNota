"""Generates the offline demo data for Score Playback (PIYA-208).

Writes into ``assets/demo/``:

- ``score_page_1.png``: a copy of ``data/preprocessed/page_004_preprocessed.png``
  (1300 x 1575, kept at its original size since it is only ~31 KB). It is
  a real preprocessed open-score SATB page: two systems of four staves,
  printed bars 29-36.
- ``soprano.mp3`` / ``alto.mp3`` / ``tenor.mp3`` / ``bass.mp3``: a simple
  I-IV-V-I-vi-IV-V-I progression in F major at 90 bpm, one line per voice,
  all exactly the same length so the four players stay in step.
- ``timing.json``: PIYA-117/118-shaped events whose ``timestampMs`` match
  the synthesized audio and whose ``x``/``y``/``bar`` sit on the page's real
  barlines and staves.

It is demo data. The audio does NOT match the printed notes: only the bar
and staff geometry is real. The demo renumbers the page's printed bars 29-36
as bars 1-8, as if it were a score of its own.

Coordinates are pixels in the copied image, i.e. the image the fake
PIYA-103 returns, which is how PIYA-118 AC2 defines them. The geometry was
measured from the image with PIL (staff-line rows: dark pixels across more
than 60% of the width; barlines: columns dark through a whole staff):

- system 1 staves (top line y): 70, 240, 410, 580; system 2: 940, 1110,
  1280, 1450. Lines are 10 px apart, so staff centres are top + 20.
- system 1 barlines x: 401, 678, 954; system 2: 415, 674, 1027. Every staff
  ends at x = 1219.
- the first note after clef/key/time signature starts at x ~ 215 (system
  1) and ~ 195 (system 2).

Run from the app root with the project venv (needs Pillow and numpy, and
ffmpeg on PATH for MP3):

    D:/PiyaNota/.venv/Scripts/python.exe tool/generate_playback_demo.py \
        --page D:/PiyaNota/data/preprocessed/page_004_preprocessed.png
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

SAMPLE_RATE = 22050
BPM = 90
BEATS_PER_BAR = 4
PPQ = 480  # Matches stage5_synthesis.PPQ.
SECONDS_PER_BEAT = 60.0 / BPM
TAIL_SECONDS = 1.5
MP3_BITRATE = "48k"
PEAK_AMPLITUDE = 0.35
ATTACK_SECONDS = 0.005
RELEASE_SECONDS = 0.04
HARMONIC_COUNT = 6

EXPECTED_PAGE_SIZE = (1300, 1575)
STAFF_LINE_GAP = 10
HALF_STEP_PX = STAFF_LINE_GAP / 2
STAFF_HEIGHT = 4 * STAFF_LINE_GAP
# Band padding beyond the outer staves, about two ledger lines.
SYSTEM_PAD = 20
# Keeps an onset off the barline it follows/precedes.
BAR_INNER_PAD = 24

SYSTEM_STAFF_TOPS = ([70, 240, 410, 580], [940, 1110, 1280, 1450])
# (content start, barline, barline, barline, staff end) per system.
SYSTEM_BAR_EDGES = ([215, 401, 678, 954, 1219], [195, 415, 674, 1027, 1219])
BARS_PER_SYSTEM = 4

VOICES = ("Soprano", "Alto", "Tenor", "Bass")

# Notes as (pitch, beats) per bar.
SCORE: dict[str, list[list[tuple[str, int]]]] = {
    "Soprano": [
        [("F4", 1), ("G4", 1), ("A4", 1), ("C5", 1)],
        [("Bb4", 1), ("A4", 1), ("G4", 1), ("F4", 1)],
        [("E4", 1), ("G4", 1), ("C5", 1), ("Bb4", 1)],
        [("A4", 2), ("C5", 2)],
        [("D5", 1), ("C5", 1), ("A4", 1), ("F4", 1)],
        [("D5", 1), ("Bb4", 1), ("F4", 1), ("D5", 1)],
        [("C5", 1), ("Bb4", 1), ("G4", 1), ("E4", 1)],
        [("F4", 4)],
    ],
    "Alto": [
        [("C4", 2), ("C4", 2)],
        [("D4", 2), ("D4", 2)],
        [("E4", 2), ("E4", 2)],
        [("F4", 2), ("C4", 2)],
        [("F4", 2), ("D4", 2)],
        [("F4", 2), ("D4", 2)],
        [("E4", 2), ("C4", 2)],
        [("C4", 4)],
    ],
    "Tenor": [
        [("A3", 2), ("A3", 2)],
        [("F3", 2), ("Bb3", 2)],
        [("G3", 2), ("G3", 2)],
        [("A3", 2), ("A3", 2)],
        [("A3", 2), ("A3", 2)],
        [("Bb3", 2), ("F3", 2)],
        [("G3", 2), ("Bb3", 2)],
        [("A3", 4)],
    ],
    "Bass": [
        [("F2", 4)],
        [("Bb2", 4)],
        [("C3", 4)],
        [("F2", 4)],
        [("D3", 4)],
        [("Bb2", 4)],
        [("C3", 4)],
        [("F2", 4)],
    ],
}

_LETTER_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_LETTER_STEP = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
# Diatonic step of each clef's middle line (B4 treble, D3 bass). Tenor
# reads treble 8vb, so its middle line sounds B3.
_MIDDLE_LINE_STEP = {
    "Soprano": 4 * 7 + 6,
    "Alto": 4 * 7 + 6,
    "Tenor": 3 * 7 + 6,
    "Bass": 3 * 7 + 1,
}


@dataclass(frozen=True)
class Note:
    voice: str
    pitch: str
    bar: int  # 1-based
    beat: int  # 0-based within the bar
    beats: int


def midi_number(pitch: str) -> int:
    letter, rest = pitch[0], pitch[1:]
    accidental = 0
    if rest.startswith("b"):
        accidental, rest = -1, rest[1:]
    elif rest.startswith("#"):
        accidental, rest = 1, rest[1:]
    return 12 * (int(rest) + 1) + _LETTER_SEMITONE[letter] + accidental


def diatonic_step(pitch: str) -> int:
    octave = int(pitch.lstrip("ABCDEFG").lstrip("b#"))
    return octave * 7 + _LETTER_STEP[pitch[0]]


def notes_for(voice: str) -> list[Note]:
    notes: list[Note] = []
    for bar_index, bar in enumerate(SCORE[voice]):
        beat = 0
        for pitch, beats in bar:
            notes.append(Note(voice, pitch, bar_index + 1, beat, beats))
            beat += beats
        if beat != BEATS_PER_BAR:
            raise ValueError(f"{voice} bar {bar_index + 1} has {beat} beats")
    return notes


def onset_seconds(note: Note) -> float:
    return ((note.bar - 1) * BEATS_PER_BAR + note.beat) * SECONDS_PER_BEAT


def synthesize(notes: list[Note], total_seconds: float) -> np.ndarray:
    """Additive, decaying harmonics: piano-ish enough for a demo."""
    out = np.zeros(int(total_seconds * SAMPLE_RATE), dtype=np.float64)
    for note in notes:
        start = int(onset_seconds(note) * SAMPLE_RATE)
        length = int(note.beats * SECONDS_PER_BEAT * SAMPLE_RATE)
        t = np.arange(length) / SAMPLE_RATE
        freq = 440.0 * 2 ** ((midi_number(note.pitch) - 69) / 12)
        tone = np.zeros(length)
        for n in range(1, HARMONIC_COUNT + 1):
            tone += (
                np.sin(2 * np.pi * freq * n * t)
                * np.exp(-t * (1.2 + 0.7 * n))
                / n**1.3
            )
        envelope = np.ones(length)
        attack = int(ATTACK_SECONDS * SAMPLE_RATE)
        release = int(RELEASE_SECONDS * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-release:] *= np.linspace(1, 0, release)
        out[start : start + length] += tone * envelope
    peak = np.max(np.abs(out))
    return out / peak * PEAK_AMPLITUDE if peak > 0 else out


def write_audio(samples: np.ndarray, target: Path) -> Path:
    pcm = (samples * 32767).astype("<i2").tobytes()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        wav_target = target.with_suffix(".wav")
        _write_wav(pcm, wav_target)
        return wav_target
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "voice.wav"
        _write_wav(pcm, wav)
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1",
             "-b:a", MP3_BITRATE, str(target)],
            check=True,
        )
    return target


def _write_wav(pcm: bytes, target: Path) -> None:
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm)


def event_x(note: Note) -> int:
    system = (note.bar - 1) // BARS_PER_SYSTEM
    slot = (note.bar - 1) % BARS_PER_SYSTEM
    edges = SYSTEM_BAR_EDGES[system]
    left = edges[slot] + BAR_INNER_PAD
    right = edges[slot + 1] - BAR_INNER_PAD
    return round(left + (right - left) * note.beat / BEATS_PER_BAR)


def event_y(note: Note) -> int:
    system = (note.bar - 1) // BARS_PER_SYSTEM
    staff = VOICES.index(note.voice)
    centre = SYSTEM_STAFF_TOPS[system][staff] + STAFF_HEIGHT / 2
    offset = (diatonic_step(note.pitch) - _MIDDLE_LINE_STEP[note.voice])
    return round(centre - offset * HALF_STEP_PX)


def timing_events() -> list[dict[str, object]]:
    notes = sorted(
        (note for voice in VOICES for note in notes_for(voice)),
        key=lambda n: (onset_seconds(n), VOICES.index(n.voice)),
    )
    events: list[dict[str, object]] = []
    for event_id, note in enumerate(notes, start=1):
        system = (note.bar - 1) // BARS_PER_SYSTEM
        tops = SYSTEM_STAFF_TOPS[system]
        events.append({
            "timestampMs": round(onset_seconds(note) * 1000),
            "pageIndex": 0,
            "voice": note.voice,
            "tick": ((note.bar - 1) * BEATS_PER_BAR + note.beat) * PPQ,
            "eventId": event_id,
            "x": event_x(note),
            "y": event_y(note),
            "bar": note.bar,
            # Optional fields backend-lead may add (2026-10-09).
            "systemIndex": system,
            "systemTopY": tops[0] - SYSTEM_PAD,
            "systemBottomY": tops[-1] + STAFF_HEIGHT + SYSTEM_PAD,
        })
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--page", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path,
        default=Path(__file__).resolve().parent.parent / "assets" / "demo",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with Image.open(args.page) as page:
        if page.size != EXPECTED_PAGE_SIZE:
            raise ValueError(
                f"{args.page} is {page.size}; the geometry above was measured "
                f"on a {EXPECTED_PAGE_SIZE} page"
            )
        page.save(args.out / "score_page_1.png", optimize=True)

    bars = len(SCORE["Soprano"])
    total = bars * BEATS_PER_BAR * SECONDS_PER_BEAT + TAIL_SECONDS
    for voice in VOICES:
        written = write_audio(
            synthesize(notes_for(voice), total),
            args.out / f"{voice.lower()}.mp3",
        )
        print(f"wrote {written} ({written.stat().st_size} bytes)")

    timing = args.out / "timing.json"
    timing.write_text(json.dumps(timing_events(), indent=1) + "\n")
    print(f"wrote {timing}; audio length {total:.2f} s")


if __name__ == "__main__":
    main()
