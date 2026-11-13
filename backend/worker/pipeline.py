"""Adapter between the conversion worker and the Stage 1-5 OMR pipeline.

The stage modules live at the repo root and need torch/cv2, which the API image does not have, so
they are imported lazily and reached only through a ``Stages`` bundle that tests replace with fakes.
"""

# DEFENSE INDEX: (Ctrl+F the tag to jump to the explanation)
#   DEFENSE: lazy imports     - why torch/cv2 stage modules are imported inside real_stages(), not at the top
#   DEFENSE: stages bundle    - why every pipeline step is a field of one Stages object (tests swap in fakes)
#   DEFENSE: fixed reasons    - why failure reasons sent to clients are fixed text, never exception text
#   DEFENSE: cpu only         - why CUDA is switched off before torch loads
#   DEFENSE: progress bands   - how stage percentages and in-stage bands stay in order and never hit 100
#   DEFENSE: validate first   - why inputs and model files are checked before any heavy work
#   DEFENSE: input guard      - why only bad-photo errors become PipelineError and real bugs propagate
#   DEFENSE: blank pages      - why unreadable whole pages are flagged here
#   DEFENSE: cancel via progress - why on_progress may raise and nothing may swallow it
#   DEFENSE: free memory      - why big image planes are dropped after the JPEGs exist
#   DEFENSE: empty check      - why "all voices empty" is tested before Stage 4
#   DEFENSE: failed voices    - why a failed voice stays in the list (silent track) instead of vanishing
#   DEFENSE: midi only        - why the new score output is MIDI and MP3 is a legacy path

from __future__ import annotations

import json
import logging
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

# DEFENSE: progress bands - the app shows one progress bar for the whole job. Each stage owns a slice of
# 0-100: STAGE_PERCENT is where the slice starts, the *_BAND tuples are how far we creep inside it
# while the stage runs. Bands end just before the next stage starts so the bar never goes backwards,
# and only complete_job (outside this file) writes 100.
# (job status, percent reported when the stage starts), in pipeline order.
STAGE_PERCENT = (("preprocessing", 5), ("detecting_staff", 25), ("transcribing", 40),
                 ("reconstructing", 85), ("synthesizing", 92))

# In-stage progress bands (lo, hi) in percent. Weights are approximate: Moonriver smoke preprocessing took
# 52.7 s of 212.8 s in the 2026-11-05 run and 104 s in the 2026-11-04 run. hi stays below the next stage's
# start (25 / 85) so a stage never reports the next band before it ends; 100 is written only by complete_job.
PREPROCESS_BAND = (5, 24)
DETECT_BAND = (25, 39)  # Stage 2, reported per page so a cancel is noticed between pages
TRANSCRIBE_BAND = (40, 84)  # Stage 3 Pass 1 (CRNN forward, ~90%) then Pass 2, weighted inside Stage 3

ProgressFn = Callable[[int, int], None]

CLEF_KEY_DEFAULT = "models/clef_key_classifier.pt"
# DEFENSE: fixed reasons - these strings go to the phone app. We never put exception text in them,
# because it could leak file paths or internals. Each stage gets one short, user-safe sentence instead.
STAGE_FAILURE_REASONS = {"preprocessing": "no readable page", "detecting_staff": "no readable staves",
                         "transcribing": "could not read the notation"}

NO_VOICES_REASON = "no readable staves, please retake clearer photos of your pages"  # all four voices empty

LOG = logging.getLogger(__name__)
MISCONFIGURED_REASON = "service misconfigured"  # fixed text: reasons reach clients

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
    # Same size and deskew as ``jpeg`` but with the lyrics kept; None when Stage 1 had no native page.
    display_jpeg: bytes | None = None

    @property
    def served_jpeg(self) -> bytes:
        """The bytes stored and shown in the app: the lyrics-kept page when there is one."""
        return self.display_jpeg if self.display_jpeg is not None else self.jpeg


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
            yolo_weights=path("PIYA_YOLO_WEIGHTS", "models/best.pt"),
            crnn_weights=path("PIYA_CRNN_WEIGHTS",
                              "models/phase2_seed1.pt"),
            soundfont=path("PIYA_SOUNDFONT", "models/piano.sf2"),
            clef_key_weights=(_REPO_ROOT / CLEF_KEY_DEFAULT if clef_key is None
                              else Path(clef_key) if clef_key else None),
        )


