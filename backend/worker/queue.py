"""Postgres-backed job queue for the conversion worker.

All functions run inside the caller's transaction so a claim and its follow-up writes commit or
roll back together.
"""

from __future__ import annotations

from typing import Any

import psycopg

STALE_TIMEOUT_S = 1200  # longest plausible single conversion before the worker is presumed dead
MAX_ATTEMPTS = 2
HEARTBEAT_INTERVAL_S = 60

_WORKING_STATUSES = ("preprocessing", "detecting_staff", "transcribing", "reconstructing", "synthesizing")
_Conn = psycopg.Connection[dict[str, Any]]


def claim_next_job(conn: _Conn) -> dict[str, Any] | None:
    """Claim the oldest queued job; SKIP LOCKED lets concurrent workers pass over a held row.

    Heartbeat uses clock_timestamp(), not the transaction start, so commit promptly after claiming.
    A race can return None while other queued jobs exist; the worker just polls again.
    """
    return conn.execute(
        "UPDATE jobs SET status = 'preprocessing', attempts = attempts + 1, heartbeat_at = clock_timestamp(), "
        "updated_at = now() WHERE id = (SELECT id FROM jobs WHERE status = 'queued' "
        "ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *"
    ).fetchone()


def touch(conn: _Conn, job_id: int) -> None:
    """Record liveness so reclaim_stale leaves a long-running job alone.

    Run in its own short committed transaction: now() would freeze at the start of a long one.
    """
    conn.execute("UPDATE jobs SET heartbeat_at = clock_timestamp(), updated_at = clock_timestamp() WHERE id = %s", (job_id,))


def set_stage(conn: _Conn, job_id: int, status: str, percent: int, current_page: int | None) -> bool:
    """Advance a job's stage; False means it left the working statuses (e.g. user cancelled).

    Run in a short committed transaction so the clock_timestamp() heartbeat is visible promptly.
    """
    cur = conn.execute(
        "UPDATE jobs SET status = %s, percent_complete = %s, current_page = %s, heartbeat_at = clock_timestamp(), "
        "updated_at = clock_timestamp() WHERE id = %s AND status = ANY(%s)",
        (status, percent, current_page, job_id, list(_WORKING_STATUSES)),
    )
    return cur.rowcount == 1


def reclaim_stale(conn: _Conn, *, timeout_s: int, max_attempts: int) -> tuple[int, int]:
    """Requeue working jobs with a dead heartbeat, or fail them once attempts are used up.

    Returns:
        (requeued, failed) counts.
    """
    rows = conn.execute(
        "UPDATE jobs SET status = CASE WHEN attempts >= %s THEN 'failed' ELSE 'queued' END, "
        "failure_reason = CASE WHEN attempts >= %s THEN 'worker_timeout' ELSE failure_reason END, "
        "updated_at = now() WHERE status = ANY(%s) AND COALESCE(heartbeat_at, updated_at) < now() - make_interval(secs => %s) "
        "RETURNING status",
        (max_attempts, max_attempts, list(_WORKING_STATUSES), timeout_s),
    ).fetchall()
    failed = sum(1 for r in rows if r["status"] == "failed")
    return len(rows) - failed, failed
