"""Settings and wiring for the db storage backend: no public dev key, /media only when used."""

from __future__ import annotations

import dataclasses

import pytest

from backend import db
from backend.app import create_app
from backend.config import Settings, load_settings

_PROD_DB_ENV = {
    "PIYA_ENV": "prod",
    "PIYA_DATABASE_URL": "postgresql://u:p@localhost:55432/piya_test",
    "PIYA_REQUIRE_HTTPS": "true",
    "PIYA_STORAGE_BACKEND": "db",
    "PIYA_MAIL_BACKEND": "memory",
    "PIYA_MAIL_FROM": "noreply@example.com",
    "PIYA_RESET_CODE_HMAC_KEY": "k1",
    "PIYA_LOG_HASH_KEY": "k2",
    "PIYA_MEDIA_HMAC_KEY": "k3",
    "PIYA_PUBLIC_BASE_URL": "https://api.example.com",
}


def test_prod_db_with_all_settings_loads() -> None:
    assert load_settings(_PROD_DB_ENV).public_base_url == "https://api.example.com"


def test_prod_db_requires_media_hmac_key() -> None:
    env = {k: v for k, v in _PROD_DB_ENV.items() if k != "PIYA_MEDIA_HMAC_KEY"}
    with pytest.raises(RuntimeError, match="PIYA_MEDIA_HMAC_KEY"):
        load_settings(env)


def test_prod_db_requires_public_base_url() -> None:
    env = {k: v for k, v in _PROD_DB_ENV.items() if k != "PIYA_PUBLIC_BASE_URL"}
    with pytest.raises(RuntimeError, match="PIYA_PUBLIC_BASE_URL"):
        load_settings(env)


def test_prod_db_public_base_url_must_be_https() -> None:
    with pytest.raises(ValueError, match="PIYA_PUBLIC_BASE_URL"):
        load_settings({**_PROD_DB_ENV, "PIYA_PUBLIC_BASE_URL": "http://api.example.com"})


def test_memory_storage_app_has_no_media_route(settings: Settings) -> None:
    app = create_app(dataclasses.replace(settings, storage_backend="memory"))
    try:
        assert app.test_client().get("/media/audio/a.mp3?exp=1&sig=x").status_code == 404
    finally:
        db.close_pool()
