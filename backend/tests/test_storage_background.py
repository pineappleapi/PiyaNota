"""Tests for storage backends, the deletion queue, account purge and pruning (PIYA-309 AC3, PIYA-319)."""

from __future__ import annotations

import logging
import re

import pytest
from flask import Flask
from flask.testing import FlaskClient

from backend import background, db
from backend.config import Settings
from backend.storage import B2Storage, MemoryStorage, new_key

EMAIL = "gone@example.com"
PASSWORD = "Secret123zz"


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


class FlakyStorage(MemoryStorage):
    """Fails the first delete of ``fail_key`` to exercise retry."""

    def __init__(self, fail_key: str) -> None:
        super().__init__()
        self.fail_key = fail_key
        self.failed = False

    def delete(self, key: str) -> None:
        if key == self.fail_key and not self.failed:
            self.failed = True
            raise ConnectionError("https://x/?sig=secret")
        super().delete(key)


def _queued_keys() -> set[str]:
    with db.transaction() as conn:
        return {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions")}


def _count(table: str) -> int:
    with db.transaction() as conn:
        row = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()  # noqa: S608 - test constant
    assert row is not None
    return int(row["n"])


def test_memory_storage_roundtrip() -> None:
    s = MemoryStorage()
    s.put("pages/a.jpg", b"x", "image/jpeg")
    assert s.get("pages/a.jpg") == b"x"
    s.delete("pages/a.jpg")
    s.delete("pages/a.jpg")  # missing key is not an error
    assert "pages/a.jpg" not in s.objects


def test_new_key_is_random_uuid() -> None:
    a, b = new_key("pages", "jpg"), new_key("pages", "jpg")
    assert a != b
    assert re.fullmatch(r"pages/[0-9a-f-]{36}\.jpg", a)


def test_b2_signed_url_has_expiry(settings: Settings) -> None:
    from dataclasses import replace

    cfg = replace(
        settings,
        storage_backend="b2",
        b2_endpoint="https://s3.us-west-004.backblazeb2.com",
        b2_bucket="bucket",
        b2_key_id="id",
        b2_app_key="key",
    )
    storage = B2Storage(cfg)
    assert "X-Amz-Expires=3600" in storage.signed_url("audio/a.mp3")
    assert "X-Amz-Expires=60" in storage.signed_url("audio/a.mp3", ttl_seconds=60)


def test_deletion_queue_deletes_and_retries(app: Flask) -> None:
    storage = FlakyStorage("pages/a.jpg")
    storage.put("pages/a.jpg", b"1", "image/jpeg")
    storage.put("pages/b.jpg", b"2", "image/jpeg")
    with db.transaction() as conn:
        background.queue_deletion(conn, ["pages/a.jpg", "pages/b.jpg"])

    assert background.run_deletions(storage) == 1
    assert "pages/b.jpg" not in storage.objects
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT attempts, last_error, next_attempt_at > now() AS future FROM storage_deletions"
        ).fetchone()
        assert row is not None
        assert (row["attempts"], row["last_error"], row["future"]) == (1, "ConnectionError", True)
        conn.execute("UPDATE storage_deletions SET next_attempt_at = now()")

    assert background.run_deletions(storage) == 1
    assert storage.objects == {}
    assert _count("storage_deletions") == 0


def _seed_user(email: str = EMAIL) -> tuple[int, set[str]]:
    """Insert a deleted user owning every kind of user-linked row; returns (id, object keys)."""
    keys = {"pages/p1.jpg", "thumbs/t.jpg", "audio/s.mp3", "timing/m.json"}
    with db.transaction() as conn:
        row = conn.execute(
            "INSERT INTO users (email, password_hash, deleted_at) VALUES (%s, 'h', now()) RETURNING id",
            (email,),
        ).fetchone()
        assert row is not None
        uid: int = row["id"]
        score = conn.execute(
            "INSERT INTO scores (user_id, title, page_count, tempo_source, review, thumbnail_key) "
            "VALUES (%s, 'T', 1, 'default', '{}', 'thumbs/t.jpg') RETURNING id",
            (uid,),
        ).fetchone()
        assert score is not None
        job = conn.execute(
            "INSERT INTO jobs (user_id, score_id, status, source, page_count, title, tempo_source) "
            "VALUES (%s, %s, 'complete', 'images', 1, 'T', 'default') RETURNING id",
            (uid, score["id"]),
        ).fetchone()
        assert job is not None
        conn.execute(
            "INSERT INTO job_pages (job_id, page_index, object_key, width, height) "
            "VALUES (%s, 0, 'pages/p1.jpg', 10, 10)",
            (job["id"],),
        )
        conn.execute(
            "INSERT INTO audio_tracks (score_id, voice, file_key) VALUES (%s, 'soprano', 'audio/s.mp3')",
            (score["id"],),
        )
        conn.execute(
            "INSERT INTO timing_metadata (score_id, metadata_key) VALUES (%s, 'timing/m.json')",
            (score["id"],),
        )
        conn.execute(
            "INSERT INTO sessions (user_id, token_hash, expires_at) "
            "VALUES (%s, '\\x01', now() + interval '1 day')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
            "VALUES (%s, '\\x02', now() + interval '1 day')",
            (uid,),
        )
    return uid, keys


