"""Flask application factory: JSON error envelope, proxy trust, and the /healthz probe."""

from __future__ import annotations

import logging
import traceback

import psycopg
from flask import Flask, Response
from werkzeug.exceptions import HTTPException, MethodNotAllowed
from werkzeug.middleware.proxy_fix import ProxyFix

from backend import db
from backend.config import SETTINGS_KEY, Settings, load_settings
from backend.envelope import ApiError, error_response, ok
from backend.routes_auth import auth_bp

LOG = logging.getLogger(__name__)
_HTTP_ERROR_CODES: dict[int, str] = {
    404: "not_found",
    405: "method_not_allowed",
    413: "request_too_large",
}
_INTERNAL_MESSAGE = "Internal server error"


def create_app(settings: Settings | None = None) -> Flask:
    """Build the Flask app and initialise the database pool.

    Routes read their configuration from ``app.config[SETTINGS_KEY]``. Blueprints from later
    tasks are registered here.

    Args:
        settings: Explicit configuration. Loaded from the environment when omitted.

    Returns:
        A configured Flask application.
    """
    cfg = settings if settings is not None else load_settings()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_content_length
    app.config[SETTINGS_KEY] = cfg
    # Trusting exactly the proxies we run behind is what keeps client IPs unspoofable via
    # X-Forwarded-For, which the per-IP rate limits depend on.
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=cfg.trusted_proxy_count,
        x_proto=cfg.trusted_proxy_count,
    )
    db.init_pool(
        cfg.database_url,
        max_size=cfg.db_pool_max_size,
        prepare_threshold=cfg.db_prepare_threshold,
    )

    @app.errorhandler(Exception)
    def _handle_error(exc: Exception) -> tuple[Response, int]:
        if isinstance(exc, ApiError):
            return error_response(exc)
        if isinstance(exc, HTTPException):
            status = exc.code or 500
            code = _HTTP_ERROR_CODES.get(status, "http_error")
            response, _ = error_response(ApiError(status, code, exc.name))
            # RFC 9110 requires Allow on 405; werkzeug knows the valid methods.
            if isinstance(exc, MethodNotAllowed) and exc.valid_methods:
                response.headers["Allow"] = ", ".join(exc.valid_methods)
            return response, status
        _log_unhandled(exc)
        return error_response(ApiError(500, "internal_error", _INTERNAL_MESSAGE))

    app.register_blueprint(auth_bp)

    @app.get("/healthz")
    def healthz() -> tuple[Response, int]:
        # Deliberately no DB access: UptimeRobot pings this every 5 minutes and Neon must be
        # allowed to scale to zero.
        return ok({"ok": True}, 200, "ok")

    return app


def _log_unhandled(exc: Exception) -> None:
    """Log what is needed to debug an unexpected error without leaking request data.

    Exception messages can echo user input (psycopg's ``Key (email)=(...)``), so only the type,
    the integrity constraint name and the stack frames are logged, never ``str(exc)``.
    """
    constraint = exc.diag.constraint_name if isinstance(exc, psycopg.Error) else None
    frames = "".join(traceback.format_tb(exc.__traceback__))
    LOG.error("unhandled %s (constraint=%s)\n%s", type(exc).__name__, constraint, frames)
