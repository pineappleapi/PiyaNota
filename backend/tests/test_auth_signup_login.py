"""Tests for sign-up, login and their throttles (PIYA-301, PIYA-302, V2 B1)."""

from __future__ import annotations

import logging
import threading
from typing import Any

import pytest
from flask import Flask, g, jsonify
from flask.testing import FlaskClient

from dataclasses import replace

from backend import db, security, throttle
from backend.config import SETTINGS_KEY

PASSWORD = "Secret123zz"


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


@pytest.fixture
def probe_client(app: Flask) -> FlaskClient:
    @app.get("/_probe")
    @security.require_auth
    def probe() -> Any:
        return jsonify({"id": g.user.id})

    return app.test_client()


def _signup(client: FlaskClient, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "email": "a@example.com",
        "password": PASSWORD,
        "passwordConfirmation": PASSWORD,
    }
    body.update(overrides)
    return client.post("/api/auth/signup", json={k: v for k, v in body.items() if v is not None})


def _login(
    client: FlaskClient,
    email: str = "a@example.com",
    password: str = PASSWORD,
    ip: str = "10.0.0.1",
) -> Any:
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        environ_overrides={"REMOTE_ADDR": ip},
    )


def _expire_waits() -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE throttle_backoff SET wait_until = now() - interval '1 second'")


def test_signup_success_shape(probe_client: FlaskClient) -> None:
    res = _signup(probe_client)
    assert res.status_code == 201
    body = res.get_json()
    assert body["message"] == "Account created"
    data = body["data"]
    assert set(data) == {"userId", "email", "role", "sessionToken", "expiresAt"}
    assert isinstance(data["userId"], int)
    assert data["role"] == "choir_member"
    assert data["expiresAt"].endswith("Z")
    probe = probe_client.get("/_probe", headers={"Authorization": f"Bearer {data['sessionToken']}"})
    assert probe.status_code == 200 and probe.get_json()["id"] == data["userId"]


@pytest.mark.parametrize(
    ("overrides", "code", "field"),
    [
        ({"email": None}, "missing_field", "email"),
        ({"password": None}, "missing_field", "password"),
        ({"passwordConfirmation": None}, "missing_field", "passwordConfirmation"),
        ({"passwordConfirmation": "Different123"}, "password_mismatch", "passwordConfirmation"),
        ({"password": "short1", "passwordConfirmation": "short1"}, "weak_password", "password"),
        ({"email": "not-an-email"}, "invalid_email", "email"),
    ],
)
def test_signup_validation_codes(
    client: FlaskClient, overrides: dict[str, Any], code: str, field: str
) -> None:
    res = _signup(client, **overrides)
    assert res.status_code == 400
    error = res.get_json()["error"]
    assert (error["code"], error["field"]) == (code, field)


def test_signup_duplicate_409(client: FlaskClient) -> None:
    assert _signup(client).status_code == 201
    res = _signup(client)
    assert res.status_code == 409
    assert res.get_json()["error"]["code"] == "email_already_registered"


def test_signup_ignores_role_field(client: FlaskClient) -> None:
    assert _signup(client, role="choir_director").status_code == 201
    with db.transaction() as conn:
        row = conn.execute("SELECT role FROM users").fetchone()
    assert row is not None and row["role"] == "choir_member"


