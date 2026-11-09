"""Tests for the Postgres-backed window limiter and exponential backoff."""

from __future__ import annotations

import pytest
from flask import Flask

from backend import db, throttle


def test_window_limit(app: Flask, db_clean: None) -> None:
    with db.transaction() as conn:
        assert throttle.window_retry_after(conn, "b", "k", 2, 60) is None
        throttle.record_hit(conn, "b", "k")
        throttle.record_hit(conn, "b", "k")
        wait = throttle.window_retry_after(conn, "b", "k", 2, 60)
        assert wait is not None and 0 < wait <= 60
        assert throttle.window_retry_after(conn, "b", "other", 2, 60) is None
        assert throttle.window_retry_after(conn, "other", "k", 2, 60) is None


def test_window_hits_expire(app: Flask, db_clean: None) -> None:
    with db.transaction() as conn:
        throttle.record_hit(conn, "b", "k")
        conn.execute("UPDATE throttle_hits SET created_at = now() - interval '61 seconds'")
        assert throttle.window_retry_after(conn, "b", "k", 1, 60) is None


def _wait_after_failure(free: int) -> tuple[int, int | None]:
    with db.transaction() as conn:
        n = throttle.record_failure(conn, "s", "k", free_failures=free)
        return n, throttle.backoff_wait(conn, "s", "k")


def test_backoff_sequence_login(app: Flask, db_clean: None) -> None:
    expected = {1: 30, 2: 60, 3: 120}
    for n in range(1, 11):
        got_n, wait = _wait_after_failure(0)
        assert got_n == n
        if n in expected:
            assert wait is not None and expected[n] - 2 <= wait <= expected[n]
    assert wait is not None and 898 <= wait <= 900


def test_backoff_sequence_reset_code(app: Flask, db_clean: None) -> None:
    assert _wait_after_failure(2) == (1, None)
    assert _wait_after_failure(2) == (2, None)
    n3, w3 = _wait_after_failure(2)
    n4, w4 = _wait_after_failure(2)
    assert (n3, n4) == (3, 4)
    assert w3 is not None and 28 <= w3 <= 30
    assert w4 is not None and 58 <= w4 <= 60


def test_backoff_resets_after_24h_idle(app: Flask, db_clean: None) -> None:
    for _ in range(5):
        _wait_after_failure(0)
    with db.transaction() as conn:
        conn.execute("UPDATE throttle_backoff SET last_failure_at = now() - interval '25 hours'")
    assert _wait_after_failure(0)[0] == 1


def test_clear_failures_and_expired_wait(app: Flask, db_clean: None) -> None:
    _wait_after_failure(0)
    with db.transaction() as conn:
        conn.execute("UPDATE throttle_backoff SET wait_until = now() - interval '1 second'")
        assert throttle.backoff_wait(conn, "s", "k") is None
        throttle.clear_failures(conn, "s", "k")
        assert throttle.record_failure(conn, "s", "k", free_failures=0) == 1


def test_too_many() -> None:
    err = throttle.too_many(42)
    assert (err.status, err.code, err.retry_after) == (429, "rate_limited", 42)


def _ladder_failure() -> tuple[int, int | None]:
    with db.transaction() as conn:
        n = throttle.record_failure(conn, "s", "k", ladder=throttle.LOGIN_LADDER)
        return n, throttle.backoff_wait(conn, "s", "k")


def test_ladder_schedule_and_step_down(app: Flask, db_clean: None) -> None:
    waits = [_ladder_failure()[1] for _ in range(10)]
    got = [None if w is None else round(w, -1) for w in waits]
    assert got == [None] * 4 + [30, 60, 90, 120, 150, 3600]
    assert _ladder_failure() == (11, 3600)  # lock still active: counts on, no step-down
    with db.transaction() as conn:
        conn.execute("UPDATE throttle_backoff SET wait_until = now() - interval '1 second'")
    n, wait = _ladder_failure()
    assert n == 5 and wait is not None and 28 <= wait <= 30


def test_record_failure_needs_exactly_one_schedule(app: Flask, db_clean: None) -> None:
    with db.transaction() as conn:
        for kwargs in ({}, {"free_failures": 0, "ladder": throttle.LOGIN_LADDER}):
            with pytest.raises(ValueError):
                throttle.record_failure(conn, "s", "k", **kwargs)
