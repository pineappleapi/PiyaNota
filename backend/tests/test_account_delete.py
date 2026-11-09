"""B3: DELETE /api/account purges inline (J3)."""

from __future__ import annotations

import psycopg.errors
import pytest
from flask import Flask
from flask.testing import FlaskClient

from backend import background, db
from backend.storage import MemoryStorage
from backend.tests.test_account import EMAIL, PASSWORD, WRONG, _auth, _login, _signup

pytestmark = pytest.mark.usefixtures("db_clean")

LOGIN_EMAIL_SCOPE = "login_email"


def _seed_blobs(app: Flask, email: str) -> tuple[int, set[str]]:
    """Give the user one blob of every kind, in the memory store; returns (id, keys)."""
    storage = app.extensions["storage"]
    assert isinstance(storage, MemoryStorage)
    tag = email.split("@")[0]
    keys = {f"pages/{tag}.jpg", f"thumbs/{tag}.jpg", f"audio/{tag}.mp3", f"midi/{tag}.mid", f"timing/{tag}.json"}
    for k in keys:
        storage.put(k, b"x", "application/octet-stream")
    with db.transaction() as conn:
        uid = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()["id"]
        sid = conn.execute(
            "INSERT INTO scores (user_id, title, page_count, tempo_source, review, thumbnail_key) "
            "VALUES (%s, 'T', 1, 'default', '{}', %s) RETURNING id",
            (uid, f"thumbs/{tag}.jpg"),
        ).fetchone()["id"]
        jid = conn.execute(
            "INSERT INTO jobs (user_id, score_id, status, source, page_count, title, tempo_source) "
            "VALUES (%s, %s, 'complete', 'images', 1, 'T', 'default') RETURNING id",
            (uid, sid),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO job_pages (job_id, page_index, object_key, width, height) "
            "VALUES (%s, 0, %s, 10, 10)",
            (jid, f"pages/{tag}.jpg"),
        )
        conn.execute(
            "INSERT INTO audio_tracks (score_id, voice, file_key, midi_key) VALUES (%s, 'soprano', %s, %s)",
            (sid, f"audio/{tag}.mp3", f"midi/{tag}.mid"),
        )
        conn.execute(
            "INSERT INTO timing_metadata (score_id, metadata_key) VALUES (%s, %s)",
            (sid, f"timing/{tag}.json"),
        )
    return uid, keys


def _delete(client: FlaskClient, token: str, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return client.delete("/api/account", json={"password": password}, headers=_auth(token))


def test_delete_then_old_token_login_and_resignup(client: FlaskClient) -> None:
    token = _signup(client)
    assert _delete(client, token).status_code == 200
    assert client.get("/api/scores", headers=_auth(token)).status_code == 401
    res = _login(client)
    assert res.status_code == 401 and res.get_json()["error"]["code"] == "invalid_credentials"
    assert _signup(client)  # 201 asserted inside, no wait for the loop


def test_no_blob_of_user_remains(app: Flask, client: FlaskClient) -> None:
    token = _signup(client)
    uid, keys = _seed_blobs(app, EMAIL)
    storage = app.extensions["storage"]
    assert _delete(client, token).status_code == 200
    with db.transaction() as conn:
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions")}
        log = conn.execute("SELECT user_ref FROM purge_log").fetchall()
    assert queued == keys and [r["user_ref"] for r in log] == [uid]
    background.run_deletions(storage)
    assert not (keys & set(storage.objects))


def test_wrong_password_changes_nothing_and_skips_login_lockout(
    app: Flask, client: FlaskClient
) -> None:
    token = _signup(client)
    _, keys = _seed_blobs(app, EMAIL)
    res = _delete(client, token, WRONG)
    assert res.status_code == 403 and res.get_json()["error"]["code"] == "invalid_current_password"
    with db.transaction() as conn:
        assert conn.execute("SELECT 1 FROM users WHERE email = %s", (EMAIL,)).fetchone()
        assert conn.execute("SELECT 1 FROM storage_deletions").fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM throttle_backoff WHERE scope = %s", (LOGIN_EMAIL_SCOPE,)
        ).fetchone() is None
    assert client.get("/api/account", headers=_auth(token)).status_code == 200
    assert keys <= set(app.extensions["storage"].objects)


def test_inline_purge_failure_rolls_back(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _signup(client)

    def boom(conn: object, ks: object) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(background, "queue_deletion", boom)
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    assert _delete(client, token).status_code == 500
    monkeypatch.undo()
    with db.transaction() as conn:
        row = conn.execute("SELECT deleted_at FROM users WHERE email = %s", (EMAIL,)).fetchone()
    assert row is not None and row["deleted_at"] is None
    assert client.get("/api/account", headers=_auth(token)).status_code == 200


def test_delete_retries_once_on_deadlock(client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _signup(client)
    real = background.purge_user
    calls: list[int] = []

    def flaky(conn: background.Conn, user_id: int) -> None:
        calls.append(user_id)
        if len(calls) == 1:
            raise psycopg.errors.DeadlockDetected("simulated")
        real(conn, user_id)

    monkeypatch.setattr(background, "purge_user", flaky)
    assert _delete(client, token).status_code == 200
    assert len(calls) == 2
    monkeypatch.undo()
    with db.transaction() as conn:
        assert conn.execute("SELECT 1 FROM users WHERE email = %s", (EMAIL,)).fetchone() is None
