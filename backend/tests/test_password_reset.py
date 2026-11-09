"""Tests for emailed-code password reset (PIYA-303, PIYA-304, V2 B3/B4) and the mailers."""

from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.request
from typing import Any

import pytest
from flask import Flask, g, jsonify
from flask.testing import FlaskClient

from backend import db, mailer, security
from backend.mailer import BrevoMailer, MailError, MemoryMailer

PASSWORD = "Secret123zz"
NEW_PASSWORD = "Brandnew456yy"
EMAIL = "a@example.com"
RESET_IP_LIMIT = 30


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


@pytest.fixture
def mail(app: Flask) -> MemoryMailer:
    m = app.extensions["mailer"]
    assert isinstance(m, MemoryMailer)
    return m


def _signup(client: FlaskClient, email: str = EMAIL) -> str:
    res = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "passwordConfirmation": PASSWORD},
    )
    assert res.status_code == 201
    token: str = res.get_json()["data"]["sessionToken"]
    return token


def _request(client: FlaskClient, email: str = EMAIL, ip: str = "10.0.0.1") -> Any:
    return client.post(
        "/api/auth/password-reset/request",
        json={"email": email},
        environ_overrides={"REMOTE_ADDR": ip},
    )


def _confirm(
    client: FlaskClient,
    code: str,
    password: str = NEW_PASSWORD,
    confirmation: str | None = None,
    email: str = EMAIL,
    ip: str = "10.0.0.1",
) -> Any:
    return client.post(
        "/api/auth/password-reset/confirm",
        json={
            "email": email,
            "resetToken": code,
            "newPassword": password,
            "newPasswordConfirmation": password if confirmation is None else confirmation,
        },
        environ_overrides={"REMOTE_ADDR": ip},
    )


def _verify(client: FlaskClient, code: str, email: str = EMAIL, ip: str = "10.0.0.1") -> Any:
    return client.post(
        "/api/auth/password-reset/verify",
        json={"email": email, "code": code},
        environ_overrides={"REMOTE_ADDR": ip},
    )


def _skip_wait() -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE throttle_backoff SET wait_until = now() - interval '1 second'")


def _count(bucket: str) -> int:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM throttle_hits WHERE bucket = %s", (bucket,)
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _failures() -> int:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT coalesce(max(failures), 0) AS n FROM throttle_backoff WHERE scope = 'reset_code'"
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _live_rows() -> int:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM password_reset_tokens WHERE used_at IS NULL"
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def _ip_key(app: Flask, ip: str) -> str:
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": ip}):
        return security.keyed_hash(security.client_ip())


