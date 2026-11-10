"""Conversion worker: claim a queued job, run the pipeline, publish results, mark the job done or failed."""

from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import shutil
import signal
import tempfile
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

import psycopg

from backend import background, completion, db, migrate
from backend.midi_combined import build_combined_midi
from backend.config import Settings, load_settings
from backend.logutil import describe_exception
from backend.storage import Storage, build_storage, new_key
from backend.worker import health, queue
from backend.worker.pipeline import PipelineConfig, PipelineError, PipelineResult, run_pipeline

LOG = logging.getLogger(__name__)

UNEXPECTED_FAILURE_REASON = "conversion failed"  # fixed text: reasons reach clients, details go to the log
NO_PLAYBACK_FAILURE_REASON = "no playable audio could be built"  # distinct from a transient crash
HEARTBEAT_JOIN_TIMEOUT_S = 10.0
HUNG_EXIT_GRACE_S = 120.0  # after the overrun fail, how long a pipeline may take to notice before the worker exits
HUNG_WORKER_EXIT_CODE = 3
PROGRESS_WRITE_INTERVAL_S = 1.0  # was 2.0: coarser writes made the bar trail the log lines
EMPTY_TIMING: dict[str, Any] = {"events": []}

Runner = Callable[..., PipelineResult]


class _Cancelled(Exception):
    """The job left the working statuses (user cancel or reclaim); stop without failing it."""


def make_progress_writer(write: Callable[[int], None], *, clock: Callable[[], float] = monotonic,
                         interval_s: float = PROGRESS_WRITE_INTERVAL_S) -> Callable[[int], None]:
    """Wrap ``write`` so it runs at most once per ``interval_s`` and only when the percent rises.

    Progress is cosmetic: any exception from ``write`` is logged and swallowed, never failing the job,
    except ``_Cancelled``, which must reach the pipeline so a cancelled job stops early.
    """
    last_percent = -1
    last_at = float("-inf")

    def report(percent: int) -> None:
        nonlocal last_percent, last_at
        now = clock()
        if percent <= last_percent or now - last_at < interval_s:
            return
        try:
            write(percent)
        except _Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - progress must never fail a conversion
            LOG.warning("progress write failed: %s", type(exc).__name__)
            return
        last_percent, last_at = percent, now

    return report


def _queue_page_deletions(conn: Any, job_ids: Sequence[int]) -> None:
    """Queue the page objects of ``job_ids`` for deletion, as cancel does."""
    for job_id in job_ids:
        background.queue_deletion(conn, [r["object_key"] for r in conn.execute(
            "SELECT object_key FROM job_pages WHERE job_id = %s", (job_id,)).fetchall()])


def _heartbeat(url: str, job_id: int, interval_s: float, stop: threading.Event,
               connect: Callable[..., Any] = psycopg.connect, max_runtime_s: int | None = None,
               exit_grace_s: float = HUNG_EXIT_GRACE_S, exit_fn: Callable[[int], Any] = os._exit) -> None:
    """Touch the job until ``stop`` is set, on a private autocommit connection.

    With ``max_runtime_s`` it also fails the job once past that wall-clock limit and stops: the
    pipeline thread may be hung, so only this thread can enforce the cap in a one-worker deployment.
    The failed status makes the pipeline's next set_stage/set_progress raise _Cancelled. A pipeline
    thread that never reports again cannot be interrupted, so after ``exit_grace_s`` more seconds this
    thread ends the process with ``exit_fn`` (os._exit: nothing else can stop a hung thread).

    Its own connection keeps the heartbeat visible while the main thread holds long transactions;
    prepare_threshold=None keeps it safe behind Neon's pooled (PgBouncer) endpoint.
    """
    conn: Any = None
    while not stop.wait(interval_s):
        try:
            if conn is None:
                conn = connect(url, autocommit=True, prepare_threshold=None)
            conn.execute("UPDATE jobs SET heartbeat_at = clock_timestamp(), "
                         "updated_at = clock_timestamp() WHERE id = %s", (job_id,))
            if max_runtime_s is not None:
                with db.transaction() as pooled:  # fail + queue deletions commit together, or neither (retried next tick)
                    overrun = queue.fail_job_if_overrun(pooled, job_id, max_runtime_s=max_runtime_s)
                    if overrun:
                        _queue_page_deletions(pooled, [job_id])
                if overrun:
                    LOG.warning("job past max runtime, failed job_id=%s", job_id)
                    # A hung pipeline cannot be interrupted in-process: if it has not returned after the
                    # grace period, exit so the supervisor (restart: always / NSSM) gives a fresh worker.
                    if not stop.wait(exit_grace_s):
                        LOG.critical("pipeline still hung %ss after max runtime job_id=%s; exiting worker",
                                     exit_grace_s, job_id)
                        logging.shutdown()
                        exit_fn(HUNG_WORKER_EXIT_CODE)
                    break
        except psycopg.Error as exc:  # transient (Neon idle cutoff, restart): reconnect next tick, never exit
            LOG.warning("heartbeat failed job_id=%s: %s", job_id, type(exc).__name__)
            _close_quietly(conn)
            conn = None
        except Exception as exc:  # noqa: BLE001 - a dead heartbeat thread would silently disable the stale/overrun guards
            LOG.error("heartbeat error job_id=%s: %s", job_id, describe_exception(exc))
    _close_quietly(conn)


