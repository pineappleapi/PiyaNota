"""Pipeline adapter: stage order, voice mapping, failed voices and config errors (fake stages), plus one real run."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from backend.worker import pipeline
from backend.worker.pipeline import CleanPage, PipelineConfig, PipelineError, Stages, run_pipeline

EVENT = {"type": "note", "pitch": 60}
MOONRIVER = Path("D:/PiyaNota/data/chords_dataset/Moonriver/Moonriver/p01.JPG")


def _jpeg() -> bytes:
    buf = BytesIO()
    Image.new("L", (8, 8), 255).save(buf, "JPEG")
    return buf.getvalue()


def _config(tmp_path: Path) -> PipelineConfig:
    files = [tmp_path / n for n in ("y.pt", "c.pt", "s.sf2")]
    for f in files:
        f.write_bytes(b"x")
    return PipelineConfig(files[0], files[1], files[2], None)


def _fake_stages(missing: tuple[str, ...] = ()) -> Stages:
    def synthesize(satb: dict[str, Any], out_dir: str, bpm: int, sf: str) -> dict[str, str]:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        paths = {}
        for voice, events in satb.items():
            if events:
                p = Path(out_dir) / f"{voice.lower()}.mp3"
                p.write_bytes(b"mp3-" + voice.encode())
                paths[voice] = str(p)
        return paths

    satb = {v: ([] if v in missing else [EVENT]) for v in pipeline.VOICES}
    flags = [{"kind": "x", "start_tick": 0, "end_tick": 5}, {"kind": "y"}]
    return Stages(
        preprocess=lambda i, p, k: [("img", 1, None)],
        clean_page=lambda page: CleanPage(b"jpg", 10, 20),
        detect=lambda pages, y, s, m: {},
        clef_key=lambda pages, m, w: None,
        transcribe=lambda v, w, d, e: {},
        reconstruct=lambda ev: (satb, {"flags": flags}),
        review=lambda ev, f: ({"reviewNeeded": False}, []),
        synthesize=synthesize,
    )


def _run(tmp_path: Path, stages: Stages, on_stage: Any = lambda s, p: None) -> pipeline.PipelineResult:
    return run_pipeline([_jpeg()], tempo_bpm=90, work_dir=tmp_path / "w", config=_config(tmp_path),
                        on_stage=on_stage, stages=stages)


def test_stage_callbacks_fire_in_order(tmp_path: Path) -> None:
    seen: list[tuple[str, int]] = []
    result = _run(tmp_path, _fake_stages(), lambda s, p: seen.append((s, p)))
    names = [s for s, _ in seen]
    assert names == ["preprocessing", "detecting_staff", "transcribing", "reconstructing", "synthesizing"]
    percents = [p for _, p in seen]
    assert percents == sorted(percents)
    assert set(result.stage_seconds) == set(names)


def test_result_maps_voices_and_lowercases_keys(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake_stages())
    assert result.mp3 == {"soprano": b"mp3-Soprano", "alto": b"mp3-Alto",
                          "tenor": b"mp3-Tenor", "bass": b"mp3-Bass"}
    assert result.failed_voices == []
    assert set(result.events) == {"soprano", "alto", "tenor", "bass"}
    assert result.pages == [CleanPage(b"jpg", 10, 20)]
    assert result.muted_measures == [{"kind": "x", "start_tick": 0, "end_tick": 5}]
    assert result.timing_inputs == {}


def test_empty_voice_becomes_failed_voice_unreadable(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake_stages(missing=("Alto",)))
    assert result.failed_voices == ["alto"]
    assert result.failed_voice_causes == {"alto": "unreadable"}
    assert "alto" not in result.mp3 and len(result.mp3) == 3


def test_missing_weights_raises_pipeline_error(tmp_path: Path) -> None:
    config = PipelineConfig(tmp_path / "no.pt", tmp_path / "no2.pt", tmp_path / "no.sf2", None)
    with pytest.raises(PipelineError, match="missing model file"):
        run_pipeline([_jpeg()], tempo_bpm=90, work_dir=tmp_path / "w", config=config,
                     on_stage=lambda s, p: None, stages=_fake_stages())


def test_unreadable_page_raises_with_index(tmp_path: Path) -> None:
    with pytest.raises(PipelineError) as info:
        run_pipeline([_jpeg(), b"not an image"], tempo_bpm=90, work_dir=tmp_path / "w",
                     config=_config(tmp_path), on_stage=lambda s, p: None, stages=_fake_stages())
    assert info.value.page_index == 1


@pytest.mark.slow
def test_moonriver_page1_end_to_end(tmp_path: Path) -> None:
    config = PipelineConfig.from_env(os.environ)
    needed = [MOONRIVER, config.yolo_weights, config.crnn_weights, config.soundfont]
    if not all(p.is_file() for p in needed):
        pytest.skip("weights or fixture absent")
    result = run_pipeline([MOONRIVER.read_bytes()], tempo_bpm=90, work_dir=tmp_path, config=config,
                          on_stage=lambda s, p: None)
    print("STAGE_SECONDS", result.stage_seconds)
    assert len(result.mp3) == 4 and all(result.mp3.values())
    assert len(result.pages) == 1 and result.pages[0].width > 0 and result.pages[0].height > 0
