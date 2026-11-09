"""Password hashing, opaque session tokens, the ``require_auth`` decorator and keyed hashing."""

from __future__ import annotations

import functools
import hashlib
import hmac
import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar, cast

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import current_app, g, request

from backend import db
from backend.config import SETTINGS_KEY, Settings
from backend.envelope import ApiError

LOG = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])
Conn = psycopg.Connection[dict[str, Any]]

TOKEN_PREFIX = "sess_"
_TOKEN_BYTES = 32
_BEARER = "bearer "
_PARALLELISM = 1
# The instance has 512 MB and each hash can use argon2_memory_kib, so cap concurrent hashes.
_MAX_CONCURRENT_HASHES = 2
HASH_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENT_HASHES)
_DUMMY_PASSWORD = "dummy-password-for-timing"


@dataclass(frozen=True)
class AuthUser:
    """The authenticated caller, as read from the database on this request."""

    id: int
    email: str
    role: str


def _settings() -> Settings:
    return cast(Settings, current_app.config[SETTINGS_KEY])


def _hasher() -> PasswordHasher:
    cfg = _settings()
    return PasswordHasher(
        time_cost=cfg.argon2_time_cost,
        memory_cost=cfg.argon2_memory_kib,
        parallelism=_PARALLELISM,
    )


def hash_password(password: str) -> str:
    """Hash with argon2id at the configured cost; the salt is random per call."""
    hasher = _hasher()
    with HASH_SEMAPHORE:
        return hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    """Return True when ``password`` matches ``stored``; a mismatch or malformed hash is False."""
    hasher = _hasher()
    with HASH_SEMAPHORE:
        try:
            return hasher.verify(stored, password)
        except VerifyMismatchError:
            return False
        except (VerificationError, InvalidHashError):
            # Message only: no password, hash or email may reach the logs.
            LOG.warning("stored password hash unreadable")
            return False


_dummy_hash: str | None = None


def needs_rehash(stored: str) -> bool:
    """True when ``stored`` was made with weaker params than the current settings."""
    return _hasher().check_needs_rehash(stored)


def verify_dummy() -> None:
    """Burn one argon2 verify so unknown-email logins take as long as real ones."""
    global _dummy_hash
    if _dummy_hash is None:
        # Built lazily because the cost params come from the app's settings.
        _dummy_hash = hash_password(_DUMMY_PASSWORD)
    verify_password(_DUMMY_PASSWORD, _dummy_hash)


def token_hash(token: str) -> bytes:
    """SHA-256 of a session token; only this is stored, so a DB leak yields no usable tokens."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def keyed_hash(value: str) -> str:
    """HMAC-SHA256 hex under ``log_hash_key``, for log lines and throttle keys (no raw PII)."""
    return hmac.new(_settings().log_hash_key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_session(conn: Conn, user_id: int) -> tuple[str, datetime]:
    """Create a session row; return the plaintext token (shown once) and its expiry."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(days=_settings().session_ttl_days)
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (user_id, token_hash(token), expires_at),
    )
    return token, expires_at


def revoke_user_sessions(
    conn: Conn, user_id: int, *, keep_token_hash: bytes | None = None
) -> None:
    """Revoke the user's live sessions, optionally sparing the caller's own."""
    conn.execute(
        "UPDATE sessions SET revoked_at = now(), updated_at = now() "
        "WHERE user_id = %s AND revoked_at IS NULL "
        "AND (%s::bytea IS NULL OR token_hash <> %s::bytea)",
        (user_id, keep_token_hash, keep_token_hash),
    )


def client_ip() -> str:
    """Client address after ProxyFix has applied the trusted proxy count."""
    return request.remote_addr or "unknown"


def _unauthorized() -> ApiError:
    # One shared error for every failure mode so responses cannot be used to probe tokens.
    return ApiError(401, "unauthorized", "Unauthorized")


def require_auth(view: F) -> F:
    """Authenticate the Bearer token and set ``g.user`` / ``g.token_hash``.

    The token is read only from the Authorization header, never the query string.

    Raises:
        ApiError: 401 ``unauthorized`` for a missing, unknown, expired or revoked token, or a
            deleted user.
    """

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        header = request.headers.get("Authorization", "")
        if not header.lower().startswith(_BEARER):
            raise _unauthorized()
        token = header[len(_BEARER):].strip()
        if not token:
            raise _unauthorized()
        digest = token_hash(token)
        with db.transaction() as conn:
            row = conn.execute(
                "SELECT u.id, u.email, u.role FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > now() "
                "AND u.deleted_at IS NULL",
                (digest,),
            ).fetchone()
        if row is None:
            raise _unauthorized()
        g.user = AuthUser(id=row["id"], email=row["email"], role=row["role"])
        g.token_hash = digest
        return view(*args, **kwargs)

    return cast(F, wrapper)
