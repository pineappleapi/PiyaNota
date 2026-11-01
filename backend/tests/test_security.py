"""Tests for hashing, sessions, require_auth and the email/password validators."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from typing import Any

import pytest
from flask import Flask, g, jsonify
from flask.testing import FlaskClient

from backend import db, security
from backend.config import Settings
from backend.envelope import ApiError
from backend.validation import check_password_policy, normalize_email


@pytest.fixture
def auth_app(app: Flask) -> Flask:
    @app.get("/_whoami")
    @security.require_auth
    def whoami() -> Any:
        return jsonify({"id": g.user.id, "role": g.user.role, "email": g.user.email})

    return app


def _make_user(role: str = "choir_member", email: str = "a@example.com", deleted: bool = False) -> int:
    with db.transaction() as conn:
        row = conn.execute(
            "INSERT INTO users (email, password_hash, role, deleted_at) "
            "VALUES (%s, 'x', %s, CASE WHEN %s THEN now() END) RETURNING id",
            (email, role, deleted),
        ).fetchone()
        assert row is not None
        return int(row["id"])


def _get(client: FlaskClient, token: str | None) -> Any:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    return client.get("/_whoami", headers=headers)


def test_hash_is_salted_and_verifies(app: Flask) -> None:
    with app.app_context():
        h1 = security.hash_password("hunter22")
        h2 = security.hash_password("hunter22")
        assert h1 != h2
        assert h1.startswith("$argon2id$")
        assert security.verify_password("hunter22", h1)
        assert security.verify_password("hunter22", h2)
        assert not security.verify_password("wrong", h1)
        assert not security.verify_password("hunter22", "not-a-hash")
        security.verify_dummy()


def test_hash_long_unicode_password(app: Flask) -> None:
    pw = "pä55wörd🎵" * 20
    with app.app_context():
        assert security.verify_password(pw, security.hash_password(pw))


def test_cost_params_from_settings(app: Flask, settings: Settings) -> None:
    with app.app_context():
        h = security.hash_password("hunter22")
    match = re.search(r"m=(\d+),t=(\d+)", h)
    assert match is not None
    assert int(match.group(1)) == settings.argon2_memory_kib
    assert int(match.group(2)) == settings.argon2_time_cost


def test_session_token_shape_and_storage(app: Flask, db_clean: None) -> None:
    uid = _make_user()
    with app.app_context(), db.transaction() as conn:
        token, expires = security.issue_session(conn, uid)
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert token.startswith("sess_") and len(token) >= 40
    assert expires.tzinfo is not None
    assert [bytes(r["token_hash"]) for r in rows] == [hashlib.sha256(token.encode()).digest()]
    assert token.encode() not in bytes(rows[0]["token_hash"])


def _issue(app: Flask, uid: int) -> str:
    with app.app_context(), db.transaction() as conn:
        return security.issue_session(conn, uid)[0]


def test_require_auth_rejects_all_bad_tokens_identically(
    auth_app: Flask, client: FlaskClient, db_clean: None
) -> None:
    uid = _make_user()
    gone = _make_user(email="gone@example.com", deleted=True)
    expired = _issue(auth_app, uid)
    revoked = _issue(auth_app, uid)
    deleted = _issue(auth_app, gone)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE token_hash = %s",
            (security.token_hash(expired),),
        )
        conn.execute(
            "UPDATE sessions SET revoked_at = now() WHERE token_hash = %s",
            (security.token_hash(revoked),),
        )
    responses = [_get(client, t) for t in (None, "junk", expired, revoked, deleted)]
    assert {r.status_code for r in responses} == {401}
    bodies = {r.get_data() for r in responses}
    assert len(bodies) == 1
    assert _get(client, _issue(auth_app, uid)).status_code == 200


def test_require_auth_ignores_query_string_token(
    auth_app: Flask, client: FlaskClient, db_clean: None
) -> None:
    token = _issue(auth_app, _make_user())
    assert client.get(f"/_whoami?token={token}").status_code == 401


def test_require_auth_role_from_db(auth_app: Flask, client: FlaskClient, db_clean: None) -> None:
    token = _issue(auth_app, _make_user(role="choir_director"))
    body = _get(client, token).get_json()
    assert body["role"] == "choir_director"


def test_revoke_keeps_calling_token(auth_app: Flask, client: FlaskClient, db_clean: None) -> None:
    uid = _make_user()
    tokens = [_issue(auth_app, uid) for _ in range(3)]
    with auth_app.app_context(), db.transaction() as conn:
        security.revoke_user_sessions(conn, uid, keep_token_hash=security.token_hash(tokens[1]))
    assert [_get(client, t).status_code for t in tokens] == [401, 200, 401]
    with auth_app.app_context(), db.transaction() as conn:
        security.revoke_user_sessions(conn, uid)
    assert _get(client, tokens[1]).status_code == 401


def test_keyed_hash_is_hex_and_stable(app: Flask) -> None:
    with app.app_context():
        assert security.keyed_hash("x") == security.keyed_hash("x")
        assert re.fullmatch(r"[0-9a-f]{64}", security.keyed_hash("x"))
        assert security.keyed_hash("x") != security.keyed_hash("y")


def test_normalize_email() -> None:
    assert normalize_email(" Maria@Example.COM ") == "maria@example.com"
    with pytest.raises(ApiError) as bad:
        normalize_email("no-at")
    assert bad.value.code == "invalid_email"
    with pytest.raises(ApiError) as missing:
        normalize_email("   ")
    assert missing.value.code == "missing_field"


@pytest.mark.parametrize("pw", ["abcdefgh", "12345678", "abc1"])
def test_password_policy_rejects(pw: str) -> None:
    with pytest.raises(ApiError) as exc:
        check_password_policy(pw, "password")
    assert exc.value.status == 400
    assert exc.value.code == "weak_password"
    assert exc.value.field == "password"


def test_password_policy_accepts() -> None:
    check_password_policy("abcdefg1", "password")
