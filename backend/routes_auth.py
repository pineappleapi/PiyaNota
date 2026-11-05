"""Sign-up and login routes (PIYA-301, PIYA-302) with durable throttling (V2 B1)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, cast

import psycopg
from flask import Blueprint, Response, current_app, g

from backend import db, security, throttle
from backend.mailer import MailError, get_mailer
from backend.config import SETTINGS_KEY, Settings
from backend.envelope import ApiError, iso_z, ok
from backend.routes_account import check_current_password
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


_RESET_REQ_EMAIL_BUCKET = "reset_req_email"
_RESET_REQ_IP_BUCKET = "reset_req_ip"
_RESET_CODE_SCOPE = "reset_code"
_RESET_CODE_IP_BUCKET = "reset_code_ip"
_RESET_WINDOW_S = 3600
_RESET_CODE_DIGITS = 6
_RESET_FREE_FAILURES = 4
_RESET_CODE_EMAIL_BUCKET = "reset_code_email"
_RESET_CODE_EMAIL_PER_HOUR = 10
_RESET_REQUEST_MESSAGE = "If this email is registered, a reset link has been sent"


def _code_digest(code: str) -> bytes:
    """HMAC of a reset code; the 6-digit space is tiny, so a plain hash would be brute-forceable."""
    key = _settings().reset_code_hmac_key
    return hmac.new(key, code.encode("utf-8"), hashlib.sha256).digest()


@auth_bp.post("/password-reset/request")
def password_reset_request() -> tuple[Response, int]:
    cfg = _settings()
    body = json_body()
    email = normalize_email(body.get("email"))
    email_key = security.keyed_hash(email)
    ip_key = security.keyed_hash(security.client_ip())

    failure: ApiError | None = None
    # Throttle first and record every admitted request (even for unknown emails) so the 404 cannot
    # be used for unlimited enumeration. Hits commit; the error is raised after the block.
    with db.transaction() as conn:
        throttle.lock_subject(conn, _RESET_REQ_EMAIL_BUCKET, email_key)
        throttle.lock_subject(conn, _RESET_REQ_IP_BUCKET, ip_key)
        # Same lock as verify/confirm so a concurrent confirm cannot accept the superseded code.
        throttle.lock_subject(conn, _RESET_CODE_SCOPE, email_key)
        waits = [
            throttle.window_retry_after(
                conn,
                _RESET_REQ_EMAIL_BUCKET,
                email_key,
                cfg.reset_request_email_per_hour,
                _RESET_WINDOW_S,
            ),
            throttle.window_retry_after(
                conn, _RESET_REQ_IP_BUCKET, ip_key, cfg.reset_request_ip_per_hour, _RESET_WINDOW_S
            ),
        ]
        active = [w for w in waits if w is not None]
        if active:
            # Requests answered 429 are not counted, so a blocked caller cannot extend the window.
            failure = throttle.too_many(max(active))
        else:
            throttle.record_hit(conn, _RESET_REQ_EMAIL_BUCKET, email_key)
            throttle.record_hit(conn, _RESET_REQ_IP_BUCKET, ip_key)
            user = conn.execute(
                "SELECT id FROM users WHERE email = %s AND deleted_at IS NULL FOR UPDATE",
                (email,),
            ).fetchone()
            if user is None:
                failure = ApiError(
                    404, "email_not_registered", "Email is not registered", field="email"
                )
            else:
                code = f"{secrets.randbelow(10**_RESET_CODE_DIGITS):0{_RESET_CODE_DIGITS}d}"
                try:
                    # Savepoint: a send failure drops the new code but keeps the throttle hits.
                    with conn.transaction():
                        conn.execute(
                            "UPDATE password_reset_tokens SET used_at = now() "
                            "WHERE user_id = %s AND used_at IS NULL",
                            (user["id"],),
                        )
                        conn.execute(
                            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
                            "VALUES (%s, %s, now() + make_interval(mins => %s))",
                            (user["id"], _code_digest(code), cfg.reset_code_ttl_minutes),
                        )
                        # Inside the savepoint so no live code exists for a mail never sent.
                        get_mailer().send_reset_code(email, code)
                        throttle.clear_failures(conn, _RESET_CODE_SCOPE, email_key)
                except MailError as exc:
                    LOG.error("reset mail failed email=%s: %s", email_key, exc)
                    failure = ApiError(500, "internal_error", "Internal server error")
    if failure is not None:
        raise failure
    return ok(None, 200, _RESET_REQUEST_MESSAGE)


def _check_reset_code(
    conn: throttle.Conn,
    email: str,
    code: str,
    *,
    hit_on_gone: bool,
    precheck: Callable[[], None] | None = None,
) -> tuple[ApiError | None, Mapping[str, Any] | None]:
    """Shared by verify and confirm: locks, waits, token lookup, wrong-code bookkeeping.

    Returns ``(failure, row)``; exactly one is set. ``precheck`` runs after the wait check but
    before the code is looked at, so a typo neither consumes the code nor counts as a guess.
    Verify records a ``reset_code_ip`` hit on every 410 (``hit_on_gone``) because an unknown
    email and a missing live code look identical to the caller.
    """
    cfg = _settings()
    email_key = security.keyed_hash(email)
    ip_key = security.keyed_hash(security.client_ip())
    throttle.lock_subject(conn, _RESET_CODE_SCOPE, email_key)
    throttle.lock_subject(conn, _RESET_CODE_IP_BUCKET, ip_key)
    waits = [
        throttle.backoff_wait(conn, _RESET_CODE_SCOPE, email_key),
        throttle.window_retry_after(
            conn, _RESET_CODE_IP_BUCKET, ip_key, cfg.reset_code_ip_per_hour, _RESET_WINDOW_S
        ),
        throttle.window_retry_after(
            conn,
            _RESET_CODE_EMAIL_BUCKET,
            email_key,
            _RESET_CODE_EMAIL_PER_HOUR,
            _RESET_WINDOW_S,
        ),
    ]
    active = [w for w in waits if w is not None]
    if active:
        return throttle.too_many(max(active)), None
    if precheck is not None:
        precheck()
    row = conn.execute(
        "SELECT u.id AS user_id, t.id AS token_id, t.token_hash, "
        "GREATEST(1, CEIL(EXTRACT(EPOCH FROM t.expires_at - now())))::int AS expires_in "
        "FROM users u JOIN password_reset_tokens t ON t.user_id = u.id "
        "WHERE u.email = %s AND u.deleted_at IS NULL "
        "AND t.used_at IS NULL AND t.expires_at > now() FOR UPDATE OF u",
        (email,),
    ).fetchone()
    if row is None:
        if hit_on_gone:
            throttle.record_hit(conn, _RESET_CODE_IP_BUCKET, ip_key)
        return (
            ApiError(410, "reset_token_expired_or_invalid", "Reset code expired or invalid"),
            None,
        )
    if hmac.compare_digest(bytes(row["token_hash"]), _code_digest(code)):
        return None, row
    # V2 B4.8: the IP window counts wrong codes only; so does the hourly per-email window.
    throttle.record_failure(
        conn, _RESET_CODE_SCOPE, email_key, free_failures=_RESET_FREE_FAILURES
    )
    throttle.record_hit(conn, _RESET_CODE_IP_BUCKET, ip_key)
    throttle.record_hit(conn, _RESET_CODE_EMAIL_BUCKET, email_key)
    return (
        ApiError(
            400,
            "reset_code_invalid",
            "Reset code is incorrect",
            field="resetToken",
            retry_after=throttle.backoff_wait(conn, _RESET_CODE_SCOPE, email_key),
        ),
        None,
    )


@auth_bp.post("/password-reset/verify")
def password_reset_verify() -> tuple[Response, int]:
    body = json_body()
    email = normalize_email(body.get("email"))
    code = require_str(body, "code").strip()
    with db.transaction() as conn:
        failure, row = _check_reset_code(conn, email, code, hit_on_gone=True)
    if failure is not None:
        raise failure
    if row is None:
        raise RuntimeError("verify finished without a result or an error")
    return ok({"expiresInSeconds": int(row["expires_in"])}, 200, "Reset code verified")


@auth_bp.post("/password-reset/confirm")
def password_reset_confirm() -> tuple[Response, int]:
    body = json_body()
    email = normalize_email(body.get("email"))
    code = require_str(body, "resetToken").strip()
    password = require_str(body, "newPassword")
    confirmation = require_str(body, "newPasswordConfirmation")

    def precheck() -> None:
        if password != confirmation:
            raise ApiError(
                400, "password_mismatch", "Passwords do not match", field="newPasswordConfirmation"
            )
        check_password_policy(password, "newPassword")

    with db.transaction() as conn:
        failure, row = _check_reset_code(
            conn, email, code, hit_on_gone=False, precheck=precheck
        )
        if failure is None and row is not None:
            # Hashed only once the code verified, so unauthenticated callers cannot burn CPU.
            email_key = security.keyed_hash(email)
            conn.execute(
                "UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s",
                (security.hash_password(password), row["user_id"]),
            )
            conn.execute(
                "UPDATE password_reset_tokens SET used_at = now() WHERE id = %s",
                (row["token_id"],),
            )
            security.revoke_user_sessions(conn, row["user_id"])
            throttle.clear_failures(conn, _RESET_CODE_SCOPE, email_key)
            throttle.clear_failures(conn, _LOGIN_EMAIL_SCOPE, email_key)
    if failure is not None:
        raise failure
    return ok(None, 200, "Password reset successful")


@auth_bp.post("/logout")
@security.require_auth
def logout() -> tuple[Response, int]:
    # PIYA-305 AC1 wins over AC4: an expired/revoked token never reaches here, it gets 401.
    with db.transaction() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = now(), updated_at = now() WHERE token_hash = %s",
            (g.token_hash,),
        )
    return ok(None, 200, "Logged out")


@auth_bp.post("/change-password")
@security.require_auth
def change_password() -> tuple[Response, int]:
    body = json_body()
    current = require_str(body, "currentPassword")
    new = require_str(body, "newPassword")
    failure: ApiError | None = None
    with db.transaction() as conn:
        failure = check_current_password(conn, g.user.id, current)
        if failure is None:
            # Policy and hashing only after the current password verified, so a stolen token
            # cannot burn argon2 CPU; a policy error rolls back (no wrong guess to count).
            check_password_policy(new, "newPassword")
            conn.execute(
                "UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s",
                (security.hash_password(new), g.user.id),
            )
            security.revoke_user_sessions(conn, g.user.id, keep_token_hash=g.token_hash)
    if failure is not None:
        raise failure
    return ok(None, 200, "Password changed")