# DEFENSE: stages bundle - the real stages need torch and OpenCV, which are slow to load and absent
# from the API image. Putting each step in one Stages object lets unit tests pass cheap fake functions
# with the same shapes, so the worker logic is tested without any ML libraries.
@dataclass(frozen=True)
class Stages:
    """One callable per pipeline step so tests can inject fakes.

    Each field matches one real stage function (see ``real_stages``); a fake only has to accept and
    return the same shapes.
    """

    preprocess: Callable[[str, str, bool, ProgressFn | None], list[Any]]
    clean_page: Callable[[Any], CleanPage]
    detect: Callable[[list[Any], str, str, str, list[Any] | None, ProgressFn | None], dict[str, Any]]
    clef_key: Callable[[list[Any], str, str], Any]
    transcribe: Callable[[dict[str, Any], str, Any, str, dict[Any, list[float]] | None, ProgressFn | None],
                         dict[str, list[dict[str, Any]]]]
    reconstruct: Callable[[dict[str, Any]], tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]]
    review: Callable[[dict[str, Any], list[dict[str, Any]]], tuple[dict[str, Any], list[dict[str, Any]]]]
    synthesize: Callable[[dict[str, Any], str, int, str], dict[str, str]]
    # (width, height) of the Stage 1 detection page; timing x/y are measured on it, not on the native image.
    page_size: Callable[[Any], tuple[int, int]]


@dataclass
class PipelineResult:
    mp3: dict[str, bytes]
    midi: dict[str, bytes]
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
    # DEFENSE: cpu only - the server has no GPU we want to depend on. Setting this to -1 hides all GPUs
    # from torch, but it only works if done BEFORE torch is imported, which is why it sits right here.
    # DEFENSE: lazy imports - the imports below are inside this function on purpose. Importing the
    # stage modules pulls in torch/cv2, so the API process (which never converts) stays light and
    # starts fast; only the worker that calls real_stages() pays that cost.
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # empty string crashes ultralytics
    import cv2
    import stage3_clefkey
    import stage3_transcription as s3
    from stage1_preprocessing import preprocess_batch
    from stage2_detection import detect_staff_regions
    from stage4_reconstruction import reconstruct_satb_with_report
    from stage5_synthesis import build_review, synthesize_satb

    def preprocess(in_dir: str, prep_dir: str, keep_unmasked: bool, progress: ProgressFn | None) -> list[Any]:
        return preprocess_batch(in_dir, prep_dir, save_debug=False, keep_unmasked=keep_unmasked,
                                keep_display=True, progress=progress)

    def clean_page(page: Any) -> CleanPage:
        # The native strip source is the best cleaned view; the 1600 px binary is the fallback.
        image = page[2] if page[2] is not None else page[0]
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, CLEAN_PAGE_JPEG_QUALITY])
        if not ok:
            raise PipelineError("could not encode the cleaned page", page[1] - 1)
        display_jpeg = None
        if page[2] is not None and len(page) > 3 and page[3] is not None and page[3].strip_display is not None:
            ok, dbuf = cv2.imencode(".jpg", page[3].strip_display, [cv2.IMWRITE_JPEG_QUALITY, CLEAN_PAGE_JPEG_QUALITY])
            if not ok:
                raise PipelineError("could not encode the display page", page[1] - 1)
            display_jpeg = dbuf.tobytes()
        return CleanPage(buf.tobytes(), int(image.shape[1]), int(image.shape[0]), display_jpeg)

    def detect(pages: list[Any], yolo: str, strips_dir: str, manifest: str, geometry_out: list[Any] | None,
               progress: ProgressFn | None) -> Any:
        return detect_staff_regions(pages, model_weights=yolo, output_dir=strips_dir, manifest_path=manifest,
                                    geometry_out=geometry_out, progress=progress)

    def clef_key(pages: list[Any], manifest_path: str, weights: str) -> Any:
        model = stage3_clefkey.load_clef_key_model(stage3_clefkey.check_clef_key_weights(weights))
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        return stage3_clefkey.decisions_for_pages(pages, manifest, model)[0]

    def transcribe(voices: dict[str, Any], weights: str, decisions: Any, events_dir: str,
                   barlines_out: dict[Any, list[float]] | None, progress: ProgressFn | None) -> Any:
        return s3.transcribe_voice_sequences(
            voices, model_weights=weights, img_height=CRNN_STRIP_HEIGHT, viz_dir=events_dir + "_viz",
            events_dir=events_dir, clef_key_decisions=decisions, barlines_out=barlines_out,
            progress=progress)

    def synthesize(satb: dict[str, Any], out_dir: str, bpm: int, soundfont: str) -> dict[str, str]:
        return synthesize_satb(satb, output_dir=out_dir, bpm=bpm, soundfont_path=soundfont, render_audio=False)

    return Stages(preprocess, clean_page, detect, clef_key, transcribe, reconstruct_satb_with_report,
                  build_review, synthesize, lambda page: (int(page[0].shape[1]), int(page[0].shape[0])))


