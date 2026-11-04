"""Signed /media/<key> route: the signature is the capability, so no auth header is involved."""

from __future__ import annotations

import dataclasses
import hmac
from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from backend import db, routes_media
from backend.app import create_app
from backend.config import Settings

KEY = "audio/0123.mp3"
DATA = bytes(range(200))
PUBLIC_BASE = "http://localhost"


@pytest.fixture
def app(settings: Settings) -> Iterator[Flask]:
    flask_app = create_app(dataclasses.replace(settings, storage_backend="db"))
    flask_app.config["TESTING"] = True
    yield flask_app
    db.close_pool()


@pytest.fixture
def client(app: Flask, db_clean: None) -> FlaskClient:
    app.extensions["storage"].put(KEY, DATA, "audio/mpeg")
    return app.test_client()


def _link(app: Flask, key: str = KEY, ttl: int = 60) -> str:
    url: str = app.extensions["storage"].signed_url(key, ttl_seconds=ttl)
    return url.removeprefix(PUBLIC_BASE)


def test_valid_link_returns_bytes_and_content_type(app: Flask, client: FlaskClient) -> None:
    resp = client.get(_link(app))
    assert resp.status_code == 200
    assert resp.data == DATA
    assert resp.headers["Content-Type"] == "audio/mpeg"
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert resp.headers["Cache-Control"] == "private, max-age=0"


def test_expired_link_403(app: Flask, client: FlaskClient) -> None:
    assert client.get(_link(app, ttl=-10)).status_code == 403


def test_tampered_signature_403(app: Flask, client: FlaskClient) -> None:
    link = _link(app)
    bad = client.get(link[:-1] + ("0" if link[-1] != "0" else "1"))
    assert bad.status_code == 403
    expired = client.get(_link(app, ttl=-10))
    assert bad.data == expired.data  # same body: do not reveal which check failed


def test_range_0_99_returns_206_with_content_range(app: Flask, client: FlaskClient) -> None:
    resp = client.get(_link(app), headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert resp.data == DATA[:100]
    assert resp.headers["Content-Range"] == "bytes 0-99/200"
    assert resp.headers["Content-Length"] == "100"


def test_open_ended_and_suffix_ranges(app: Flask, client: FlaskClient) -> None:
    open_ended = client.get(_link(app), headers={"Range": "bytes=150-"})
    assert open_ended.status_code == 206
    assert open_ended.data == DATA[150:]
    assert open_ended.headers["Content-Range"] == "bytes 150-199/200"
    suffix = client.get(_link(app), headers={"Range": "bytes=-10"})
    assert suffix.status_code == 206
    assert suffix.data == DATA[-10:]
    assert suffix.headers["Content-Range"] == "bytes 190-199/200"


@pytest.mark.parametrize(
    "value",
    ["bytes=200-", "bytes=500-600", "bytes=5-2", "bytes=abc", "items=0-1", "bytes=0-1,5-6", "bytes=-0"],
)
def test_unsatisfiable_range_416(app: Flask, client: FlaskClient, value: str) -> None:
    resp = client.get(_link(app), headers={"Range": value})
    assert resp.status_code == 416
    assert resp.headers["Content-Range"] == "bytes */200"


def test_unknown_key_404(app: Flask, client: FlaskClient) -> None:
    assert client.get(_link(app, key="audio/missing.mp3")).status_code == 404


def test_weird_key_is_handled_safely(app: Flask, client: FlaskClient) -> None:
    resp = client.get(_link(app, key="x'; DROP TABLE blobs;--"))
    assert resp.status_code == 404  # validly signed but unknown; parameterised query, no injection
    assert client.get(_link(app)).status_code == 200


def test_head_returns_length_without_body(app: Flask, client: FlaskClient) -> None:
    resp = client.head(_link(app))
    assert resp.status_code == 200
    assert resp.data == b""
    assert resp.headers["Content-Length"] == "200"
    assert resp.headers["Content-Type"] == "audio/mpeg"


def test_signature_compare_is_constant_time(
    app: Flask, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = hmac.compare_digest

    def spy(a: str | bytes, b: str | bytes) -> bool:
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(routes_media.hmac, "compare_digest", spy)
    assert client.get(_link(app)).status_code == 200
    assert calls
