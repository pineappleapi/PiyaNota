"""Stem loudness normalization in Stage 5 (B10). Synthetic sine WAVs; no soundfont or fluidsynth needed."""

import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage5_synthesis as s5  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")


def _sine_wav(path: Path, amplitude: float) -> None:
    t = np.arange(int(2.0 * s5.RENDER_SAMPLE_RATE)) / s5.RENDER_SAMPLE_RATE
    data = (amplitude * 32767 * np.sin(2 * np.pi * 440 * t)).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(s5.RENDER_SAMPLE_RATE)
        w.writeframes(data.tobytes())


def test_gain_quiet_stem_goes_up_to_target() -> None:
    assert s5._loudness_gain_db(-30.0, -20.0) == pytest.approx(10.0)


def test_gain_limited_by_peak_ceiling() -> None:
    # Target wants +4 dB, but the peak is already at -4 dBTP: only +2 dB fits under -2.
    assert s5._loudness_gain_db(-24.0, -4.0) == pytest.approx(2.0)


def test_gain_loud_stem_goes_down() -> None:
    assert s5._loudness_gain_db(-10.0, -1.0) == pytest.approx(-10.0)


@needs_ffmpeg
def test_gain_step_lands_on_target(tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    _sine_wav(wav, 0.02)
    lufs, peak = s5._measure_loudness(wav)  # type: ignore[misc]
    gain = s5._loudness_gain_db(lufs, peak)
    out = tmp_path / "b.wav"
    subprocess.run(["ffmpeg", "-y", "-i", str(wav), "-af", f"volume={gain}dB", str(out)],
                   check=True, capture_output=True)
    new_lufs, _ = s5._measure_loudness(out)  # type: ignore[misc]
    assert new_lufs == pytest.approx(s5.STEM_TARGET_LUFS, abs=0.5)


@needs_ffmpeg
def test_silent_wav_is_not_amplified(tmp_path: Path) -> None:
    wav = tmp_path / "s.wav"
    _sine_wav(wav, 0.0)
    m = s5._measure_loudness(wav)
    assert m is None or m[0] <= s5.MIN_MEASURABLE_LUFS


def test_measure_failure_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise OSError("no ffmpeg")
    monkeypatch.setattr(s5.subprocess, "run", boom)
    assert s5._measure_loudness(tmp_path / "x.wav") is None