def _validate_inputs(page_jpegs: list[bytes], config: PipelineConfig) -> None:
    """Fail fast, before any heavy work: all model files exist and every page is a real image.

    Raises:
        PipelineError: "service misconfigured" for a missing model (our fault, details only in the
            log) or a short fixed reason for bad pages (the user's photo).
    """
    # DEFENSE: validate first - a missing weights file or a corrupt upload would otherwise fail
    # minutes into the run. Checking now gives an instant, clear answer. img.verify() reads the file
    # structure without decoding all pixels, so it is cheap.
    required = [config.yolo_weights, config.crnn_weights, config.soundfont]
    if config.clef_key_weights is not None:
        required.append(config.clef_key_weights)
    for path in required:
        if not path.is_file():
            LOG.error("missing model file: %s", path)
            raise PipelineError(MISCONFIGURED_REASON)
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
    # DEFENSE: input guard - only errors a bad photo can cause (ValueError, missing file, OpenCV error)
    # become a friendly "could not read" failure. Anything else, like a TypeError, is OUR bug: it is
    # left to crash loudly so we notice and fix it instead of blaming the user's photo.
    try:
        return call()
    except _input_errors() as exc:
        raise PipelineError(STAGE_FAILURE_REASONS[status]) from exc


def _flag_blank_pages(satb: dict[str, list[dict[str, Any]]], flags: list[dict[str, Any]], n_pages: int) -> None:
    """Add pages (1-based) where no voice has any event to every voice's ``voice_unreadable`` flag.

    Stage 4 only sees pages that have events, so a fully unreadable page would otherwise be lost silently.
    """
    # DEFENSE: blank pages - if page 2 of 3 produced no notes at all, Stage 4 never hears about it and
    # the song would just be shorter with no warning. We compare the pages we received with the pages
    # that have events and raise a "review needed" flag for the missing ones, for every voice.
    seen = {e["page_index"] for evs in satb.values() for e in evs if "page_index" in e}
    blank = [p for p in range(1, n_pages + 1) if p not in seen] if seen else []
    if not blank:
        return
    for voice in VOICES:
        flag = next((f for f in flags if f.get("kind") == "voice_unreadable" and f.get("voice") == voice), None)
        if flag is None:
            flags.append({"kind": "voice_unreadable", "voice": voice, "pages": blank, "page_index": None,
                          "sys_idx": None, "bar": None, "review_needed": True})
        else:
            flag["pages"] = sorted(set(flag["pages"]) | set(blank))


