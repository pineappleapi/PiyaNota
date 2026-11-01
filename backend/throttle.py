"""Durable (Postgres-backed) rate limits: sliding-window counters and exponential backoff.

Keys are expected to be ``security.keyed_hash`` outputs so no raw email or IP is stored. State
lives in the database, so limits hold across workers and restarts.
"""

from __future__ import annotations

import math
from typing import Any

import psycopg

from backend.envelope import ApiError

Conn = psycopg.Connection[dict[str, Any]]

_BACKOFF_BASE_S = 30
_BACKOFF_MAX_S = 900
_IDLE_RESET_HOURS = 24


def window_retry_after(conn: Conn, bucket: str, key: str, limit: int, window_s: int) -> int | None:
    """Seconds until a slot frees up when ``limit`` hits are already in the window, else None."""
    row = conn.execute(
        "SELECT count(*) AS n, "
        "EXTRACT(EPOCH FROM (min(created_at) + make_interval(secs => %s) - now())) AS wait "
        "FROM throttle_hits WHERE bucket = %s AND subject_key = %s "
        "AND created_at > now() - make_interval(secs => %s)",
        (window_s, bucket, key, window_s),
    ).fetchone()
    if row is None or row["n"] < limit:
        return None
    return max(1, math.ceil(float(row["wait"])))


def record_hit(conn: Conn, bucket: str, key: str) -> None:
    """Count one event against ``bucket``/``key``."""
    conn.execute("INSERT INTO throttle_hits (bucket, subject_key) VALUES (%s, %s)", (bucket, key))


def backoff_wait(conn: Conn, scope: str, key: str) -> int | None:
    """Remaining seconds of an active backoff wait, or None."""
    row = conn.execute(
        "SELECT EXTRACT(EPOCH FROM (wait_until - now())) AS wait FROM throttle_backoff "
        "WHERE scope = %s AND subject_key = %s AND wait_until > now()",
        (scope, key),
    ).fetchone()
    if row is None:
        return None
    return max(1, math.ceil(float(row["wait"])))


def record_failure(conn: Conn, scope: str, key: str, *, free_failures: int) -> int:
    """Record a failed attempt and return the failure count N.

    The count restarts at 1 after 24 h without failures. Once N exceeds ``free_failures`` a wait
    of ``min(900, 30 * 2 ** (N - 1 - free_failures))`` seconds is set.
    """
    row = conn.execute(
        "INSERT INTO throttle_backoff (scope, subject_key, failures, last_failure_at) "
        "VALUES (%s, %s, 1, now()) "
        "ON CONFLICT (scope, subject_key) DO UPDATE SET "
        "failures = CASE WHEN throttle_backoff.last_failure_at < "
        "now() - make_interval(hours => %s) THEN 1 ELSE throttle_backoff.failures + 1 END, "
        "last_failure_at = now(), updated_at = now() RETURNING failures",
        (scope, key, _IDLE_RESET_HOURS),
    ).fetchone()
    if row is None:
        raise RuntimeError("throttle_backoff upsert returned no row")
    failures: int = row["failures"]
    wait_s: int | None = None
    if failures > free_failures:
        wait_s = min(_BACKOFF_MAX_S, _BACKOFF_BASE_S * 2 ** (failures - 1 - free_failures))
    conn.execute(
        "UPDATE throttle_backoff SET wait_until = "
        "CASE WHEN %(w)s::int IS NULL THEN NULL ELSE now() + make_interval(secs => %(w)s::int) END "
        "WHERE scope = %(s)s AND subject_key = %(k)s",
        {"w": wait_s, "s": scope, "k": key},
    )
    return failures


def clear_failures(conn: Conn, scope: str, key: str) -> None:
    """Forget failures after a success."""
    conn.execute("DELETE FROM throttle_backoff WHERE scope = %s AND subject_key = %s", (scope, key))


def too_many(retry_after: int) -> ApiError:
    """The 429 error carrying Retry-After."""
    return ApiError(429, "rate_limited", "Too many requests", retry_after=retry_after)
