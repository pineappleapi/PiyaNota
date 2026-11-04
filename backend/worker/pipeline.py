"""Adapter between the conversion worker and the Stage 1-5 OMR pipeline.

The stage modules live at the repo root and need torch/cv2, which the API image does not have, so
they are imported lazily and reached only through a ``Stages`` bundle that tests replace with fakes.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image

VOICES = ("Soprano", "Alto", "Tenor", "Bass")
FAILED_VOICE_CAUSE = "unreadable"
CRNN_STRIP_HEIGHT = 64  # Stage 3 CRNN input height
CLEAN_PAGE_JPEG_QUALITY = 90
STRIPS_MANIFEST = "manifest.json"

# (job status, percent reported when the stage starts), in pipeline order.
STAGE_PERCENT = (("preprocessing", 5), ("detecting_staff", 25), ("transcribing", 40),
                 ("reconstructing", 85), ("synthesizing", 92))

CLEF_KEY_DEFAULT = "training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt"
STAGE_FAILURE_REASONS = {"preprocessing": "no readable page", "detecting_staff": "no readable staves",
                         "transcribing": "could not read the notation"}

_REPO_ROOT = Path(__file__).resolve().parents[2]


class PipelineError(Exception):
    """The job cannot be converted (bad input or missing model); not a retryable crash."""

    def __init__(self, reason: str, page_index: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.page_index = page_index


@dataclass(frozen=True)
class CleanPage:
    """The Stage 1 cleaned page, JPEG encoded, as the app shows it."""

    jpeg: bytes
    width: int
    height: int


@dataclass(frozen=True)
class PipelineConfig:
    """Model and soundfont paths. v1 defaults to CRNN seed 1; point PIYA_CRNN_WEIGHTS at seed 2 to swap."""

    yolo_weights: Path
    crnn_weights: Path
    soundfont: Path
    # ClefKeyNet is advisory but ON by default (its events are flagged review_needed); None opts out.
    clef_key_weights: Path | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> PipelineConfig:
        def path(name: str, default: str) -> Path:
            return Path(env.get(name) or _REPO_ROOT / default)

        clef_key = env.get("PIYA_CLEFKEY_WEIGHTS")  # empty string = explicit opt-out
        return cls(
            yolo_weights=path("PIYA_YOLO_WEIGHTS", "staff_detector_files/weights/best.pt"),
            crnn_weights=path("PIYA_CRNN_WEIGHTS",
                              "music_symbol_detection/phase2_kaggle_models/seed1/phase2_seed1.pt"),
            soundfont=path("PIYA_SOUNDFONT", "soundfont/piano.sf2"),
            clef_key_weights=(_REPO_ROOT / CLEF_KEY_DEFAULT if clef_key is None
                              else Path(clef_key) if clef_key else None),
        )


@dataclass(frozen=True)
class Stages:
    """One callable per pipeline step so tests can inject fakes."""

    preprocess: Callable[[str, str, bool], list[Any]]
    clean_page: Callable[[Any], CleanPage]
    detect: Callable[[list[Any], str, str, str, list[Any] | None], dict[str, Any]]
    clef_key: Callable[[list[Any], str, str], Any]
    transcribe: Callable[[dict[str, Any], str, Any, str, dict[Any, list[float]] | None],
                         dict[str, list[dict[str, Any]]]]
    reconstruct: Callable[[dict[str, Any]], tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]]
    review: Callable[[dict[str, Any], list[dict[str, Any]]], tuple[dict[str, Any], list[dict[str, Any]]]]
    synthesize: Callable[[dict[str, Any], str, int, str], dict[str, str]]
    # (width, height) of the Stage 1 detection page; timing x/y are measured on it, not on the native image.
    page_size: Callable[[Any], tuple[int, int]]


@dataclass
class PipelineResult:
    mp3: dict[str, bytes]
    failed_voices: list[str]
    failed_voice_causes: dict[str, str]
    review: dict[str, Any]
    muted_measures: list[dict[str, Any]]
    pages: list[CleanPage]
    events: dict[str, list[dict[str, Any]]]
    stage_seconds: dict[str, float]
    # Keyword arguments for timing_export.build_timing (voice-capitalised events, strips, barlines,
    # page_sizes, report, bpm); empty when timing collection is off.
    timing_inputs: dict[str, Any] = field(default_factory=dict)


def real_stages() -> Stages:
    """Bind the real stage modules; CPU only.

    CUDA_VISIBLE_DEVICES=-1 is set here, before torch is imported, and is the only CPU guard; the worker
    entry point should set it too. The caller removes work_dir.
    """
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # empty string crashes ultralytics
    import cv2
    import stage3_clefkey
    import stage3_transcription as s3
    from stage1_preprocessing import preprocess_batch
    from stage2_detection import detect_staff_regions
    from stage4_reconstruction import reconstruct_satb_with_report
    from stage5_synthesis import build_review, synthesize_satb

    def preprocess(in_dir: str, prep_dir: str, keep_unmasked: bool) -> list[Any]:
        return preprocess_batch(in_dir, prep_dir, save_debug=False, keep_unmasked=keep_unmasked)

    def clean_page(page: Any) -> CleanPage:
        # The native strip source is the best cleaned view; the 1600 px binary is the fallback.
        image = page[2] if page[2] is not None else page[0]
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, CLEAN_PAGE_JPEG_QUALITY])
        if not ok:
            raise PipelineError("could not encode the cleaned page", page[1] - 1)
        return CleanPage(buf.tobytes(), int(image.shape[1]), int(image.shape[0]))

    def detect(pages: list[Any], yolo: str, strips_dir: str, manifest: str, geometry_out: list[Any] | None) -> Any:
        return detect_staff_regions(pages, model_weights=yolo, output_dir=strips_dir, manifest_path=manifest,
                                    geometry_out=geometry_out)

    def clef_key(pages: list[Any], manifest_path: str, weights: str) -> Any:
        model = stage3_clefkey.load_clef_key_model(stage3_clefkey.check_clef_key_weights(weights))
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        return stage3_clefkey.decisions_for_pages(pages, manifest, model)[0]

    def transcribe(voices: dict[str, Any], weights: str, decisions: Any, events_dir: str,
                   barlines_out: dict[Any, list[float]] | None) -> Any:
        return s3.transcribe_voice_sequences(
            voices, model_weights=weights, img_height=CRNN_STRIP_HEIGHT, viz_dir=events_dir + "_viz",
            events_dir=events_dir, clef_key_decisions=decisions, barlines_out=barlines_out)

    def synthesize(satb: dict[str, Any], out_dir: str, bpm: int, soundfont: str) -> dict[str, str]:
        return synthesize_satb(satb, output_dir=out_dir, bpm=bpm, soundfont_path=soundfont)

    return Stages(preprocess, clean_page, detect, clef_key, transcribe, reconstruct_satb_with_report,
                  build_review, synthesize, lambda page: (int(page[0].shape[1]), int(page[0].shape[0])))


def _validate_inputs(page_jpegs: list[bytes], config: PipelineConfig) -> None:
    required = [config.yolo_weights, config.crnn_weights, config.soundfont]
    if config.clef_key_weights is not None:
        required.append(config.clef_key_weights)
    for path in required:
        if not path.is_file():
            raise PipelineError(f"missing model file: {path.name}")
    if not page_jpegs:
        raise PipelineError("no pages")
    for index, data in enumerate(page_jpegs):
        try:
            with Image.open(BytesIO(data)) as img:
                img.verify()
        except (OSError, SyntaxError, Image.DecompressionBombError) as exc:  # truncated, non-image or huge
            raise PipelineError("unreadable page image", index) from exc  # reasons reach clients: no exc text


def _input_errors() -> tuple[type[BaseException], ...]:
    """Exceptions a bad photo can cause; cv2.error only exists where the real stages run."""
    try:
        import cv2
    except ImportError:
        return (ValueError, FileNotFoundError)
    return (ValueError, FileNotFoundError, cv2.error)


def _guard(status: str, call: Callable[[], Any]) -> Any:
    """Map input-caused failures to PipelineError with a fixed reason; real bugs (TypeError...) propagate."""
    try:
        return call()
    except _input_errors() as exc:
        raise PipelineError(STAGE_FAILURE_REASONS[status]) from exc


def run_pipeline(
    page_jpegs: list[bytes],
    *,
    tempo_bpm: int,
    work_dir: Path,
    config: PipelineConfig,
    on_stage: Callable[[str, int], None],
    stages: Stages | None = None,
    timing: bool = True,
) -> PipelineResult:
    """Run Stages 1-5 on the page photos; all temporary files stay under ``work_dir``.

    ``timing`` makes Stages 2 and 3 record strip geometry and barline positions for the timing export.
    """
    _validate_inputs(page_jpegs, config)
    st = stages or real_stages()
    in_dir, prep, strips, out = (work_dir / n for n in ("input", "prep", "strips", "audio"))
    in_dir.mkdir(parents=True, exist_ok=True)
    for index, data in enumerate(page_jpegs, start=1):
        (in_dir / f"page_{index:03d}.jpg").write_bytes(data)
    manifest = str(strips / STRIPS_MANIFEST)
    seconds: dict[str, float] = {}
    geometry: list[Any] | None = [] if timing else None
    barlines: dict[Any, list[float]] | None = {} if timing else None
    percent = dict(STAGE_PERCENT)

    def begin(status: str) -> float:
        on_stage(status, percent[status])
        return monotonic()

    t = begin("preprocessing")
    use_ck = config.clef_key_weights is not None
    pages = _guard("preprocessing", lambda: st.preprocess(str(in_dir), str(prep), use_ck))
    clean = [st.clean_page(p) for p in pages]
    seconds["preprocessing"] = monotonic() - t

    t = begin("detecting_staff")
    voices = _guard("detecting_staff",
                    lambda: st.detect(pages, str(config.yolo_weights), str(strips), manifest, geometry))
    seconds["detecting_staff"] = monotonic() - t

    t = begin("transcribing")
    def transcribe() -> dict[str, list[dict[str, Any]]]:
        decisions = st.clef_key(pages, manifest, str(config.clef_key_weights)) if use_ck else None
        return st.transcribe(voices, str(config.crnn_weights), decisions, str(work_dir / "stage3"), barlines)

    events = _guard("transcribing", transcribe)
    seconds["transcribing"] = monotonic() - t

    t = begin("reconstructing")
    try:
        satb, report = st.reconstruct(events)
    except ValueError as exc:  # Stage 4 raises when it cannot place a voice
        raise PipelineError("no readable staves") from exc  # fixed text: reasons reach clients
    review, _detail = st.review(events, report["flags"])
    seconds["reconstructing"] = monotonic() - t

    t = begin("synthesizing")
    paths = st.synthesize(satb, str(out), tempo_bpm, str(config.soundfont))
    seconds["synthesizing"] = monotonic() - t

    # Stage 5 falls back to a .mid when rendering fails; only real MP3s count as delivered voices.
    mp3 = {v.lower(): Path(p).read_bytes() for v, p in paths.items() if Path(p).suffix == ".mp3"}
    shutil.rmtree(out, ignore_errors=True)
    if not mp3:
        raise PipelineError("audio rendering failed")
    failed = [v.lower() for v in VOICES if v.lower() not in mp3]
    return PipelineResult(
        mp3=mp3,
        failed_voices=failed,
        failed_voice_causes={v: FAILED_VOICE_CAUSE for v in failed},
        review=review,
        muted_measures=[f for f in report["flags"] if "start_tick" in f and "end_tick" in f],
        pages=clean,
        events={v.lower(): satb.get(v, []) for v in VOICES},
        stage_seconds=seconds,
        timing_inputs={"events": satb, "strips": geometry, "barlines": barlines, "report": report,
                       "page_sizes": [st.page_size(p) for p in pages], "bpm": tempo_bpm} if timing else {},
    )
