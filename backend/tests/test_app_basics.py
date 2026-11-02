"""Scaffold behaviour: envelope shape, error handlers, settings loading, and pool recovery."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from flask import Flask
from flask.testing import FlaskClient

from backend import db
from backend.config import Settings, load_settings
from backend.envelope import ApiError, iso_z, ok
from backend.validation import json_body


def _add_json_probe(app: Flask) -> None:
    # Test-only route: production code never exposes json_body() on its own.
    @app.post("/_probe/json")
    def probe() -> dict[str, object]:
        return {"success": True, "data": json_body()}


def test_healthz_ok(client: FlaskClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_unknown_route_json_404(client: FlaskClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["error"]["code"] == "not_found"


def test_method_not_allowed_json(client: FlaskClient) -> None:
    response = client.post("/healthz")
    assert response.status_code == 405
    assert response.get_json()["error"]["code"] == "method_not_allowed"
    assert "GET" in response.headers["Allow"]


def test_success_envelope_keys(app: Flask) -> None:
    @app.get("/_probe/ok")
    def probe_ok() -> tuple[object, int]:
        return ok({"x": 1}, 201, "made")

    response = app.test_client().get("/_probe/ok")
    assert response.status_code == 201
    assert response.get_json() == {"data": {"x": 1}, "success": True, "status": 201, "message": "made"}


def test_error_envelope_keys(app: Flask) -> None:
    @app.get("/_probe/err")
    def probe_err() -> None:
        raise ApiError(409, "conflict", "nope", field="email", page_index=2, retry_after=30)

    response = app.test_client().get("/_probe/err")
    assert response.status_code == 409
    assert response.headers["Retry-After"] == "30"
    assert response.get_json() == {
        "data": None,
        "success": False,
        "status": 409,
        "message": "nope",
        "error": {
            "code": "conflict",
            "field": "email",
            "pageIndex": 2,
            "retryAfterSeconds": 30,
        },
    }


def test_request_too_large_json_413(app: Flask) -> None:
    _add_json_probe(app)
    app.config["MAX_CONTENT_LENGTH"] = 64
    response = app.test_client().post(
        "/_probe/json", data='{"pad": "' + "x" * 200 + '"}', content_type="application/json"
    )
    assert response.status_code == 413
    assert response.is_json
    assert response.get_json()["error"]["code"] == "request_too_large"


@pytest.mark.parametrize("payload", ["[]", "null", '"x"', "{bad"])
def test_json_body_rejects_non_object(app: Flask, payload: str) -> None:
    _add_json_probe(app)
    response = app.test_client().post(
        "/_probe/json", data=payload, content_type="application/json"
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_json"


def test_json_body_rejects_wrong_content_type(app: Flask) -> None:
    _add_json_probe(app)
    response = app.test_client().post("/_probe/json", data='{"a": 1}', content_type="text/plain")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_json"


def test_json_body_accepts_object(app: Flask) -> None:
    _add_json_probe(app)
    response = app.test_client().post("/_probe/json", json={"a": 1})
    assert response.status_code == 200
    assert response.get_json()["data"] == {"a": 1}


def test_internal_error_is_generic(app: Flask) -> None:
    @app.get("/_probe/boom")
    def boom() -> str:
        raise RuntimeError("secret detail")

    response = app.test_client().get("/_probe/boom")
    assert response.status_code == 500
    assert "secret detail" not in response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "internal_error"


def test_integrity_error_not_logged_verbatim(app: Flask, caplog: pytest.LogCaptureFixture) -> None:
    # Built at runtime so the value does not also appear in the source line that the
    # traceback frames quote.
    email = "someone@example.com"

    @app.get("/_probe/integrity")
    def integrity() -> str:
        raise psycopg.errors.UniqueViolation(f"Key (email)=({email}) already exists.")

    with caplog.at_level(logging.ERROR, logger="backend.app"):
        response = app.test_client().get("/_probe/integrity")
    assert response.status_code == 500
    assert email not in caplog.text
    assert "UniqueViolation" in caplog.text


def test_iso_z_normalises_to_utc() -> None:
    moment = datetime(2026, 11, 1, 9, 30, 0, tzinfo=timezone(timedelta(hours=8)))
    assert iso_z(moment) == "2026-11-01T01:30:00Z"


def test_iso_z_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        iso_z(datetime(2026, 11, 1, 9, 30))  # noqa: DTZ001


_PROD_ENV: dict[str, str] = {
    "PIYA_ENV": "prod",
    "PIYA_DATABASE_URL": "postgresql://x",
    "PIYA_RESET_CODE_HMAC_KEY": "reset-key",
    "PIYA_LOG_HASH_KEY": "log-key",
    "PIYA_REQUIRE_HTTPS": "true",
    "PIYA_STORAGE_BACKEND": "memory",
    "PIYA_MAIL_BACKEND": "memory",
    "PIYA_MAIL_FROM": "noreply@example.org",
}


def test_prod_settings_require_secrets() -> None:
    with pytest.raises(RuntimeError, match="PIYA_"):
        load_settings({"PIYA_ENV": "prod"})


def test_prod_accepts_complete_env() -> None:
    assert load_settings(_PROD_ENV).env == "prod"


@pytest.mark.parametrize("missing", ["PIYA_RESET_CODE_HMAC_KEY", "PIYA_DATABASE_URL"])
def test_prod_names_missing_variable(missing: str) -> None:
    env = {k: v for k, v in _PROD_ENV.items() if k != missing}
    with pytest.raises(RuntimeError, match=missing):
        load_settings(env)


def test_prod_requires_https_flag() -> None:
    with pytest.raises(RuntimeError, match="PIYA_REQUIRE_HTTPS"):
        load_settings({**_PROD_ENV, "PIYA_REQUIRE_HTTPS": "false"})


def test_secrets_encode_as_utf8_bytes_and_database_url_falls_back() -> None:
    settings: Settings = load_settings(
        {
            "PIYA_ENV": "test",
            "PIYA_RESET_CODE_HMAC_KEY": "réset",
            "PIYA_LOG_HASH_KEY": "log",
            "DATABASE_URL": "postgresql://fallback",
        }
    )
    assert settings.reset_code_hmac_key == "réset".encode("utf-8")
    assert settings.log_hash_key == b"log"
    assert settings.database_url == "postgresql://fallback"


def test_dev_secrets_have_defaults() -> None:
    settings = load_settings({"PIYA_ENV": "dev"})
    assert settings.reset_code_hmac_key
    assert settings.log_hash_key


def test_pool_recovers_after_backend_terminated(app: Flask, settings: Settings) -> None:
    # max_size=1 forces the same physical connection to be reused, so the terminated backend is
    # the one the pool hands out next.
    db.init_pool(settings.database_url, max_size=1, prepare_threshold=None)
    with db.transaction() as conn:
        pid = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]

    with psycopg.connect(settings.database_url, autocommit=True) as admin:
        # The 5000 ms timeout waits until the backend has actually exited; without it the
        # next checkout could race a dying connection.
        admin.execute("SELECT pg_terminate_backend(%s, 5000)", (pid,))

    with db.transaction() as conn:
        row = conn.execute("SELECT 1 AS one").fetchone()
    assert row == {"one": 1}


def test_debug_headers_off_by_default(client: FlaskClient) -> None:
    assert client.get("/api/_debug/headers").status_code == 404


def test_debug_headers_returns_proxy_headers(settings: Settings) -> None:
    from dataclasses import replace

    from backend.app import create_app

    app = create_app(replace(settings, debug_headers=True))
    try:
        response = app.test_client().get(
            "/api/_debug/headers",
            headers={"X-Forwarded-For": "203.0.113.9", "CF-Connecting-IP": "203.0.113.9"},
        )
        data = response.get_json()["data"]
        assert response.status_code == 200
        assert data["X-Forwarded-For"] == "203.0.113.9"
        assert data["CF-Connecting-IP"] == "203.0.113.9"
        assert data["True-Client-IP"] is None
    finally:
        db.close_pool()


def test_debug_headers_env_flag(settings: Settings) -> None:
    assert load_settings({"PIYA_ENV": "test", "PIYA_DEBUG_HEADERS": "1"}).debug_headers is True
    assert settings.debug_headers is False


def test_prod_with_log_mailer_warns(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    from dataclasses import replace

    from backend.app import create_app

    prod = replace(settings, env="prod", require_https=True, mail_backend="log")
    with caplog.at_level(logging.WARNING, logger="backend.app"):
        create_app(prod)
    db.close_pool()
    assert "mail backend is 'log'" in caplog.text