def test_purge_cascades_and_logs(
    app: Flask, client: FlaskClient, caplog: pytest.LogCaptureFixture
) -> None:
    uid, keys = _seed_user()
    with caplog.at_level(logging.INFO, logger="backend.background"):
        assert background.run_purges(MemoryStorage()) == 1
    for table in (
        "users", "sessions", "password_reset_tokens", "scores", "jobs",
        "job_pages", "audio_tracks", "timing_metadata",
    ):
        assert _count(table) == 0, table
    assert _queued_keys() == keys
    with db.transaction() as conn:
        log = conn.execute("SELECT user_ref FROM purge_log").fetchall()
    assert [r["user_ref"] for r in log] == [uid]
    assert f"account purge complete user_ref={uid}" in caplog.text
    assert EMAIL not in caplog.text
    res = client.post(
        "/api/auth/signup",
        json={"email": EMAIL, "password": PASSWORD, "passwordConfirmation": PASSWORD},
    )
    assert res.status_code == 201


def test_purge_failure_leaves_account_marked(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid, keys = _seed_user()

    def boom(conn: object, ks: object) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(background, "queue_deletion", boom)
    assert background.run_purges(MemoryStorage()) == 0
    with db.transaction() as conn:
        row = conn.execute("SELECT deleted_at FROM users WHERE id = %s", (uid,)).fetchone()
    assert row is not None and row["deleted_at"] is not None
    assert _count("purge_log") == 0

    monkeypatch.undo()
    assert background.run_purges(MemoryStorage()) == 1
    assert _queued_keys() == keys


def test_prune_old_rows(app: Flask) -> None:
    with db.transaction() as conn:
        uid = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES ('p@example.com', 'h') RETURNING id"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO throttle_hits (bucket, subject_key, created_at) VALUES "
            "('b', 's', now() - interval '2 hours'), ('b', 's', now())"
        )
        conn.execute(
            "INSERT INTO sessions (user_id, token_hash, expires_at, revoked_at) VALUES "
            "(%(u)s, '\\x01', now() - interval '2 days', NULL),"
            "(%(u)s, '\\x02', now() + interval '1 day', now() - interval '2 days'),"
            "(%(u)s, '\\x03', now() + interval '1 day', NULL)",
            {"u": uid},
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, used_at) VALUES "
            "(%s, '\\x04', now() - interval '2 days', now() - interval '2 days')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO throttle_backoff (scope, subject_key, last_failure_at) VALUES "
            "('s', 'old', now() - interval '2 days'), ('s', 'new', now())"
        )
        removed = background.run_prune(conn)
    assert removed == 1 + 2 + 1 + 1
    assert _count("throttle_hits") == 1
    assert _count("sessions") == 1
    assert _count("password_reset_tokens") == 0
    assert _count("throttle_backoff") == 1


def test_reserved_keys_self_heal(app: Flask) -> None:
    storage = MemoryStorage()
    storage.put("pages/orphan.jpg", b"x", "image/jpeg")
    storage.put("pages/kept.jpg", b"x", "image/jpeg")
    background.reserve_keys(["pages/orphan.jpg", "pages/kept.jpg"])
    assert background.run_deletions(storage) == 0  # reservation not yet due
    with db.transaction() as conn:
        background.release_keys(conn, ["pages/kept.jpg"])
    assert _queued_keys() == {"pages/orphan.jpg"}
    with db.transaction() as conn:
        conn.execute("UPDATE storage_deletions SET next_attempt_at = now()")
    assert background.run_deletions(storage) == 1
    assert set(storage.objects) == {"pages/kept.jpg"}


def test_purge_skips_user_locked_elsewhere(app: Flask) -> None:
    uid, _ = _seed_user()
    with db.transaction() as other:
        other.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (uid,))
        assert background.run_purges(MemoryStorage()) == 0
        assert _count("purge_log") == 0
    assert background.run_purges(MemoryStorage()) == 1
    assert _count("purge_log") == 1
