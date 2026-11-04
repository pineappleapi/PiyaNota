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


def test_two_concurrent_claims_never_return_the_same_job(app: Flask, settings: Settings) -> None:
    with db.transaction() as conn:
        _job(conn, _user(conn))
    results: list[dict[str, Any] | None] = []
    first_claimed = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as c:
            results.append(queue.claim_next_job(c))
            first_claimed.set()
            release.wait(timeout=10)  # keep the row lock while the second claim runs

    thread = threading.Thread(target=holder)
    thread.start()
    assert first_claimed.wait(timeout=10)
    with psycopg.connect(settings.database_url, row_factory=dict_row) as c:
        second = queue.claim_next_job(c)
    release.set()
    thread.join()
    assert second is None
    assert results[0] is not None


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