def _close_quietly(conn: Any) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except psycopg.Error as exc:
        LOG.warning("heartbeat close failed: %s", type(exc).__name__)


def _discard(storage: Storage, keys: Sequence[str]) -> None:
    """Delete uploaded objects; reservations are released only if every delete worked, else the queue retries."""
    if not keys:
        return
    try:
        for key in keys:
            storage.delete(key)
    except Exception as exc:  # noqa: BLE001 - any backend error: keep the reservation so the queue retries
        LOG.error("discarding uploads failed: %s", type(exc).__name__)
        return
    with db.transaction() as conn:
        background.release_keys(conn, keys)


SCALED_KEYS = ("x", "y", "systemTopY", "systemBottomY")


def _scale_to_served_pages(timing: dict[str, Any], result: PipelineResult) -> None:
    """Rescale event coordinates from the detection page to the served cleaned page, in place.

    build_timing measures on the 1600 px detection page while the app is served the native-size cleaned
    page, so unscaled highlights would sit at the wrong place. An event whose page has a missing or
    zero size on either side is left unscaled rather than failing the job (the app still plays audio).
    """
    detect_sizes = result.timing_inputs.get("page_sizes") or []
    for event in timing.get("events", []) + timing.get("bars", []):
        page = event.get("pageIndex")
        if not isinstance(page, int) or not 0 <= page < min(len(detect_sizes), len(result.pages)):
            continue
        (det_w, det_h), served = detect_sizes[page], result.pages[page]
        if det_w <= 0 or det_h <= 0 or served.width <= 0 or served.height <= 0:
            continue
        for key in SCALED_KEYS:
            if isinstance(event.get(key), (int, float)):
                event[key] = round(event[key] * (served.width / det_w if key == "x" else served.height / det_h), 1)


def _timing_bytes(result: PipelineResult, settings: Settings) -> bytes:
    """Timing JSON, or ``{"events": []}`` (with the reason logged) when disabled or inconsistent."""
    timing = EMPTY_TIMING
    if not settings.timing_enabled:
        LOG.info("timing skipped: disabled")
    elif not result.timing_inputs:
        LOG.info("timing skipped: no inputs")
    else:
        try:
            from timing_export import build_timing  # repo-root module, pure python

            timing = build_timing(**result.timing_inputs)
            _scale_to_served_pages(timing, result)
            if not timing.get("events"):
                LOG.warning("timing empty: build_timing found the geometry inconsistent")
            return json.dumps(timing).encode("utf-8")
        except Exception as exc:  # noqa: BLE001 - timing is optional; it must never fail a converted job
            LOG.error("timing failed, using empty timing: %s", describe_exception(exc))
            timing = EMPTY_TIMING
    return json.dumps(timing).encode("utf-8")


def _combined_midi(result: PipelineResult, timing: bytes) -> bytes:
    """Combined playback MIDI, the only thing the app plays for a new score.

    Raises:
        PipelineError: no usable bars/events, or the builder failed. Completing the job without it would
            leave a "done" score that cannot play, so the job fails (and can be retried) instead.
    """
    try:
        bars = json.loads(timing).get("bars")
        events = result.timing_inputs.get("events")
        combined = build_combined_midi(events, bars, result.timing_inputs.get("bpm"),
                                       result.failed_voices) if bars and events else None
    except Exception as exc:  # noqa: BLE001 - any builder error becomes one clear job failure
        LOG.error("combined midi failed: %s", describe_exception(exc))
        raise PipelineError(NO_PLAYBACK_FAILURE_REASON) from exc
    if combined is None:
        LOG.error("combined midi unavailable: no usable bars/events")
        raise PipelineError(NO_PLAYBACK_FAILURE_REASON)
    return combined


