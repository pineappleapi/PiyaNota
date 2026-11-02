"""Flask application factory: JSON error envelope, proxy trust, and the /healthz probe."""

from __future__ import annotations

import logging

from flask import Flask, Response
from werkzeug.exceptions import HTTPException, MethodNotAllowed
from werkzeug.middleware.proxy_fix import ProxyFix

from backend import background, db
from backend.mailer import build_mailer
from backend.config import SETTINGS_KEY, Settings, load_settings
from backend.logutil import describe_exception
from backend.envelope import ApiError, error_response, ok
from backend.routes_account import account_bp
from backend.routes_auth import auth_bp
from backend.routes_jobs import jobs_bp
from backend.routes_scores import scores_bp
from backend.storage import build_storage

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

    app.extensions["mailer"] = build_mailer(cfg)
    app.extensions["storage"] = build_storage(cfg)
    app.register_blueprint(auth_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(scores_bp)

    @app.get("/healthz")
    def healthz() -> tuple[Response, int]:
        # Deliberately no DB access: UptimeRobot pings this every 5 minutes and Neon must be
        # allowed to scale to zero.
        return ok({"ok": True}, 200, "ok")

    if cfg.run_background:
        background.start_loop(app)

    return app


def _log_unhandled(exc: Exception) -> None:
    """Log what is needed to debug an unexpected error without leaking request data."""
    LOG.error("unhandled %s", describe_exception(exc))