def run_pipeline(
    page_jpegs: list[bytes],
    *,
    tempo_bpm: int,
    work_dir: Path,
    config: PipelineConfig,
    on_stage: Callable[[str, int], None],
    stages: Stages | None = None,
    timing: bool = True,
    on_progress: Callable[[int], None] | None = None,
) -> PipelineResult:
    """Run Stages 1-5 on the page photos; all temporary files stay under ``work_dir``.

    ``timing`` makes Stages 2 and 3 record strip geometry and barline positions for the timing export.
    ``on_progress`` gets an overall percent inside the preprocessing and transcribing bands; it may raise to abort a cancelled job,
    so nothing here may swallow its exception.

    Returns:
        PipelineResult with per-voice MIDI (and MP3 on the legacy path), failed voices, review flags,
        cleaned pages and per-stage timings.

    Raises:
        PipelineError: input or configuration problem with a client-safe reason.
    """
    # DEFENSE: cancel via progress - the user can cancel a job. The worker does that by making
    # on_progress raise an exception; the stages call it often, so the job stops at the next update.
    # That is why none of the code here may catch broad exceptions around those calls.
    _validate_inputs(page_jpegs, config)
    t_libs = monotonic()
    st = stages or real_stages()
    LOG.info("pipeline libraries ready load_s=%.1f pages=%s", monotonic() - t_libs, len(page_jpegs))
    in_dir, prep, strips, out = (work_dir / n for n in ("input", "prep", "strips", "audio"))
    in_dir.mkdir(parents=True, exist_ok=True)
    for index, data in enumerate(page_jpegs, start=1):
        (in_dir / f"page_{index:03d}.jpg").write_bytes(data)
    manifest = str(strips / STRIPS_MANIFEST)
    seconds: dict[str, float] = {}
    geometry: list[Any] | None = [] if timing else None
    barlines: dict[Any, list[float]] | None = {} if timing else None
    percent = dict(STAGE_PERCENT)

    def band(lo_hi: tuple[int, int]) -> ProgressFn | None:
        if on_progress is None:
            return None
        lo, hi = lo_hi
        return lambda done, total: on_progress(lo + (hi - lo) * done // max(total, 1))

    def begin(status: str) -> float:
        LOG.info("stage start status=%s percent=%s", status, percent[status])
        on_stage(status, percent[status])
        return monotonic()

    t = begin("preprocessing")
    use_ck = config.clef_key_weights is not None
    pages = _guard("preprocessing", lambda: st.preprocess(str(in_dir), str(prep), use_ck, band(PREPROCESS_BAND)))
    clean = [st.clean_page(p) for p in pages]
    # DEFENSE: free memory - a 12 MP photo keeps big image arrays alive. The app only needs the JPEGs
    # made just above, so we drop the heavy arrays now to keep the worker's RAM low for later stages.
    # Free the native display planes (and the whole PreprocessedPage when ClefKeyNet is off) now that
    # the JPEGs exist; the worker otherwise holds ~24 MB per 12 MP page until synthesis ends.
    pages = [tuple(p) if use_ck else tuple(p[:3]) for p in pages]
    for p in pages:
        if len(p) > 3 and p[3] is not None:
            p[3].strip_display = None
    seconds["preprocessing"] = monotonic() - t

    t = begin("detecting_staff")
    voices = _guard("detecting_staff",
                    lambda: st.detect(pages, str(config.yolo_weights), str(strips), manifest, geometry,
                                      band(DETECT_BAND)))
    seconds["detecting_staff"] = monotonic() - t

    t = begin("transcribing")
    def transcribe() -> dict[str, list[dict[str, Any]]]:
        decisions = st.clef_key(pages, manifest, str(config.clef_key_weights)) if use_ck else None
        return st.transcribe(voices, str(config.crnn_weights), decisions, str(work_dir / "stage3"), barlines,
                             band(TRANSCRIBE_BAND))

    events = _guard("transcribing", transcribe)
    seconds["transcribing"] = monotonic() - t

    t = begin("reconstructing")
    # DEFENSE: empty check - "no notes in any voice" is the one case we report as unreadable photos.
    # We test it ourselves instead of catching Stage 4's ValueError, so a different ValueError (a real
    # bug) is not blamed on the user.
    # Stage 4 raises ValueError only when all four voices are empty; checking here keeps any other
    # ValueError (a real bug) from being reported to the client as unreadable photos.
    if not any(events.get(v) for v in VOICES):
        raise PipelineError(NO_VOICES_REASON)  # fixed text: reasons reach clients
    satb, report = st.reconstruct(events)
    _flag_blank_pages(satb, report["flags"], len(page_jpegs))
    review, detail = st.review(events, report["flags"])
    LOG.info("review flags full_count=%s", len(detail))  # the uncapped list is log-only, never stored
    seconds["reconstructing"] = monotonic() - t

    t = begin("synthesizing")
    paths = st.synthesize(satb, str(out), tempo_bpm, str(config.soundfont))
    seconds["synthesizing"] = monotonic() - t

    # DEFENSE: midi only - the new flow makes MIDI files (small, the phone plays them) and skips MP3
    # rendering. The mp3 dict stays only so older or injected stages still work.
    # Stage 5 falls back to a .mid when rendering fails; an unreadable voice is a silent MP3 and
    # is listed by Stage 4, not inferred from a missing file.
    mp3 = {v.lower(): Path(p).read_bytes() for v, p in paths.items() if Path(p).suffix == ".mp3"}
    # Stage 5 writes every voice's .mid before rendering, so these exist even for fallback voices.
    midi = {v.lower(): (out / f"{v.lower()}.mid").read_bytes() for v in VOICES
            if (out / f"{v.lower()}.mid").is_file()}
    shutil.rmtree(out, ignore_errors=True)
    # New scores are MIDI-only (render_audio=False); a non-empty mp3 only comes from an injected/legacy stage.
    rendered = mp3.keys() if mp3 else midi.keys()
    if not rendered:
        raise PipelineError("audio rendering failed")
    # DEFENSE: failed voices - a voice that Stage 4 could not read (or has no output file) is still
    # listed in `failed`, in fixed S-A-T-B order, instead of being dropped. The app then shows that
    # voice as "unreadable" and the other three still play. Its MIDI is removed below, so there is
    # nothing wrong to play, and its cause is the fixed text FAILED_VOICE_CAUSE.
    # A voice with no rendered file must not vanish from failedVoices.
    failed = [v.lower() for v in VOICES
              if v in report.get("failed_voices", []) or v.lower() not in rendered]
    return PipelineResult(
        mp3=mp3,
        midi={v: b for v, b in midi.items() if v not in failed},
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
