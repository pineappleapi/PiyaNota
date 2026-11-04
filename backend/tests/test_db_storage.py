"""DbStorage: Postgres-backed object storage shared by the API and the worker process."""

from __future__ import annotations

import dataclasses

import pytest
from flask import Flask

from backend import db
from backend.config import Settings
from backend.storage import DbStorage


@pytest.fixture
def storage(app: Flask, settings: Settings, db_clean: None) -> DbStorage:
    return DbStorage(dataclasses.replace(settings, storage_backend="db"))


def _content_type(key: str) -> str | None:
    with db.transaction() as conn:
        row = conn.execute("SELECT content_type FROM blobs WHERE key = %s", (key,)).fetchone()
    return None if row is None else str(row["content_type"])


def test_put_get_roundtrip_and_content_type(storage: DbStorage) -> None:
    storage.put("audio/a.mp3", b"\x00\x01abc", "audio/mpeg")
    assert storage.get("audio/a.mp3") == b"\x00\x01abc"
    assert _content_type("audio/a.mp3") == "audio/mpeg"


def test_delete_missing_key_is_not_an_error(storage: DbStorage) -> None:
    storage.delete("audio/none.mp3")
    storage.put("audio/b.mp3", b"x", "audio/mpeg")
    storage.delete("audio/b.mp3")
    with pytest.raises(KeyError):
        storage.get("audio/b.mp3")


def test_put_overwrites(storage: DbStorage) -> None:
    storage.put("pages/p.jpg", b"one", "image/jpeg")
    storage.put("pages/p.jpg", b"two", "image/png")
    assert storage.get("pages/p.jpg") == b"two"
    assert _content_type("pages/p.jpg") == "image/png"


def test_signed_url_is_absolute_and_carries_expiry_and_sig(storage: DbStorage) -> None:
    url = storage.signed_url("audio/a.mp3", ttl_seconds=60)
    assert url.startswith("http://localhost/media/audio/a.mp3?exp=")
    assert "&sig=" in url
