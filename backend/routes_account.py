"""Account info and deletion (PIYA-306, PIYA-307) plus the current-password gate shared with
change-password (PIYA-322)."""

from __future__ import annotations

from typing import cast

import psycopg.errors
from flask import Blueprint, Response, current_app, g

from backend import background, db, security, throttle
from backend.config import SETTINGS_KEY, Settings

from backend.envelope import ApiError, iso_z, ok
from backend.validation import MAX_PASSWORD_LENGTH, json_body, require_str

account_bp = Blueprint("account", __name__, url_prefix="/api/account")

# One bucket for change-password and delete-account: both are "prove you know the password"
# gates, so guesses against either must draw from the same budget.
CHANGE_PW_BUCKET = "change_pw"
_WRONG_PASSWORD = "Current password is incorrect"
_DELETE_ATTEMPTS = 2


def check_current_password(
    conn: security.Conn, user_id: int, password: str
) -> ApiError | None:
    """Throttle then verify the caller's current password inside the caller's transaction.

    Counts only wrong passwords. The caller must raise the returned error after the transaction
    block exits, otherwise the rollback would drop the recorded hit.

    Args:
        conn: Open transaction connection.
        user_id: Authenticated user.
        password: Password supplied in the request.

    Returns:
        429 ``rate_limited``, 403 ``invalid_current_password``, or None when verified.
    """
    cfg = cast(Settings, current_app.config[SETTINGS_KEY])
    key = security.keyed_hash(str(user_id))
    throttle.lock_subject(conn, CHANGE_PW_BUCKET, key)
    retry = throttle.window_retry_after(
        conn, CHANGE_PW_BUCKET, key, cfg.change_password_limit, cfg.change_password_window_s
    )
    if retry is not None:
        return throttle.too_many(retry)
    row = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
    valid = False
    if row is None or len(password) > MAX_PASSWORD_LENGTH:
        security.verify_dummy()
    else:
        valid = security.verify_password(password, row["password_hash"])
    if valid:
        return None
    throttle.record_hit(conn, CHANGE_PW_BUCKET, key)
    return ApiError(403, "invalid_current_password", _WRONG_PASSWORD)


@account_bp.get("")
@security.require_auth
def account_info() -> tuple[Response, int]:
    with db.transaction() as conn:
        row = conn.execute("SELECT created_at FROM users WHERE id = %s", (g.user.id,)).fetchone()
    if row is None:
        raise RuntimeError("authenticated user vanished")
    data = {
        "email": g.user.email,
        "role": g.user.role,
        "accountCreatedAt": iso_z(row["created_at"]),
    }
    return ok(data, 200, "Account info retrieved")


@account_bp.delete("")
@security.require_auth
def delete_account() -> tuple[Response, int]:
    password = require_str(json_body(), "password")
    failure: ApiError | None = None
    # A purge can deadlock against the worker finishing a job for the same user (opposite row
    # order); the whole transaction rolled back, so one retry is safe and turns a rare 500 into 200.
    for attempt in range(_DELETE_ATTEMPTS):
        try:
            with db.transaction() as conn:
                failure = check_current_password(conn, g.user.id, password)
                if failure is None:
                    # Inline so users.email UNIQUE frees at once; the background loop stays as a safety
                    # net. Sessions cascade with the user row. Any failure rolls the whole delete back.
                    background.purge_user(conn, g.user.id)
            break
        except psycopg.errors.DeadlockDetected:
            if attempt == _DELETE_ATTEMPTS - 1:
                raise
    if failure is not None:
        raise failure
    return ok(None, 200, "Account deleted")
