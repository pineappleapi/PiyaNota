"""Sign-up and login routes (PIYA-301, PIYA-302) with durable throttling (V2 B1)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, cast

import psycopg
from flask import Blueprint, Response, current_app

from backend import db, security, throttle
from backend.config import SETTINGS_KEY, Settings
from backend.envelope import ApiError, iso_z, ok
from backend.validation import (
    MAX_PASSWORD_LENGTH,
    check_password_policy,
    json_body,
    normalize_email,
    require_str,
)

LOG = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

_EMAIL_CONSTRAINT = "users_email_key"
_SIGNUP_BUCKET = "signup_ip"
_LOGIN_IP_BUCKET = "login_ip"
_LOGIN_EMAIL_SCOPE = "login_email"
_INVALID_CREDENTIALS = "Incorrect email or password"


def session_payload(user_row: Mapping[str, Any], token: str, expires_at: datetime) -> dict[str, Any]:
    """Build the ``data`` object shared by sign-up and login responses."""
    return {
        "userId": int(user_row["id"]),
        "email": user_row["email"],
        "role": user_row["role"],
        "sessionToken": token,
        "expiresAt": iso_z(expires_at),
    }


def _settings() -> Settings:
    return cast(Settings, current_app.config[SETTINGS_KEY])


def _invalid_credentials() -> ApiError:
    return ApiError(401, "invalid_credentials", _INVALID_CREDENTIALS)


@auth_bp.post("/signup")
def signup() -> tuple[Response, int]:
    cfg = _settings()
    ip_key = security.keyed_hash(security.client_ip())
    # The hit is recorded and committed before any validation so failed attempts count too;
    # the 429 is raised only after the block, otherwise the rollback would drop the hit.
    with db.transaction() as conn:
        throttle.lock_subject(conn, _SIGNUP_BUCKET, ip_key)
        retry = throttle.window_retry_after(
            conn, _SIGNUP_BUCKET, ip_key, cfg.signup_ip_limit, cfg.signup_ip_window_s
        )
        throttle.record_hit(conn, _SIGNUP_BUCKET, ip_key)
    if retry is not None:
        raise throttle.too_many(retry)

    body = json_body()
    email = normalize_email(body.get("email"))
    password = require_str(body, "password")
    confirmation = require_str(body, "passwordConfirmation")
    if password != confirmation:
        raise ApiError(
            400, "password_mismatch", "Passwords do not match", field="passwordConfirmation"
        )
    check_password_policy(password, "password")

    password_hash = security.hash_password(password)
    try:
        with db.transaction() as conn:
            # Role is never read from the body (PIYA-316 AC4): the column default applies.
            user = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id, email, role",
                (email, password_hash),
            ).fetchone()
            if user is None:
                raise RuntimeError("user insert returned no row")
            token, expires_at = security.issue_session(conn, user["id"])
    except psycopg.errors.UniqueViolation as exc:
        if exc.diag.constraint_name != _EMAIL_CONSTRAINT:
            raise
        # Deliberately not logged: the exception text contains the email.
        raise ApiError(
            409, "email_already_registered", "Email is already registered", field="email"
        ) from None
    return ok(session_payload(user, token, expires_at), 201, "Account created")


@auth_bp.post("/login")
def login() -> tuple[Response, int]:
    cfg = _settings()
    body = json_body()
    email = normalize_email(body.get("email"))
    password = require_str(body, "password")
    email_key = security.keyed_hash(email)
    ip_key = security.keyed_hash(security.client_ip())

    failure: ApiError | None = None
    result: tuple[Mapping[str, Any], str, datetime] | None = None
    # Failures and 429 decisions must commit, so ApiError is raised only after the block.
    with db.transaction() as conn:
        throttle.lock_subject(conn, _LOGIN_EMAIL_SCOPE, email_key)
        throttle.lock_subject(conn, _LOGIN_IP_BUCKET, ip_key)
        waits = [
            throttle.backoff_wait(conn, _LOGIN_EMAIL_SCOPE, email_key),
            throttle.window_retry_after(
                conn, _LOGIN_IP_BUCKET, ip_key, cfg.login_ip_limit, cfg.login_ip_window_s
            ),
        ]
        active = [w for w in waits if w is not None]
        if active:
            failure = throttle.too_many(max(active))
        else:
            user = conn.execute(
                "SELECT id, email, role, password_hash FROM users "
                "WHERE email = %s AND deleted_at IS NULL",
                (email,),
            ).fetchone()
            valid = False
            if user is None or len(password) > MAX_PASSWORD_LENGTH:
                # Exactly one argon2 call on every failing path, so neither an unknown email nor
                # an over-long password on a known one is distinguishable by timing.
                security.verify_dummy()
            else:
                valid = security.verify_password(password, user["password_hash"])
            if valid and user is not None:
                throttle.clear_failures(conn, _LOGIN_EMAIL_SCOPE, email_key)
                if security.needs_rehash(user["password_hash"]):
                    conn.execute(
                        "UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s",
                        (security.hash_password(password), user["id"]),
                    )
                token, expires_at = security.issue_session(conn, user["id"])
                result = (user, token, expires_at)
            else:
                throttle.record_failure(conn, _LOGIN_EMAIL_SCOPE, email_key, free_failures=0)
                throttle.record_hit(conn, _LOGIN_IP_BUCKET, ip_key)
                LOG.info(
                    "login failed email=%s at=%s", email_key, iso_z(datetime.now(timezone.utc))
                )
                failure = _invalid_credentials()
    if failure is not None:
        raise failure
    if result is None:
        raise RuntimeError("login finished without a result or an error")
    return ok(session_payload(*result), 200, "Login successful")
