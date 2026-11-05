"""Job queue core against real Postgres: claim ordering, SKIP LOCKED, heartbeat and reclaim."""

from __future__ import annotations

import threading
from typing import Any

import psycopg
import pytest
from flask import Flask
from psycopg.rows import dict_row

from backend import db
from backend.config import Settings
from backend.worker import queue

_INSERT_JOB = (
    "INSERT INTO jobs (user_id, status, source, page_count, title, tempo_source) "
    "VALUES (%s, %s, 'images', 1, 'T', 'default') RETURNING id"
)


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Truncate tables before every test."""


def _user(conn: Any) -> int:
    row = conn.execute("INSERT INTO users (email, password_hash) VALUES ('a@example.com', 'x') RETURNING id").fetchone()
    return int(row["id"])


def _job(conn: Any, user_id: int, status: str = "queued") -> int:
    return int(conn.execute(_INSERT_JOB, (user_id, status)).fetchone()["id"])


def _row(conn: Any, job_id: int) -> dict[str, Any]:
    return conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()


def _age(conn: Any, job_id: int) -> None:
    conn.execute("UPDATE jobs SET heartbeat_at = now() - interval '1 hour' WHERE id = %s", (job_id,))


def _hold_lock_then_claim(settings: Settings, queued: int) -> tuple[list[dict[str, Any] | None], int]:
    """Lock the oldest row on connection A, then claim on B with a 1s lock_timeout.

    Without SKIP LOCKED, B would block on A's row and raise LockNotAvailable.
    """
    with db.transaction() as conn:
        user = _user(conn)
        first = _job(conn, user)
        for _ in range(queued - 1):
            _job(conn, user)
    with psycopg.connect(settings.database_url, row_factory=dict_row) as a:
        a.execute("SELECT id FROM jobs WHERE id = %s FOR UPDATE", (first,))
        with psycopg.connect(settings.database_url, row_factory=dict_row) as b:
            b.execute("SET lock_timeout = '1s'")
            return [queue.claim_next_job(b)], first


def test_claim_skips_row_locked_by_another_connection(app: Flask, settings: Settings) -> None:
    (claimed,), first = _hold_lock_then_claim(settings, queued=2)
    assert claimed is not None and claimed["id"] != first


def test_two_concurrent_claims_never_return_the_same_job(app: Flask, settings: Settings) -> None:
    (claimed,), _ = _hold_lock_then_claim(settings, queued=1)
    assert claimed is None  # the only job is held by A, so B must not also get it


def test_threaded_claims_with_one_job_have_exactly_one_winner(app: Flask, settings: Settings) -> None:
    with db.transaction() as conn:
        _job(conn, _user(conn))
    results: list[dict[str, Any] | None] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as c:
            barrier.wait(timeout=10)
            results.append(queue.claim_next_job(c))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1


def test_claim_sets_working_state(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        claimed = queue.claim_next_job(conn)
        assert claimed is not None and claimed["id"] == job_id
        assert claimed["status"] == "preprocessing"
        assert claimed["attempts"] == 1
        assert claimed["heartbeat_at"] is not None


def test_claim_skips_cancelled_and_finished(app: Flask) -> None:
    with db.transaction() as conn:
        user = _user(conn)
        for status in ("cancelled", "complete", "failed", "transcribing"):
            _job(conn, user, status)
        assert queue.claim_next_job(conn) is None


def test_claim_orders_oldest_first(app: Flask) -> None:
    with db.transaction() as conn:
        user = _user(conn)
        first = _job(conn, user)
        _job(conn, user)
        claimed = queue.claim_next_job(conn)
        assert claimed is not None and claimed["id"] == first


def test_set_stage_returns_false_when_cancelled(app: Flask) -> None:
    with db.transaction() as conn:
        user = _user(conn)
        working = _job(conn, user, "preprocessing")
        cancelled = _job(conn, user, "cancelled")
        assert queue.set_stage(conn, working, "transcribing", 40, 2) is True
        row = _row(conn, working)
        assert (row["status"], row["percent_complete"], row["current_page"]) == ("transcribing", 40, 2)
        assert queue.set_stage(conn, cancelled, "transcribing", 40, 2) is False
        assert _row(conn, cancelled)["status"] == "cancelled"


def test_progress_never_decreases_even_on_reclaimed_retry(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn), "preprocessing")
        assert queue.set_stage(conn, job_id, "transcribing", 40, None)
        assert queue.set_progress(conn, job_id, 63) and _row(conn, job_id)["percent_complete"] == 63
        assert queue.set_progress(conn, job_id, 50) and _row(conn, job_id)["percent_complete"] == 63
        assert queue.set_stage(conn, job_id, "preprocessing", 5, None)  # retry restarts at stage 1
        row = _row(conn, job_id)
        assert (row["status"], row["percent_complete"]) == ("preprocessing", 63)


def test_set_progress_returns_false_when_cancelled(app: Flask) -> None:
    with db.transaction() as conn:
        assert queue.set_progress(conn, _job(conn, _user(conn), "cancelled"), 50) is False


def test_reclaim_requeues_stale_job(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        queue.claim_next_job(conn)
        _age(conn, job_id)
        assert queue.reclaim_stale(conn, timeout_s=60, max_attempts=2) == (1, 0)
        assert _row(conn, job_id)["status"] == "queued"


def test_reclaim_fails_at_attempt_cap_with_reason(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        queue.claim_next_job(conn)
        conn.execute("UPDATE jobs SET attempts = 2 WHERE id = %s", (job_id,))
        _age(conn, job_id)
        assert queue.reclaim_stale(conn, timeout_s=60, max_attempts=2) == (0, 1)
        row = _row(conn, job_id)
        assert (row["status"], row["failure_reason"]) == ("failed", "worker_timeout")


def test_touch_prevents_reclaim(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        queue.claim_next_job(conn)
        _age(conn, job_id)
        queue.touch(conn, job_id)
        assert queue.reclaim_stale(conn, timeout_s=60, max_attempts=2) == (0, 0)


def test_reclaim_leaves_fresh_queued_and_terminal_jobs_alone(app: Flask) -> None:
    with db.transaction() as conn:
        user = _user(conn)
        fresh = _job(conn, user, "transcribing")
        conn.execute("UPDATE jobs SET heartbeat_at = now() WHERE id = %s", (fresh,))
        others = [_job(conn, user, s) for s in ("queued", "complete", "failed", "cancelled")]
        conn.execute("UPDATE jobs SET heartbeat_at = now() - interval '1 hour' WHERE id <> %s", (fresh,))
        assert queue.reclaim_stale(conn, timeout_s=60, max_attempts=2) == (0, 0)
        assert _row(conn, fresh)["status"] == "transcribing"
        assert [_row(conn, j)["status"] for j in others] == ["queued", "complete", "failed", "cancelled"]


def test_reclaim_requeues_below_attempt_cap(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn), "transcribing")
        conn.execute("UPDATE jobs SET attempts = 1 WHERE id = %s", (job_id,))
        _age(conn, job_id)
        assert queue.reclaim_stale(conn, timeout_s=60, max_attempts=2) == (1, 0)


def test_null_heartbeat_falls_back_to_updated_at(app: Flask) -> None:
    with db.transaction() as conn:
        # Inserted directly: the jobs trigger would reset updated_at on any UPDATE.
        job_id = conn.execute(
            "INSERT INTO jobs (user_id, status, source, page_count, title, tempo_source, updated_at) "
            "VALUES (%s, 'transcribing', 'images', 1, 'T', 'default', now() - interval '1 hour') RETURNING id",
            (_user(conn),),
        ).fetchone()["id"]
        assert queue.reclaim_stale(conn, timeout_s=60, max_attempts=2) == (1, 0)
        assert _row(conn, job_id)["status"] == "queued"


def test_claim_reclaim_claim_reaches_attempt_two(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        queue.claim_next_job(conn)
        _age(conn, job_id)
        queue.reclaim_stale(conn, timeout_s=60, max_attempts=2)
        again = queue.claim_next_job(conn)
        assert again is not None and again["attempts"] == 2
