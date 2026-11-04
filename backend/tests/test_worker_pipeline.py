"""Pipeline adapter: stage order, voice mapping, failed voices and config errors (fake stages), plus one real run."""

from __future__ import annotations

import os
from dataclasses import replace
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


def _fake_stages(missing: tuple[str, ...] = (), midi_only: bool = False) -> Stages:
    def synthesize(satb: dict[str, Any], out_dir: str, bpm: int, sf: str) -> dict[str, str]:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        paths = {}
        for voice in satb:  # an unreadable voice is a silent track, never a missing file
            p = Path(out_dir) / f"{voice.lower()}.{'mid' if midi_only else 'mp3'}"
            p.write_bytes(b"mp3-" + voice.encode())
            paths[voice] = str(p)
        return paths

    satb = {v: ([] if v in missing else [EVENT]) for v in pipeline.VOICES}
    flags = [{"kind": "x", "start_tick": 0, "end_tick": 5}, {"kind": "y"}]
    return Stages(
        preprocess=lambda i, p, k: [("img", 1, None)],
        clean_page=lambda page: CleanPage(b"jpg", 10, 20),
        detect=lambda pages, y, s, m, g: {},
        clef_key=lambda pages, m, w: None,
        transcribe=lambda v, w, d, e, b: {},
        reconstruct=lambda ev: (satb, {"flags": flags, "failed_voices": list(missing)}),
        review=lambda ev, f: ({"reviewNeeded": False}, []),
        synthesize=synthesize,
        page_size=lambda page: (10, 20),
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
    assert result.timing_inputs["page_sizes"] == [(10, 20)] and result.timing_inputs["bpm"] == 90
    assert set(result.timing_inputs) == {"events", "strips", "barlines", "report", "page_sizes", "bpm"}


def test_failed_voices_from_report_job_succeeds(tmp_path: Path) -> None:
    item = {"code": "voice_unreadable", "voice": "tenor", "pages": [1, 2]}
    stages = replace(_fake_stages(missing=("Tenor",)), review=lambda ev, f: ({"items": [item]}, [item]),
                     reconstruct=lambda ev: (
                         {v: ([] if v == "Tenor" else [EVENT]) for v in pipeline.VOICES},
                         {"flags": [{"kind": "voice_unreadable", "voice": "Tenor", "pages": [1, 2],
                                     "review_needed": True}], "failed_voices": ["Tenor"]}))
    result = _run(tmp_path, stages)
    assert result.failed_voices == ["tenor"]
    assert result.failed_voice_causes == {"tenor": "unreadable"}
    assert result.review["items"][0]["code"] == "voice_unreadable"
    assert result.review["items"][0]["voice"] == "tenor" and result.review["items"][0]["pages"] == [1, 2]


def test_page_with_no_events_in_any_voice_is_flagged(tmp_path: Path) -> None:
    ev = {"type": "note", "pitch": 60, "page_index": 1}
    seen: list[Any] = []
    stages = replace(_fake_stages(), reconstruct=lambda e: ({v: [ev] for v in pipeline.VOICES}, {"flags": [], "failed_voices": []}),
                     review=lambda e, f: seen.append(f) or ({}, []))
    run_pipeline([_jpeg(), _jpeg()], tempo_bpm=90, work_dir=tmp_path / "w", config=_config(tmp_path),
                 on_stage=lambda s, p: None, stages=stages)
    flags = [f for f in seen[0] if f["kind"] == "voice_unreadable"]
    assert sorted(f["voice"] for f in flags) == ["Alto", "Bass", "Soprano", "Tenor"]
    assert all(f["pages"] == [2] and f["review_needed"] for f in flags)


def test_voice_whose_render_fell_back_to_midi_is_failed(tmp_path: Path) -> None:
    def synthesize(satb: dict[str, Any], out_dir: str, bpm: int, sf: str) -> dict[str, str]:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        paths = {}
        for voice in satb:
            p = Path(out_dir) / f"{voice.lower()}.{'mid' if voice == 'Bass' else 'mp3'}"
            p.write_bytes(b"x")
            paths[voice] = str(p)
        return paths

    result = _run(tmp_path, replace(_fake_stages(), synthesize=synthesize))
    assert result.failed_voices == ["bass"] and "bass" not in result.mp3


def test_all_empty_fails_with_retake_message(tmp_path: Path) -> None:
    def raiser(ev: Any) -> Any:
        raise ValueError("all four empty")

    with pytest.raises(PipelineError, match="retake"):
        _run(tmp_path, replace(_fake_stages(), reconstruct=raiser))


def test_missing_weights_raises_pipeline_error(tmp_path: Path) -> None:
    config = PipelineConfig(tmp_path / "no.pt", tmp_path / "no2.pt", tmp_path / "no.sf2", None)
    with pytest.raises(PipelineError, match="service misconfigured"):
        run_pipeline([_jpeg()], tempo_bpm=90, work_dir=tmp_path / "w", config=config,
                     on_stage=lambda s, p: None, stages=_fake_stages())


def test_unreadable_page_raises_with_index(tmp_path: Path) -> None:
    with pytest.raises(PipelineError) as info:
        run_pipeline([_jpeg(), b"not an image"], tempo_bpm=90, work_dir=tmp_path / "w",
                     config=_config(tmp_path), on_stage=lambda s, p: None, stages=_fake_stages())
    assert info.value.page_index == 1


def test_from_env_defaults_and_opt_out() -> None:
    default = PipelineConfig.from_env({})
    assert default.clef_key_weights is not None and default.clef_key_weights.name == "clef_key_classifier.pt"
    assert default.yolo_weights.name == "best.pt" and default.crnn_weights.name == "phase2_seed1.pt"
    assert PipelineConfig.from_env({"PIYA_CLEFKEY_WEIGHTS": ""}).clef_key_weights is None
    assert PipelineConfig.from_env({"PIYA_CLEFKEY_WEIGHTS": "x.pt"}).clef_key_weights == Path("x.pt")


def test_missing_clef_key_file_raises(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = PipelineConfig(config.yolo_weights, config.crnn_weights, config.soundfont, tmp_path / "ck.pt")
    with pytest.raises(PipelineError, match="service misconfigured"):
        run_pipeline([_jpeg()], tempo_bpm=90, work_dir=tmp_path / "w", config=config,
                     on_stage=lambda s, p: None, stages=_fake_stages())


def test_midi_only_output_raises_audio_rendering_failed(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="audio rendering failed"):
        _run(tmp_path, _fake_stages(midi_only=True))


def test_input_errors_map_to_fixed_reasons(tmp_path: Path) -> None:
    def boom(exc: Exception) -> Any:
        def raiser(*args: Any) -> Any:
            raise exc
        return raiser

    with pytest.raises(PipelineError) as info:
        _run(tmp_path, replace(_fake_stages(), detect=boom(ValueError("secret detail"))))
    assert info.value.reason == "no readable staves"
    with pytest.raises(PipelineError) as info:
        _run(tmp_path, replace(_fake_stages(), preprocess=boom(FileNotFoundError("/x"))))
    assert info.value.reason == "no readable page"


def test_reconstruction_error_uses_fixed_reason(tmp_path: Path) -> None:
    def raiser(ev: Any) -> Any:
        raise ValueError("raw stage text")

    with pytest.raises(PipelineError) as info:
        _run(tmp_path, replace(_fake_stages(), reconstruct=raiser))
    assert info.value.reason == pipeline.NO_VOICES_REASON and "raw stage text" not in str(info.value)


def test_audio_failure_still_cleans_output_dir(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="audio rendering failed"):
        _run(tmp_path, _fake_stages(midi_only=True))
    assert not (tmp_path / "w" / "audio").exists()


def test_genuine_bugs_propagate(tmp_path: Path) -> None:
    def raiser(*args: Any) -> Any:
        raise TypeError("bug")

    with pytest.raises(TypeError):
        _run(tmp_path, replace(_fake_stages(), transcribe=raiser))


@pytest.mark.slow
def test_moonriver_page1_end_to_end(tmp_path: Path) -> None:
    config = PipelineConfig.from_env(os.environ)
    weights = [config.yolo_weights, config.crnn_weights, config.soundfont]
    if config.clef_key_weights is not None:
        weights.append(config.clef_key_weights)
    if not all(p.is_file() for p in weights):
        pytest.skip("weights absent")
    assert MOONRIVER.is_file(), f"fixture image missing: {MOONRIVER}"
    result = run_pipeline([MOONRIVER.read_bytes()], tempo_bpm=90, work_dir=tmp_path, config=config,
                          on_stage=lambda s, p: None)
    print("STAGE_SECONDS", result.stage_seconds)
    assert len(result.mp3) == 4 and all(result.mp3.values())
    assert len(result.pages) == 1 and result.pages[0].width > 0 and result.pages[0].height > 0