def test_concurrent_signup_one_wins(app: Flask) -> None:
    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def worker() -> None:
        local = app.test_client()
        barrier.wait()
        statuses.append(_signup(local).status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [201, 409]


def test_signup_ip_limit(app: Flask, client: FlaskClient) -> None:
    limit = 3
    app.config[SETTINGS_KEY] = replace(app.config[SETTINGS_KEY], signup_ip_limit=limit)
    for i in range(limit):
        assert _signup(client, email=f"u{i}@example.com").status_code == 201
    res = _signup(client, email="u11@example.com")
    assert res.status_code == 429
    assert res.get_json()["error"]["code"] == "rate_limited"
    assert int(res.headers["Retry-After"]) > 0


def test_email_normalized_across_signup_and_login(client: FlaskClient) -> None:
    assert _signup(client, email="  Mixed@Example.COM ").status_code == 201
    res = _login(client, email="MIXED@example.com")
    assert res.status_code == 200
    assert res.get_json()["data"]["email"] == "mixed@example.com"


def test_login_success_shape(client: FlaskClient) -> None:
    _signup(client)
    res = _login(client)
    assert res.status_code == 200
    body = res.get_json()
    assert body["message"] == "Login successful"
    assert set(body["data"]) == {"userId", "email", "role", "sessionToken", "expiresAt"}


def test_login_missing_field(client: FlaskClient) -> None:
    res = client.post("/api/auth/login", json={"email": "a@example.com"})
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "missing_field"


def test_login_generic_401(client: FlaskClient) -> None:
    _signup(client)
    wrong = _login(client, password="Wrong12345")
    unknown = _login(client, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json()["message"] == "Incorrect email or password"
    assert wrong.data == unknown.data


def _wrong(client: FlaskClient, email: str = "a@example.com", ip: str = "10.0.0.1") -> Any:
    return _login(client, email=email, password="Wrong12345", ip=ip)


def _shift_clock(seconds: int) -> None:
    """Move the stored failure clock back, which is how the DB-side now() 'advances'."""
    with db.transaction() as conn:
        conn.execute(
            "UPDATE throttle_backoff SET last_failure_at = last_failure_at - make_interval(secs => %s), "
            "wait_until = wait_until - make_interval(secs => %s)",
            (seconds, seconds),
        )


def _state() -> Any:
    with db.transaction() as conn:
        return conn.execute("SELECT failures, last_failure_at FROM throttle_backoff").fetchone()


def _fail_to(client: FlaskClient, n: int) -> Any:
    """Make n wrong logins, skipping the waits; returns the last response."""
    res = None
    for _ in range(n):
        _expire_waits()
        res = _wrong(client)
    return res


def test_login_attempts_remaining_then_wait(client: FlaskClient) -> None:
    _signup(client)
    for expected in (4, 3, 2, 1):
        res = _wrong(client)
        assert res.status_code == 401
        error = res.get_json()["error"]
        assert error["attemptsRemaining"] == expected and "retryAfterSeconds" not in error
        assert "Retry-After" not in res.headers
    res = _wrong(client)
    error = res.get_json()["error"]
    assert res.status_code == 401 and "attemptsRemaining" not in error
    assert error["retryAfterSeconds"] == 30 and res.headers["Retry-After"] == "30"
    assert _wrong(client).status_code == 429


def test_login_ladder_waits(client: FlaskClient) -> None:
    _signup(client)
    _fail_to(client, 4)
    for expected in (30, 60, 90, 120, 150, 3600):
        _expire_waits()
        res = _wrong(client)
        assert res.status_code == 401
        assert res.get_json()["error"]["retryAfterSeconds"] == expected
        assert res.headers["Retry-After"] == str(expected)


def test_login_step_down_after_lock(client: FlaskClient) -> None:
    _signup(client)
    _fail_to(client, 10)
    assert _login(client).status_code == 429
    _expire_waits()
    res = _wrong(client)
    assert res.status_code == 401 and res.get_json()["error"]["retryAfterSeconds"] == 30
    assert _state()["failures"] == 5


def test_login_correct_password_during_wait_is_429_and_keeps_count(client: FlaskClient) -> None:
    _signup(client)
    _fail_to(client, 10)
    before = _state()
    res = _login(client)
    assert res.status_code == 429 and 3590 <= int(res.headers["Retry-After"]) <= 3600
    assert _wrong(client).status_code == 429
    after = _state()
    assert after["failures"] == before["failures"] == 10
    assert after["last_failure_at"] == before["last_failure_at"]


def test_login_success_after_wait_clears_count(client: FlaskClient) -> None:
    _signup(client)
    _fail_to(client, 7)
    _expire_waits()
    assert _login(client).status_code == 200
    assert _state() is None
    assert _wrong(client).get_json()["error"]["attemptsRemaining"] == 4


def test_login_idle_24h_clears_count(client: FlaskClient) -> None:
    _signup(client)
    _fail_to(client, 7)
    _shift_clock(25 * 3600)
    assert _wrong(client).get_json()["error"]["attemptsRemaining"] == 4


def test_login_other_email_independent(client: FlaskClient) -> None:
    _signup(client)
    _fail_to(client, 5)
    assert _wrong(client).status_code == 429
    res = _wrong(client, email="b@example.com", ip="10.0.0.2")
    assert res.status_code == 401 and res.get_json()["error"]["attemptsRemaining"] == 4


def test_lock_shorter_than_idle_reset() -> None:
    from backend import background

    assert throttle.LOGIN_LADDER.lock_s < 24 * 3600
    assert background.BACKOFF_IDLE_S >= 24 * 3600


def test_login_unknown_email_counts_like_known(client: FlaskClient) -> None:
    res = _login(client, email="ghost@example.com")
    assert res.status_code == 401 and res.get_json()["error"]["attemptsRemaining"] == 4
    for _ in range(3):
        _login(client, email="ghost@example.com")
    assert _login(client, email="ghost@example.com").get_json()["error"]["retryAfterSeconds"] == 30


def test_login_429_logs_keys_only(client: FlaskClient, caplog: pytest.LogCaptureFixture) -> None:
    _signup(client)
    _fail_to(client, 5)
    with caplog.at_level(logging.INFO, logger="backend.routes_auth"):
        assert _login(client).status_code == 429
    text = caplog.text
    assert "login throttled" in text and "retry_after=" in text
    assert "a@example.com" not in text and PASSWORD not in text


def test_login_ip_limit(client: FlaskClient) -> None:
    for i in range(30):
        assert _login(client, email=f"u{i}@example.com").status_code == 401
    assert _login(client, email="u31@example.com").status_code == 429


def test_login_rehashes_outdated_hash(client: FlaskClient, app: Flask) -> None:
    _signup(client)
    with app.app_context():
        stale = security.PasswordHasher(time_cost=1, memory_cost=16, parallelism=1).hash(PASSWORD)
        assert security.needs_rehash(stale) is True
    with db.transaction() as conn:
        conn.execute("UPDATE users SET password_hash = %s", (stale,))
    assert _login(client).status_code == 200
    with db.transaction() as conn:
        row = conn.execute("SELECT password_hash FROM users").fetchone()
    assert row is not None and row["password_hash"] != stale
    with app.app_context():
        assert security.verify_password(PASSWORD, row["password_hash"])
        assert security.needs_rehash(row["password_hash"]) is False


def test_lock_subject_smoke_runs_without_error(app: Flask) -> None:
    with db.transaction() as conn:
        throttle.lock_subject(conn, "bucket", "key")


def test_password_never_logged(client: FlaskClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        _signup(client)
        _login(client, password=PASSWORD + "x")
    assert PASSWORD not in caplog.text
    assert PASSWORD + "x" not in caplog.text
    assert "a@example.com" not in caplog.text


def test_overlong_password_runs_one_argon2_call(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _signup(client)
    calls: list[str] = []
    monkeypatch.setattr(security, "verify_dummy", lambda: calls.append("dummy"))
    monkeypatch.setattr(security, "verify_password", lambda p, s: calls.append("verify") or False)
    res = _login(client, password="a1" * 513)
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "invalid_credentials"
    assert len(calls) == 1
    with db.transaction() as conn:
        row = conn.execute("SELECT failures FROM throttle_backoff").fetchone()
    assert row is not None and row["failures"] == 1
