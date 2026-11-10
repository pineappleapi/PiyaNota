"""Worker loop: claim, run (fake runner), publish, fail, cancel, heartbeat, health endpoint."""

from __future__ import annotations

import io
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from PIL import Image

from backend import db, migrate
from backend.config import Settings
from backend.storage import MemoryStorage
from backend.worker import health
from backend.worker import main as worker_main
from backend.worker.main import NO_PLAYBACK_FAILURE_REASON, UNEXPECTED_FAILURE_REASON, check_schema, process_one
from backend.worker.pipeline import CleanPage, PipelineError, PipelineResult

VOICES = ("soprano", "alto", "tenor", "bass")
SECRET = "secret-token-xyz"
HEARTBEAT_TEST_INTERVAL_S = 0.1
HEARTBEAT_TEST_RUN_S = 0.6
REAL_COMBINED_MIDI = worker_main._combined_midi


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


@pytest.fixture(autouse=True)
def _stub_combined_midi(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake pipeline result carries no bars; tests of the real builder call ``_real_combined_midi``."""
    monkeypatch.setattr(worker_main, "_combined_midi", lambda result, timing: b"MThd-stub")


def _real_combined_midi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_main, "_combined_midi", REAL_COMBINED_MIDI)


def _jpeg(size: tuple[int, int] = (80, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "JPEG")
    return buf.getvalue()


def _seed_job(storage: MemoryStorage, pages: int = 2) -> tuple[int, list[str]]:
    keys = [f"pages/old{i}.jpg" for i in range(pages)]
    with db.transaction() as conn:
        user = conn.execute("INSERT INTO users (email, password_hash) VALUES ('a@example.com', 'x') RETURNING id").fetchone()
        job = conn.execute(
            "INSERT INTO jobs (user_id, status, source, page_count, title, tempo_bpm, tempo_source, key_signature, "
            "time_signature) VALUES (%s, 'queued', 'images', %s, 'Bayan Ko', 100, 'user', 'G', '3/4') RETURNING id",
            (user["id"], pages)).fetchone()
        for i, key in enumerate(keys):
            conn.execute("INSERT INTO job_pages (job_id, page_index, object_key, width, height) VALUES (%s, %s, %s, 80, 60)",
                         (job["id"], i, key))
            storage.put(key, _jpeg(), "image/jpeg")
    return int(job["id"]), keys


def _result(voices: tuple[str, ...] = VOICES, failed: list[str] | None = None, pages: int = 2,
            mp3: bool = True) -> PipelineResult:
    return PipelineResult(
        mp3={v: b"mp3-" + v.encode() for v in voices if mp3}, midi={v: b"mid-" + v.encode() for v in voices},
        failed_voices=failed or [],
        failed_voice_causes={v: "unreadable" for v in failed or []},
        review={"reviewNeeded": False, "reasons": [], "items": [], "truncated": False}, muted_measures=[],
        pages=[CleanPage(_jpeg((40, 30)), 40, 30) for _ in range(pages)], events={}, stage_seconds={},
        timing_inputs={})


def _runner(result: PipelineResult | None = None, raises: Exception | None = None, stages: bool = True) -> Any:
    def run(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool, on_progress: Any = None) -> PipelineResult:
        assert tempo_bpm == 100 and page_jpegs and work_dir.is_dir()
        if stages:
            on_stage("preprocessing", 5)
            on_stage("synthesizing", 92)
        if raises is not None:
            raise raises
        return result or _result()
    return run


def _job(job_id: int) -> Any:
    with db.transaction() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()


def _count(table: str) -> int:
    with db.transaction() as conn:
        return int(conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"])


def test_happy_path_completes_job_and_replaces_pages_with_cleaned_ones(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)
    assert process_one(storage=storage, runner=_runner(), settings=settings) is True
    job = _job(job_id)
    assert job["status"] == "complete" and job["score_id"] is not None and job["percent_complete"] == 100
    with db.transaction() as conn:
        pages = conn.execute("SELECT * FROM job_pages WHERE job_id = %s ORDER BY page_index", (job_id,)).fetchall()
        tracks = conn.execute("SELECT voice, file_key FROM audio_tracks").fetchall()
        midi_rows = conn.execute("SELECT voice, midi_key FROM audio_tracks").fetchall()
        timing = conn.execute("SELECT metadata_key FROM timing_metadata").fetchone()
        reserved = conn.execute("SELECT count(*) AS n FROM storage_deletions").fetchone()["n"]
    assert [(p["width"], p["height"]) for p in pages] == [(40, 30), (40, 30)]
    assert not {p["object_key"] for p in pages} & set(old_keys)
    assert len(tracks) == 4 and storage.get(timing["metadata_key"]) == b'{"events": []}'
    assert {t["voice"]: storage.get(t["midi_key"]) for t in midi_rows} == {v: b"mid-" + v.encode() for v in VOICES}
    assert all(p["object_key"] in storage.objects for p in pages)
    assert reserved == len(old_keys)  # only the old page blobs wait in the deletion queue


def test_old_page_blobs_are_queued_for_deletion(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    _, old_keys = _seed_job(storage)
    process_one(storage=storage, runner=_runner(), settings=settings)
    with db.transaction() as conn:
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions").fetchall()}
    assert queued == set(old_keys)


def test_pipeline_error_fails_job_with_reason_and_page_index(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    process_one(storage=storage, runner=_runner(raises=PipelineError("no readable page", 1)), settings=settings)
    job = _job(job_id)
    assert (job["status"], job["failure_reason"], job["failure_page_index"]) == ("failed", "no readable page", 1)
    assert _count("scores") == 0


def test_unexpected_exception_fails_job_without_leaking_traceback(
        app: Flask, settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    process_one(storage=storage, runner=_runner(raises=RuntimeError(SECRET)), settings=settings)
    job = _job(job_id)
    assert job["status"] == "failed" and job["failure_reason"] == UNEXPECTED_FAILURE_REASON
    assert SECRET not in job["failure_reason"] and "Traceback" not in job["failure_reason"]
    assert "RuntimeError" in caplog.text


def test_job_cancelled_mid_run_discards_uploads_and_creates_no_score(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)

    def cancelling(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool, on_progress: Any = None) -> PipelineResult:
        on_stage("preprocessing", 5)
        with db.transaction() as conn:
            conn.execute("UPDATE jobs SET status = 'cancelled' WHERE id = %s", (job_id,))
        on_stage("detecting_staff", 25)
        raise AssertionError("pipeline must stop after on_stage reports cancellation")

    process_one(storage=storage, runner=cancelling, settings=settings)
    assert _job(job_id)["status"] == "cancelled" and _count("scores") == 0
    assert set(storage.objects) == set(old_keys)


def test_cancel_during_publish_discards_uploads_and_keeps_old_pages(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)

    def late_cancel(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool, on_progress: Any = None) -> PipelineResult:
        on_stage("synthesizing", 92)
        with db.transaction() as conn:
            conn.execute("UPDATE jobs SET status = 'cancelled' WHERE id = %s", (job_id,))
        return _result()

    process_one(storage=storage, runner=late_cancel, settings=settings)
    assert _count("scores") == 0 and set(storage.objects) == set(old_keys)
    with db.transaction() as conn:
        kept = [r["object_key"] for r in conn.execute("SELECT object_key FROM job_pages ORDER BY page_index").fetchall()]
        assert conn.execute("SELECT count(*) AS n FROM storage_deletions").fetchone()["n"] == 0
    assert kept == old_keys


def test_failed_publish_leaves_no_orphan_blobs(app: Flask, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)
    real_put = storage.put
    calls: list[str] = []

    def flaky(key: str, data: bytes, content_type: str) -> None:
        calls.append(key)
        if len(calls) == 3:
            raise OSError("disk full")
        real_put(key, data, content_type)

    monkeypatch.setattr(storage, "put", flaky)
    process_one(storage=storage, runner=_runner(), settings=settings)
    assert _job(job_id)["status"] == "failed" and set(storage.objects) == set(old_keys)


def test_heartbeat_updates_while_runner_blocks(app: Flask, settings: Settings) -> None:
    import time

    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    seen: list[Any] = []

    def slow(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool, on_progress: Any = None) -> PipelineResult:
        on_stage("preprocessing", 5)
        seen.append(_job(job_id)["heartbeat_at"])
        time.sleep(HEARTBEAT_TEST_RUN_S)  # several intervals with no stage call
        seen.append(_job(job_id)["heartbeat_at"])
        return _result()

    process_one(storage=storage, runner=slow, settings=settings, heartbeat_interval_s=HEARTBEAT_TEST_INTERVAL_S)
    assert seen[1] > seen[0]
    assert _job(job_id)["status"] == "complete"


def test_no_queued_job_returns_false(app: Flask, settings: Settings) -> None:
    assert process_one(storage=MemoryStorage(), runner=_runner(), settings=settings) is False


def test_failed_voice_is_omitted_from_audio_tracks(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    process_one(storage=storage, runner=_runner(_result(("soprano", "tenor", "bass"), failed=["alto"])), settings=settings)
    with db.transaction() as conn:
        voices = {r["voice"] for r in conn.execute("SELECT voice FROM audio_tracks").fetchall()}
        score = conn.execute("SELECT failed_voices, failed_voice_causes FROM scores").fetchone()
    assert voices == {"soprano", "tenor", "bass"}
    assert score["failed_voices"] == ["alto"] and score["failed_voice_causes"] == {"alto": "unreadable"}


def test_timing_enabled_builds_timing_from_inputs(
        app: Flask, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import timing_export

    storage = MemoryStorage()
    _seed_job(storage)
    got: dict[str, Any] = {}

    def fake_build(**kwargs: Any) -> dict[str, Any]:
        got.update(kwargs)
        return {"events": [{"x": 1}], "bars": []}

    monkeypatch.setattr(timing_export, "build_timing", fake_build)
    result = replace(_result(), timing_inputs={"bpm": 100})
    process_one(storage=storage, runner=_runner(result), settings=settings)
    with db.transaction() as conn:
        key = conn.execute("SELECT metadata_key FROM timing_metadata").fetchone()["metadata_key"]
    assert got == {"bpm": 100} and b'"x": 1' in storage.get(key)


def test_combined_midi_uploaded_when_bars_exist(
        app: Flask, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = MemoryStorage()
    _seed_job(storage)
    result = _bars_timing(monkeypatch)
    process_one(storage=storage, runner=_runner(result), settings=settings)
    with db.transaction() as conn:
        key = conn.execute("SELECT midi_combined_key FROM scores").fetchone()["midi_combined_key"]
    assert storage.get(key)[:4] == b"MThd"


def test_no_bars_fails_job_and_uploads_nothing(
        app: Flask, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import timing_export

    storage = MemoryStorage()
    _seed_job(storage)
    before = set(storage.objects)
    _real_combined_midi(monkeypatch)
    monkeypatch.setattr(timing_export, "build_timing", lambda **kw: {"events": [{"x": 1}], "bars": []})
    result = replace(_result(), timing_inputs={"bpm": 100, "events": {"Soprano": [{"type": "note"}]}})
    process_one(storage=storage, runner=_runner(result), settings=settings)
    with db.transaction() as conn:
        job = conn.execute("SELECT status, failure_reason FROM jobs").fetchone()
        assert conn.execute("SELECT count(*) AS n FROM scores").fetchone()["n"] == 0
    assert job["status"] == "failed" and job["failure_reason"] == NO_PLAYBACK_FAILURE_REASON
    assert set(storage.objects) == before


def test_timing_disabled_uploads_empty_timing(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    _seed_job(storage)
    result = replace(_result(), timing_inputs={"bpm": 100})
    process_one(storage=storage, runner=_runner(result), settings=replace(settings, timing_enabled=False))
    with db.transaction() as conn:
        key = conn.execute("SELECT metadata_key FROM timing_metadata").fetchone()["metadata_key"]
    assert storage.get(key) == b'{"events": []}'


def test_health_endpoint_answers_ok() -> None:
    thread = health.serve(0)
    with urllib.request.urlopen(f"http://127.0.0.1:{thread.port}/health", timeout=5) as resp:  # type: ignore[attr-defined]
        assert resp.status == 200 and resp.read() == b"ok"


def test_timing_failure_never_fails_the_job(app: Flask, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import timing_export

    def boom(**kwargs: Any) -> dict[str, Any]:
        raise KeyError("bad geometry")

    monkeypatch.setattr(timing_export, "build_timing", boom)
    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    process_one(storage=storage, runner=_runner(replace(_result(), timing_inputs={"bpm": 100})), settings=settings)
    with db.transaction() as conn:
        key = conn.execute("SELECT metadata_key FROM timing_metadata").fetchone()["metadata_key"]
    assert _job(job_id)["status"] == "complete" and storage.get(key) == b'{"events": []}'


def test_heartbeat_reconnects_after_transient_failure(app: Flask) -> None:
    import threading

    import psycopg

    from backend.worker.main import _heartbeat

    executed = threading.Event()
    attempts: list[int] = []

    class FakeConn:
        def execute(self, *args: Any) -> None:
            executed.set()

        def close(self) -> None:
            pass

    def connect(url: str, **kwargs: Any) -> FakeConn:
        assert kwargs["prepare_threshold"] is None
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.OperationalError("down")
        return FakeConn()

    stop = threading.Event()
    thread = threading.Thread(target=_heartbeat, args=("x", 1, 0.01, stop, connect))
    thread.start()
    assert executed.wait(5)
    stop.set()
    thread.join(5)
    assert not thread.is_alive() and len(attempts) == 2


def test_smoke_db_guard_accepts_only_the_local_test_database() -> None:
    from backend.scripts.smoke_convert import check_test_db

    check_test_db("postgresql://localhost:55432/piya_test")
    check_test_db("postgresql://127.0.0.1:55432/piya_test")
    for bad in ("postgresql://localhost.evil.net:55432/piya_test", "postgresql://localhost:5432/piya_test",
                "postgresql://localhost:55432/piya", "postgresql://localhost:55432/piya_test_x",
                "postgresql://evil.net/x?host=localhost:55432/piya_test",
                "postgresql://localhost:55432/piya_test?dbname=prod", "postgresql://localhost:55432/piya_test?host=evil.net",
                "postgresql://localhost:55432/piya_test?port=5432", "postgresql://localhost:abc/piya_test",
                "postgresql://localhost:55432/piya_test#?host=evil.net", "postgresql://localhost:55432/piya_test#x",
                "postgresql://localhost:55432/piya_test ", "postgresql://localhost:55432/piya_test\nhost=evil.net",
                "mysql://localhost:55432/piya_test", "http://localhost:55432/piya_test"):
        with pytest.raises(SystemExit):
            check_test_db(bad)


def test_timing_scaled_to_served_page_and_missing_size_is_safe() -> None:
    from backend.worker.main import _scale_to_served_pages

    event = {"pageIndex": 0, "x": 100.0, "y": 200.0, "systemTopY": 160.0, "systemBottomY": 240.0, "tick": 0}
    other = {"pageIndex": 1, "x": 100.0, "y": 200.0}
    timing = {"events": [dict(event), dict(other)]}
    result = replace(_result(pages=2), pages=[CleanPage(_jpeg(), 1500, 2400), CleanPage(_jpeg(), 1500, 2400)],
                     timing_inputs={"page_sizes": [(800, 1600), (0, 1600)]})
    _scale_to_served_pages(timing, result)
    assert timing["events"][0] == {**event, "x": 187.5, "y": 300.0, "systemTopY": 240.0, "systemBottomY": 360.0}  # sx 1.875, sy 1.5
    assert timing["events"][1] == other  # zero detection width: left unscaled, no crash
    _scale_to_served_pages({"events": [dict(event)]}, replace(result, timing_inputs={}))  # no sizes at all

    bar = {"bar": 1, "pageIndex": 0, "x": 100.0, "systemTopY": 160.0, "systemBottomY": 240.0}
    bar_other = {"bar": 2, "pageIndex": 1, "x": 100.0}
    timing = {"events": [], "bars": [dict(bar), dict(bar_other)]}
    _scale_to_served_pages(timing, result)
    assert timing["bars"][0] == {**bar, "x": 187.5, "systemTopY": 240.0, "systemBottomY": 360.0}
    assert timing["bars"][1] == bar_other  # zero detection width: unscaled
    _scale_to_served_pages({"events": []}, result)  # no bars key


def test_progress_writer_throttles_and_only_rises() -> None:
    from backend.worker.main import make_progress_writer

    now = [0.0]
    written: list[int] = []
    report = make_progress_writer(written.append, clock=lambda: now[0], interval_s=2.0)
    report(10)
    now[0] = 1.0
    report(20)  # inside 2 s: dropped
    now[0] = 2.5
    report(10)  # not a rise: dropped
    report(30)
    now[0] = 5.0
    report(30)  # same value: dropped
    report(31)
    assert written == [10, 30, 31]


def test_progress_writer_swallows_write_errors() -> None:
    from backend.worker.main import make_progress_writer

    def boom(percent: int) -> None:
        raise RuntimeError("db down")

    make_progress_writer(boom)(50)  # must not raise


def test_cancel_noticed_at_progress_write_stops_pipeline_and_logs(
        app: Flask, settings: Settings, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    import functools

    from backend.worker import main as worker_main

    monkeypatch.setattr(worker_main, "make_progress_writer",
                        functools.partial(worker_main.make_progress_writer, clock=lambda: 0.0))
    caplog.set_level("INFO")
    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)

    def run(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool, on_progress: Any = None) -> PipelineResult:
        on_stage("preprocessing", 5)
        with db.transaction() as conn:
            conn.execute("UPDATE jobs SET status = 'cancelled' WHERE id = %s", (job_id,))
        on_progress(17)  # inside a stage: must raise, not wait for the next stage start
        raise AssertionError("pipeline must stop at the progress write after cancel")

    assert process_one(storage=storage, runner=run, settings=settings) is True
    assert f"job cancelled job_id={job_id}" in caplog.text and "job timing" in caplog.text
    assert _job(job_id)["status"] == "cancelled" and set(storage.objects) == set(old_keys)


def test_runner_progress_is_stored_and_job_completes_at_100(
        app: Flask, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import functools

    from backend.worker import main as worker_main

    # Frozen clock: the second on_progress call is always inside the 1 s throttle window.
    monkeypatch.setattr(worker_main, "make_progress_writer",
                        functools.partial(worker_main.make_progress_writer, clock=lambda: 0.0))
    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    seen: list[int] = []

    def run(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool,
            on_progress: Any) -> PipelineResult:
        on_stage("preprocessing", 5)
        on_progress(17)
        seen.append(_job(job_id)["percent_complete"])
        on_stage("detecting_staff", 25)
        on_progress(99)  # callback itself is throttled; this one is inside 1 s so dropped
        seen.append(_job(job_id)["percent_complete"])
        return _result()

    assert process_one(storage=storage, runner=run, settings=settings) is True
    assert seen == [17, 25] and _job(job_id)["percent_complete"] == 100


def test_check_schema_passes_when_applied_and_raises_when_behind(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    with db.transaction() as conn:
        check_schema(conn)
    # Fake the status list instead of deleting a schema_migrations row: no shared state is touched.
    monkeypatch.setattr(migrate, "status", lambda conn: [("0001_x", True), ("0006_y", False)])
    with db.transaction() as conn, pytest.raises(RuntimeError, match="unapplied migrations: 0006_y"):
        check_schema(conn)


def _bars_timing(monkeypatch: pytest.MonkeyPatch) -> PipelineResult:
    import timing_export

    bars = [dict(bar=1, startTick=0, durTicks=1920, numerator=4, denominator=4, pickup=False)]
    ev = {"Soprano": [dict(type="note", pitch=72, tick_onset=0, duration_ticks=480)]}
    monkeypatch.setattr(timing_export, "build_timing", lambda **kw: {"events": [{"x": 1}], "bars": bars})
    _real_combined_midi(monkeypatch)
    return replace(_result(), timing_inputs={"bpm": 100, "events": ev})


def test_combined_midi_builder_error_fails_job(
        app: Flask, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = MemoryStorage()
    _seed_job(storage)
    result = _bars_timing(monkeypatch)

    def boom(*a: Any, **k: Any) -> bytes:
        raise ValueError("bad ticks")

    monkeypatch.setattr(worker_main, "build_combined_midi", boom)
    process_one(storage=storage, runner=_runner(result), settings=settings)
    with db.transaction() as conn:
        job = conn.execute("SELECT status, failure_reason FROM jobs").fetchone()
    assert job["status"] == "failed" and job["failure_reason"] == NO_PLAYBACK_FAILURE_REASON


def test_cancel_during_publish_discards_combined_midi(
        app: Flask, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)
    result = _bars_timing(monkeypatch)

    def late_cancel(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool, on_progress: Any = None) -> PipelineResult:
        on_stage("synthesizing", 92)
        with db.transaction() as conn:
            conn.execute("UPDATE jobs SET status = 'cancelled' WHERE id = %s", (job_id,))
        return result

    process_one(storage=storage, runner=late_cancel, settings=settings)
    assert _count("scores") == 0 and set(storage.objects) == set(old_keys)


def test_midi_only_result_completes_with_null_file_keys(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    assert process_one(storage=storage, runner=_runner(_result(mp3=False)), settings=settings)
    with db.transaction() as conn:
        rows = conn.execute("SELECT file_key, midi_key FROM audio_tracks").fetchall()
    assert len(rows) == 4 and all(r["file_key"] is None and r["midi_key"] for r in rows)


def test_overrun_job_is_failed_and_its_pages_queued_for_deletion(app: Flask, settings: Settings) -> None:
    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status = 'transcribing', started_at = now() - interval '2 hours' WHERE id = %s",
                     (job_id,))
    assert process_one(storage=storage, runner=_runner(), settings=settings) is False  # nothing else queued
    job = _job(job_id)
    assert (job["status"], job["failure_reason"]) == ("failed", "max_runtime_exceeded")
    with db.transaction() as conn:
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions").fetchall()}
    assert queued == set(old_keys)


def test_heartbeat_fails_overrunning_job_and_stops_the_pipeline(app: Flask, settings: Settings) -> None:
    import time
    from dataclasses import replace

    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)
    stopped_by_cancel: list[bool] = []

    def hung(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool, on_progress: Any = None) -> PipelineResult:
        on_stage("preprocessing", 5)
        with db.transaction() as conn:  # pretend the attempt started long ago
            conn.execute("UPDATE jobs SET started_at = now() - interval '1 hour' WHERE id = %s", (job_id,))
        time.sleep(HEARTBEAT_TEST_RUN_S)  # the heartbeat fails the job in the meantime
        try:
            on_stage("detecting_staff", 25)
        except worker_main._Cancelled:
            stopped_by_cancel.append(True)
            raise
        raise AssertionError("pipeline must stop once the heartbeat failed the job")

    process_one(storage=storage, runner=hung, settings=replace(settings, job_max_runtime_s=60),
                heartbeat_interval_s=HEARTBEAT_TEST_INTERVAL_S)
    job = _job(job_id)
    assert (job["status"], job["failure_reason"]) == ("failed", "max_runtime_exceeded")
    assert stopped_by_cancel == [True] and _count("scores") == 0
    with db.transaction() as conn:
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions").fetchall()}
    assert queued == set(old_keys)


def test_heartbeat_exits_worker_when_pipeline_stays_hung_after_overrun(app: Flask) -> None:
    import threading

    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status = 'transcribing', started_at = now() - interval '2 hours' WHERE id = %s",
                     (job_id,))

    class FakeConn:
        def execute(self, *args: Any) -> None:
            pass

        def close(self) -> None:
            pass

    codes: list[int] = []
    stop = threading.Event()  # never set: the pipeline thread is "hung"
    thread = threading.Thread(target=worker_main._heartbeat, args=("x", job_id, 0.01, stop, lambda *a, **k: FakeConn()),
                              kwargs={"max_runtime_s": 60, "exit_grace_s": 0.05, "exit_fn": codes.append})
    thread.start()
    thread.join(10)
    assert codes == [worker_main.HUNG_WORKER_EXIT_CODE] and _job(job_id)["status"] == "failed"


def test_heartbeat_does_not_exit_when_pipeline_finishes_within_grace(app: Flask) -> None:
    import threading

    storage = MemoryStorage()
    job_id, _ = _seed_job(storage)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status = 'transcribing', started_at = now() - interval '2 hours' WHERE id = %s",
                     (job_id,))

    class FakeConn:
        def execute(self, *args: Any) -> None:
            pass

        def close(self) -> None:
            pass

    codes: list[int] = []
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()  # the pipeline notices the failed status and returns
    thread = threading.Thread(target=worker_main._heartbeat, args=("x", job_id, 0.01, stop, lambda *a, **k: FakeConn()),
                              kwargs={"max_runtime_s": 60, "exit_grace_s": 5, "exit_fn": codes.append})
    thread.start()
    thread.join(10)
    assert codes == [] and not thread.is_alive()


def test_heartbeat_overrun_fail_and_page_queue_are_atomic_and_survive_errors(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    import psycopg

    storage = MemoryStorage()
    job_id, old_keys = _seed_job(storage)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status = 'transcribing', started_at = now() - interval '2 hours' WHERE id = %s",
                     (job_id,))
    real = worker_main._queue_page_deletions
    errors: list[Exception] = [psycopg.OperationalError("cutoff"), RuntimeError("boom")]
    statuses: list[str] = []

    def flaky(conn: Any, ids: Any) -> None:
        if errors:
            statuses.append(_job(job_id)["status"])  # other connection: fail must not be visible yet
            raise errors.pop(0)
        real(conn, ids)

    class FakeConn:
        def execute(self, *args: Any) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(worker_main, "_queue_page_deletions", flaky)
    stop = threading.Event()
    thread = threading.Thread(target=worker_main._heartbeat, args=("x", job_id, 0.01, stop, lambda *a, **k: FakeConn()),
                              kwargs={"max_runtime_s": 60, "exit_grace_s": 0.01, "exit_fn": lambda code: None})
    thread.start()
    thread.join(10)  # exits on its own once the third tick fails the job and queues the pages
    stop.set()
    assert not thread.is_alive() and errors == [] and statuses == ["transcribing", "transcribing"]
    assert _job(job_id)["status"] == "failed"
    with db.transaction() as conn:
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions").fetchall()}
    assert queued == set(old_keys)
