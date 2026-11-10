"""Piano octave persistence (PIYA-321): GET/PUT ``/api/users/me/piano-settings``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from flask import Blueprint, Response, current_app, g, request

from backend import db, security, throttle
from backend.config import SETTINGS_KEY, Settings
from backend.envelope import ApiError, iso_z, ok
from backend.validation import json_body

piano_bp = Blueprint("piano", __name__, url_prefix="/api/users/me")

PIANO_BUCKET = "piano_settings"
_WINDOW_S = 60
MIN_OCTAVE = 2
MAX_OCTAVE = 6
_LOW_VOICES = {"tenor", "bass"}
_LOW_DEFAULT = 3
_DEFAULT = 4
_MAX_FUTURE = timedelta(minutes=5)


def default_octave(voice: str | None) -> int:
    """Voice-hint default: tenor/bass 3, everything else (including unknown or missing) 4."""
    return _LOW_DEFAULT if voice is not None and voice.strip().lower() in _LOW_VOICES else _DEFAULT


def _parse_client_time(raw: object) -> datetime:
    """Parse ``clientUpdatedAt``: timezone-aware ISO 8601, at most 5 minutes ahead of now."""
    bad = ApiError(400, "client_updated_at_invalid", "client_updated_at_invalid")
    if not isinstance(raw, str):
        raise bad
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        raise bad from None
    now = datetime.now(timezone.utc)
    if moment.tzinfo is None or moment > now + _MAX_FUTURE:
        raise bad
    # Clamp skew to server now so a fast-clock device cannot pin the stored value in the future.
    return min(moment.astimezone(timezone.utc), now)


def _parse_octave(body: dict[str, object]) -> int:
    if "octave" not in body:
        raise ApiError(400, "octave_missing", "octave_missing")
    octave = body["octave"]
    # bool is an int subclass; floats (even 4.0) are rejected as "not an integer".
    if not isinstance(octave, int) or isinstance(octave, bool):
        raise ApiError(400, "octave_invalid", "octave_invalid")
    if not MIN_OCTAVE <= octave <= MAX_OCTAVE:
        raise ApiError(400, "octave_out_of_range", "octave_out_of_range")
    return octave


def _count_hit(conn: Any) -> None:
    cfg = cast(Settings, current_app.config[SETTINGS_KEY])
    subject = security.keyed_hash(str(g.user.id))
    throttle.lock_subject(conn, PIANO_BUCKET, subject)
    retry = throttle.window_retry_after(
        conn, PIANO_BUCKET, subject, cfg.piano_settings_per_minute, _WINDOW_S
    )
    if retry is not None:
        raise throttle.too_many(retry)
    throttle.record_hit(conn, PIANO_BUCKET, subject)


def _payload(octave: int, updated_at: datetime | None) -> dict[str, object]:
    return {
        "octave": octave,
        "updatedAt": None if updated_at is None else iso_z(updated_at),
        "isDefault": updated_at is None,
    }


@piano_bp.get("/piano-settings")
@security.require_auth
def get_piano_settings() -> tuple[Response, int]:
    with db.transaction() as conn:
        _count_hit(conn)
        row = conn.execute(
            "SELECT octave, updated_at FROM piano_settings WHERE user_id = %s", (g.user.id,)
        ).fetchone()
    if row is None:
        return ok(_payload(default_octave(request.args.get("voice")), None), 200,
                  "Piano settings retrieved")
    return ok(_payload(row["octave"], row["updated_at"]), 200, "Piano settings retrieved")


@piano_bp.put("/piano-settings")
@security.require_auth
def put_piano_settings() -> tuple[Response, int]:
    body = json_body()
    octave = _parse_octave(body)
    client_time = _parse_client_time(body["clientUpdatedAt"]) if "clientUpdatedAt" in body else None
    with db.transaction() as conn:
        _count_hit(conn)
        # One statement so a burst of PUTs cannot interleave; the WHERE keeps a newer stored value.
        row = conn.execute(
            "INSERT INTO piano_settings (user_id, octave, updated_at)"
            " VALUES (%(u)s, %(o)s, COALESCE(%(t)s, now()))"
            " ON CONFLICT (user_id) DO UPDATE SET octave = EXCLUDED.octave,"
            " updated_at = EXCLUDED.updated_at"
            " WHERE piano_settings.updated_at <= EXCLUDED.updated_at"
            " RETURNING octave, updated_at",
            {"u": g.user.id, "o": octave, "t": client_time},
        ).fetchone()
        if row is None:  # stale write: report what is stored
            row = conn.execute(
                "SELECT octave, updated_at FROM piano_settings WHERE user_id = %s", (g.user.id,)
            ).fetchone()
    if row is None:
        raise RuntimeError("piano settings row vanished")
    return ok(_payload(row["octave"], row["updated_at"]), 200, "Piano settings saved")