def _publish(job_id: int, result: PipelineResult, storage: Storage, settings: Settings,
             uploaded: list[str]) -> None:
    """Upload results and complete the job in one transaction.

    ``uploaded`` collects every key put so the caller can delete them on any non-success path.

    Raises:
        _Cancelled: complete_job refused (job cancelled or purged); the page swap is rolled back.
    """
    audio = {voice: new_key("audio", "mp3") for voice in result.mp3}
    midi = {voice: new_key("midi", "mid") for voice in result.midi}
    timing_key = new_key("timing", "json")
    thumb_key = new_key("thumbs", "jpg")
    page_keys = [new_key("pages", "jpg") for _ in result.pages]
    thumb = completion.make_thumbnail(result.pages[0].served_jpeg)
    timing = _timing_bytes(result, settings)
    combined = _combined_midi(result, timing)
    combined_key = new_key("midi", "mid")
    all_keys = [*audio.values(), *midi.values(), timing_key, thumb_key, *page_keys, combined_key]
    uploaded.extend(all_keys)  # tracked before the puts: a failed put may still have written the object
    background.reserve_keys(all_keys)  # committed first so a crash mid-upload leaves a reaper row
    uploads = [(audio[v], result.mp3[v], "audio/mpeg") for v in audio]
    uploads += [(midi[v], result.midi[v], "audio/midi") for v in midi]
    uploads += [(combined_key, combined, "audio/midi"),
                (timing_key, timing, "application/json"), (thumb_key, thumb, "image/jpeg")]
    uploads += [(k, p.served_jpeg, "image/jpeg") for k, p in zip(page_keys, result.pages)]
    for key, data, content_type in uploads:
        storage.put(key, data, content_type)

    with db.transaction() as conn:
        old_keys = [r["object_key"] for r in conn.execute(
            "SELECT object_key FROM job_pages WHERE job_id = %s", (job_id,)).fetchall()]
        conn.execute("DELETE FROM job_pages WHERE job_id = %s", (job_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO job_pages (job_id, page_index, object_key, width, height) VALUES (%s, %s, %s, %s, %s)",
                [(job_id, i, k, p.width, p.height) for i, (k, p) in enumerate(zip(page_keys, result.pages))])
        score_id = completion.complete_job(
            conn, job_id, audio_keys=audio, timing_key=timing_key, failed_voices=result.failed_voices,
            failed_voice_causes=result.failed_voice_causes, review=result.review,
            muted_measures=result.muted_measures, thumbnail_key=thumb_key, midi_keys=midi,
            midi_combined_key=combined_key)
        if score_id is None:
            raise _Cancelled  # rolls back the page swap too
        background.release_keys(conn, page_keys)
        background.queue_deletion(conn, old_keys)


def process_one(*, storage: Storage, runner: Runner, settings: Settings,
                heartbeat_interval_s: float | None = None) -> bool:
    """Run one queued job to completion or failure.

    Args:
        storage: Object store holding the job's page photos and receiving the results.
        runner: ``run_pipeline``-compatible callable (tests pass a fake).
        settings: Worker settings.
        heartbeat_interval_s: Override of the settings interval, for tests.

    Returns:
        False when no job was queued, True otherwise (even if the job failed).
    """
    with db.transaction() as conn:
        requeued, failed = queue.reclaim_stale(conn, timeout_s=queue.STALE_TIMEOUT_S, max_attempts=queue.MAX_ATTEMPTS)
        overrun = queue.fail_overrun(conn, max_runtime_s=settings.job_max_runtime_s)
        _queue_page_deletions(conn, overrun)  # same cleanup as a user cancel: the pages are no longer needed
        job = queue.claim_next_job(conn)
        pages = [] if job is None else conn.execute(
            "SELECT object_key FROM job_pages WHERE job_id = %s ORDER BY page_index", (job["id"],)).fetchall()
    if requeued or failed:
        LOG.warning("reclaimed stale jobs requeued=%s failed=%s", requeued, failed)
    if overrun:
        LOG.warning("failed jobs past max runtime job_ids=%s", overrun)
    if job is None:
        return False
    job_id: int = job["id"]
    LOG.info("job claimed job_id=%s attempt=%s queue_wait_s=%.1f", job_id, job["attempts"],
             _age_s(job["created_at"]))

    work_dir = Path(tempfile.mkdtemp(prefix=f"piya-job-{job_id}-"))  # before the thread so finally always pairs
    stop = threading.Event()
    beat = threading.Thread(
        target=_heartbeat, name=f"piya-heartbeat-{job_id}", daemon=True,
        args=(settings.database_url, job_id, heartbeat_interval_s or settings.worker_heartbeat_interval_s, stop),
        kwargs={"max_runtime_s": settings.job_max_runtime_s})
    beat.start()
    uploaded: list[str] = []
    failure: tuple[str, int | None] | None = None
    started = monotonic()
    marks: list[tuple[str, float]] = []  # (stage, start time); timing only, never read by logic
    try:
        def on_stage(status: str, percent: int) -> None:
            marks.append((status, monotonic()))
            with db.transaction() as conn:  # committed per stage so the status and heartbeat are visible
                if not queue.set_stage(conn, job_id, status, percent, None):
                    raise _Cancelled

        def write_progress(percent: int) -> None:
            with db.transaction() as conn:
                if not queue.set_progress(conn, job_id, percent):
                    raise _Cancelled  # stops the pipeline at its next progress report

        try:
            t_pages = monotonic()
            page_blobs = [storage.get(p["object_key"]) for p in pages]
            LOG.info("pages loaded job_id=%s pages=%s bytes=%s load_s=%.1f", job_id, len(page_blobs),
                     sum(len(b) for b in page_blobs), monotonic() - t_pages)
            result = runner(page_blobs, tempo_bpm=job["tempo_bpm"],
                            work_dir=work_dir, on_stage=on_stage, timing=settings.timing_enabled,
                            on_progress=make_progress_writer(write_progress))
            marks.append(("publish", monotonic()))
            _publish(job_id, result, storage, settings, uploaded)
        except _Cancelled:
            LOG.info("job cancelled job_id=%s", job_id)
            _discard(storage, uploaded)
        except PipelineError as exc:
            LOG.warning("pipeline error job_id=%s reason=%s", job_id, exc.reason)
            failure = (exc.reason, exc.page_index)
        except Exception as exc:  # noqa: BLE001 - any crash fails this job; the worker keeps serving
            LOG.error("job crashed job_id=%s: %s", job_id, describe_exception(exc))
            failure = (UNEXPECTED_FAILURE_REASON, None)
        if failure is not None:
            _discard(storage, uploaded)
            with db.transaction() as conn:
                completion.fail_job(conn, job_id, *failure)
    finally:
        stop.set()
        beat.join(HEARTBEAT_JOIN_TIMEOUT_S)
        shutil.rmtree(work_dir, ignore_errors=True)
        _log_timing(job_id, len(pages), started, marks, job["created_at"])
    return True


def _age_s(created_at: datetime) -> float:
    """Seconds since the job row was created (database clock vs. this host's clock: expect small skew)."""
    return (datetime.now(timezone.utc) - created_at).total_seconds()


def _log_timing(job_id: int, page_count: int, started: float, marks: list[tuple[str, float]],
                created_at: datetime) -> None:
    """Log total, per-stage and created-to-finished seconds so slow stages can be found from the worker log alone."""
    end = monotonic()
    stages = {name: round(nxt - t, 1) for (name, t), (_, nxt) in zip(marks, [*marks[1:], ("end", end)])}
    LOG.info("job timing job_id=%s pages=%s total_s=%.1f end_to_end_s=%.1f stages=%s", job_id, page_count,
             end - started, _age_s(created_at), stages)


def run_loop(*, storage: Storage, runner: Runner, settings: Settings, stop: threading.Event) -> None:
    """Poll for jobs until ``stop`` is set; sleep only when idle or after an infrastructure error."""
    while not stop.is_set():
        try:
            if process_one(storage=storage, runner=runner, settings=settings):
                continue
        except Exception as exc:  # noqa: BLE001 - e.g. database briefly unreachable; retry next poll
            LOG.error("worker iteration failed: %s", describe_exception(exc))
        stop.wait(settings.worker_poll_interval_s)


def check_schema(conn: psycopg.Connection[Any]) -> None:
    """Raise if any migration file is unapplied: a worker newer than the schema fails every job late."""
    missing = [v for v, ok in migrate.status(conn) if not ok]
    if missing:
        raise RuntimeError(f"database schema is behind this worker; unapplied migrations: {', '.join(missing)}")


def cli(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python -m backend.worker``."""
    parser = argparse.ArgumentParser(prog="python -m backend.worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="process at most one job and exit")
    mode.add_argument("--loop", action="store_true", help="poll for jobs until interrupted")
    parser.add_argument("--health-port", type=int, default=None, help="serve GET /health on this port")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings(os.environ)
    db.init_pool(settings.database_url, max_size=settings.db_pool_max_size,
                 prepare_threshold=settings.db_prepare_threshold)
    try:
        with db.transaction() as conn:
            check_schema(conn)
    except RuntimeError as exc:
        LOG.error("%s; deploy the API (it migrates at boot) first", exc)
        db.close_pool()
        return 1
    storage = build_storage(settings)
    runner = functools.partial(run_pipeline, config=PipelineConfig.from_env(os.environ))
    if args.health_port is not None:
        health.serve(args.health_port)
    try:
        if args.once:
            process_one(storage=storage, runner=runner, settings=settings)
        else:
            stop = threading.Event()
            # SIGTERM lets the current job finish or discard cleanly instead of dying mid-upload.
            signal.signal(signal.SIGTERM, lambda signum, frame: stop.set())
            run_loop(storage=storage, runner=runner, settings=settings, stop=stop)
    except KeyboardInterrupt:
        LOG.info("worker stopped")
    finally:
        db.close_pool()
    return 0
