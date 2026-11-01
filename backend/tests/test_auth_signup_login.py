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


def test_login_backoff_429(client: FlaskClient) -> None:
    _signup(client)
    assert _login(client, password="Wrong12345").status_code == 401
    res = _login(client)
    assert res.status_code == 429
    error = res.get_json()["error"]
    assert error["code"] == "rate_limited" and isinstance(error["retryAfterSeconds"], int)
    assert 25 <= int(res.headers["Retry-After"]) <= 30


def test_login_unknown_email_also_backs_off(client: FlaskClient) -> None:
    assert _login(client, email="ghost@example.com").status_code == 401
    assert _login(client, email="ghost@example.com").status_code == 429


def test_login_success_clears_backoff(client: FlaskClient) -> None:
    _signup(client)
    _login(client, password="Wrong12345")
    _expire_waits()
    assert _login(client).status_code == 200
    assert _login(client, password="Wrong12345").status_code == 401
    res = _login(client)
    assert res.status_code == 429 and 25 <= int(res.headers["Retry-After"]) <= 30


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


def test_lock_subject_runs(app: Flask) -> None:
    with db.transaction() as conn:
        throttle.lock_subject(conn, "bucket", "key")


def test_password_never_logged(client: FlaskClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        _signup(client)
        _login(client, password=PASSWORD + "x")
    assert PASSWORD not in caplog.text
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