def test_reset_request_registered_sends_code(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    res = _request(client)
    assert res.status_code == 200
    body = res.get_json()
    assert body["message"] == "If this email is registered, a reset link has been sent"
    assert body["data"] is None
    assert len(mail.sent) == 1
    to, code = mail.sent[0]
    assert to == EMAIL and re.fullmatch(r"\d{6}", code)
    with db.transaction() as conn:
        row = conn.execute("SELECT token_hash FROM password_reset_tokens").fetchone()
    assert row is not None
    assert bytes(row["token_hash"]) != code.encode()
    assert len(bytes(row["token_hash"])) == 32


def test_reset_request_unregistered_404_no_mail(client: FlaskClient, mail: MemoryMailer) -> None:
    res = _request(client, "nobody@example.com")
    assert res.status_code == 404
    assert res.get_json()["error"]["code"] == "email_not_registered"
    assert mail.sent == []


def test_reset_request_bad_email_400(client: FlaskClient) -> None:
    assert _request(client, "not-an-email").get_json()["error"]["code"] == "invalid_email"
    res = client.post("/api/auth/password-reset/request", json={})
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "missing_field"


def test_reset_request_deleted_user_is_unregistered(
    client: FlaskClient, mail: MemoryMailer
) -> None:
    _signup(client)
    with db.transaction() as conn:
        conn.execute("UPDATE users SET deleted_at = now()")
    assert _request(client).status_code == 404
    assert mail.sent == []


def test_reset_request_rate_limited_before_lookup(client: FlaskClient) -> None:
    for _ in range(5):
        assert _request(client, "nobody@example.com").status_code == 404
    res = _request(client, "nobody@example.com")
    assert res.status_code == 429
    assert res.headers["Retry-After"]


def test_reset_request_429_not_counted(client: FlaskClient) -> None:
    for _ in range(5):
        assert _request(client, "nobody@example.com").status_code == 404
    for _ in range(3):
        assert _request(client, "nobody@example.com").status_code == 429
    with db.transaction() as conn:
        n = conn.execute("SELECT count(*) AS n FROM throttle_hits").fetchone()
        assert n is not None and n["n"] == 10  # 5 email + 5 ip, none for the 429s
        conn.execute("UPDATE throttle_hits SET created_at = now() - interval '2 hours'")
    assert _request(client, "nobody@example.com").status_code == 404


def test_reset_confirm_hashes_only_on_success(
    client: FlaskClient, mail: MemoryMailer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    calls: list[int] = []
    real = security.hash_password
    monkeypatch.setattr(
        security, "hash_password", lambda pw: (calls.append(1), real(pw))[1]
    )
    assert _confirm(client, "x@x", email="nobody@example.com").status_code == 410
    for _ in range(5):
        assert _confirm(client, _wrong(code)).status_code == 400
    assert _confirm(client, code).status_code == 429
    assert calls == []
    with db.transaction() as conn:
        conn.execute("UPDATE throttle_backoff SET wait_until = now() - interval '1 second'")
    assert _confirm(client, code).status_code == 200
    assert calls == [1]


def test_reset_request_ip_limit(client: FlaskClient) -> None:
    for i in range(20):
        assert _request(client, f"u{i}@example.com").status_code == 404
    assert _request(client, "other@example.com").status_code == 429


def test_new_code_invalidates_old(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    _request(client)
    first, second = mail.sent[0][1], mail.sent[1][1]
    assert _live_rows() == 1
    if first != second:  # 1-in-10^6 collision would make the old code valid again
        res = _confirm(client, first)
        assert res.status_code == 400
        assert res.get_json()["error"]["code"] == "reset_code_invalid"
    assert _confirm(client, second).status_code == 200


def test_confirm_success_revokes_sessions(
    client: FlaskClient, app: Flask, mail: MemoryMailer
) -> None:
    @app.get("/_probe")
    @security.require_auth
    def probe() -> Any:
        return jsonify({"id": g.user.id})

    token = _signup(client)
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/_probe", headers=auth).status_code == 200
    _request(client)
    res = _confirm(client, mail.sent[0][1])
    assert res.status_code == 200
    assert res.get_json()["message"] == "Password reset successful"
    assert res.get_json()["data"] is None
    assert client.get("/_probe", headers=auth).status_code == 401
    login = client.post("/api/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD})
    assert login.status_code == 200


def test_confirm_clears_login_backoff(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    for _ in range(5):
        client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong-pass-1"})
    blocked = client.post("/api/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD})
    assert blocked.status_code == 429
    _request(client)
    assert _confirm(client, mail.sent[0][1]).status_code == 200
    ok = client.post("/api/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD})
    assert ok.status_code == 200


def test_confirm_expired_410(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    with db.transaction() as conn:
        conn.execute("UPDATE password_reset_tokens SET expires_at = now() - interval '1 minute'")
    res = _confirm(client, mail.sent[0][1])
    assert res.status_code == 410
    assert res.get_json()["error"]["code"] == "reset_token_expired_or_invalid"


def test_confirm_used_410(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    assert _confirm(client, code).status_code == 200
    assert _confirm(client, code, password="Another789xx").status_code == 410


def test_confirm_unregistered_and_deleted_410(client: FlaskClient, mail: MemoryMailer) -> None:
    assert _confirm(client, "123456", email="nobody@example.com").status_code == 410
    _signup(client)
    _request(client)
    with db.transaction() as conn:
        conn.execute("UPDATE users SET deleted_at = now()")
    assert _confirm(client, mail.sent[0][1]).status_code == 410


def test_confirm_missing_field_400(client: FlaskClient) -> None:
    res = client.post("/api/auth/password-reset/confirm", json={"email": EMAIL})
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "missing_field"


def test_wrong_code_backoff(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    for _ in range(4):
        res = _confirm(client, _wrong(code))
        assert res.status_code == 400
        assert res.get_json()["error"]["code"] == "reset_code_invalid"
        assert "Retry-After" not in res.headers
    res = _confirm(client, _wrong(code))
    assert res.status_code == 400
    assert res.get_json()["error"]["retryAfterSeconds"] == 30
    assert int(res.headers["Retry-After"]) == 30
    res = _confirm(client, code)
    assert res.status_code == 429
    assert 25 <= int(res.headers["Retry-After"]) <= 30


def test_confirm_ip_limit_counts_wrong_codes_only(
    client: FlaskClient, app: Flask, mail: MemoryMailer
) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO throttle_hits (bucket, subject_key) "
            "SELECT 'reset_code_ip', %s FROM generate_series(1, %s)",
            (_ip_key(app, "10.0.0.1"), RESET_IP_LIMIT),
        )
    assert _confirm(client, code).status_code == 429
    assert _confirm(client, code, ip="10.0.0.2").status_code == 200


def test_weak_password_does_not_consume_code(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    for _ in range(4):
        res = _confirm(client, code, password="short")
        assert res.status_code == 400 and res.get_json()["error"]["code"] == "weak_password"
    res = _confirm(client, code, confirmation="Different999zz")
    assert res.get_json()["error"]["code"] == "password_mismatch"
    assert _confirm(client, code).status_code == 200


def test_mail_failure_rolls_back(client: FlaskClient, app: Flask) -> None:
    class Failing:
        def send_reset_code(self, to: str, code: str) -> None:
            raise MailError("boom")

    _signup(client)
    app.extensions["mailer"] = Failing()
    res = _request(client)
    assert res.status_code == 500
    assert res.get_json()["error"]["code"] == "internal_error"
    assert _live_rows() == 0


def test_brevo_mailer_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Resp:
        status = 201

        def __enter__(self) -> "Resp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(req: urllib.request.Request, timeout: float) -> Resp:
        seen.update(
            url=req.full_url, headers=dict(req.header_items()), body=req.data, timeout=timeout
        )
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    BrevoMailer("key-1", "from@x.org", "PiyaNota", 30).send_reset_code("to@x.org", "123456")
    assert seen["url"] == "https://api.brevo.com/v3/smtp/email"
    assert seen["headers"]["Api-key"] == "key-1"
    assert seen["timeout"] == 10
    body = json.loads(seen["body"])
    assert body["sender"] == {"email": "from@x.org", "name": "PiyaNota"}
    assert body["to"] == [{"email": "to@x.org"}]
    assert body["subject"] == "Your PiyaNota reset code"
    assert "123456" in body["textContent"] and "30 minutes" in body["textContent"]


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.HTTPError("u", 401, "bad to@x.org", {}, io.BytesIO(b"")),  # type: ignore[arg-type]
        urllib.error.URLError("cannot reach to@x.org"),
    ],
)
def test_brevo_mailer_failure_raises_mailerror(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    def boom(req: urllib.request.Request, timeout: float) -> None:
        raise exc

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(MailError) as info:
        BrevoMailer("k", "f@x.org", "P", 30).send_reset_code("to@x.org", "123456")
    assert "to@x.org" not in str(info.value)


def test_get_mailer_returns_app_mailer(app: Flask, mail: MemoryMailer) -> None:
    with app.app_context():
        assert mailer.get_mailer() is mail


def test_verify_wrong_code_400_counts_once_and_keeps_code_live(
    client: FlaskClient, mail: MemoryMailer
) -> None:
    _signup(client)
    _request(client)
    res = _verify(client, _wrong(mail.sent[0][1]))
    assert res.status_code == 400
    err = res.get_json()["error"]
    assert err["code"] == "reset_code_invalid" and err["field"] == "resetToken"
    assert _failures() == 1 and _live_rows() == 1


def test_verify_right_code_then_confirm_same_code(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    _verify(client, _wrong(code))
    res = _verify(client, code)
    assert res.status_code == 200
    assert 1 <= res.get_json()["data"]["expiresInSeconds"] <= 1800
    assert _live_rows() == 1 and _failures() == 1  # not consumed, count not cleared
    assert _confirm(client, code).status_code == 200


def test_verify_and_confirm_share_one_counter(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    for i in range(4):
        assert (_verify if i % 2 else _confirm)(client, _wrong(code)).status_code == 400
    assert _failures() == 4
    res = _verify(client, _wrong(code))
    assert res.status_code == 400
    assert res.get_json()["error"]["retryAfterSeconds"] == 30
    assert _verify(client, code).status_code == 429
    assert _confirm(client, code).status_code == 429


def test_verify_no_live_code_410(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    res = _verify(client, "123456")
    assert res.status_code == 410
    assert res.get_json()["error"]["code"] == "reset_token_expired_or_invalid"
    _request(client)
    with db.transaction() as conn:
        conn.execute("UPDATE password_reset_tokens SET expires_at = now() - interval '1 minute'")
    assert _verify(client, mail.sent[0][1]).status_code == 410
    assert _failures() == 0


def test_verify_unknown_email_410_records_ip_hit(client: FlaskClient) -> None:
    assert _verify(client, "123456", email="nobody@example.com").status_code == 410
    assert _count("reset_code_ip") == 1
    assert _count("reset_code_email") == 0


def test_confirm_410_records_no_ip_hit(client: FlaskClient) -> None:
    assert _confirm(client, "123456", email="nobody@example.com").status_code == 410
    assert _count("reset_code_ip") == 0


def test_request_resets_counter_not_hourly_window(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    for _ in range(3):
        _verify(client, _wrong(mail.sent[0][1]))
    assert _failures() == 3
    _request(client)
    assert _failures() == 0
    assert _count("reset_code_email") == 3


def test_hourly_email_window_blocks_11th_wrong(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    for _ in range(10):
        _skip_wait()
        assert _verify(client, _wrong(code)).status_code == 400
    _skip_wait()
    res = _verify(client, _wrong(code))
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0
    assert _verify(client, code).status_code == 429  # even the right code is blocked


def test_confirm_with_superseded_code_is_counted_400(
    client: FlaskClient, mail: MemoryMailer
) -> None:
    _signup(client)
    _request(client)
    _request(client)
    first, second = mail.sent[0][1], mail.sent[1][1]
    if first == second:
        pytest.skip("1-in-10^6 code collision")
    res = _confirm(client, first)
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "reset_code_invalid"
    assert _failures() == 1
    assert _confirm(client, second).status_code == 200
    # Sequential only: the /request-vs-confirm advisory-lock race itself is not exercised.


def test_failed_mail_send_keeps_failure_count(client: FlaskClient, app: Flask) -> None:
    class Failing:
        def send_reset_code(self, to: str, code: str) -> None:
            raise MailError("boom")

    _signup(client)
    assert _request(client).status_code == 200
    code = app.extensions["mailer"].sent[0][1]
    for _ in range(2):
        assert _verify(client, _wrong(code)).status_code == 400
    app.extensions["mailer"] = Failing()
    assert _request(client).status_code == 500
    assert _failures() == 2
    assert _live_rows() == 1  # the earlier code survives; the new one was rolled back


def test_verify_during_wait_is_429_and_not_counted(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    _request(client)
    code = mail.sent[0][1]
    for _ in range(5):
        _verify(client, _wrong(code))
    ip_hits, email_hits = _count("reset_code_ip"), _count("reset_code_email")
    res = _verify(client, _wrong(code))
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0
    assert _failures() == 5
    assert (_count("reset_code_ip"), _count("reset_code_email")) == (ip_hits, email_hits)
