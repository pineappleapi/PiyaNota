"""Background work: durable storage-deletion queue, account purge, expiry pruning, and the loop."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

import psycopg
from flask import Flask

from backend import db
from backend.config import SETTINGS_KEY, Settings
from backend.logutil import describe_exception
from backend.storage import Storage

LOG = logging.getLogger(__name__)

BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 3600
RESERVE_GRACE_S = 3600
THROTTLE_HIT_MAX_AGE_S = 3600
STALE_ROW_GRACE_S = 86400
BACKOFF_IDLE_S = 86400
Conn = psycopg.Connection[dict[str, Any]]


def queue_deletion(conn: Conn, keys: Iterable[str]) -> None:
    """Insert due deletion rows inside the caller's transaction."""
    rows = [(k,) for k in keys]
    if rows:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO storage_deletions (object_key) VALUES (%s)", rows)


def reserve_keys(keys: Iterable[str]) -> None:
    """Commit deletion rows for keys about to be uploaded, due in an hour.

    If the process dies between upload and the commit that references the key, the queue deletes
    the orphan; the commit that references the key calls release_keys.
    """
    rows = [(k, RESERVE_GRACE_S) for k in keys]
    if not rows:
        return
    with db.transaction() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO storage_deletions (object_key, next_attempt_at) "
            "VALUES (%s, now() + make_interval(secs => %s))",
            rows,
        )


def release_keys(conn: Conn, keys: Iterable[str]) -> None:
    """Drop reservations for keys that are now referenced, in the referencing transaction."""
    key_list = list(keys)
    if key_list:
        conn.execute("DELETE FROM storage_deletions WHERE object_key = ANY(%s)", (key_list,))


def run_deletions(storage: Storage, limit: int = 100) -> int:
    """Delete due objects from storage, retrying failures with capped exponential backoff.

    One transaction per batch: rows stay locked (SKIP LOCKED) while storage is called, which is
    acceptable at this scale and keeps concurrent workers from double-deleting.

    Returns:
        Number of objects removed.
    """
    done = 0
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT id, object_key, attempts FROM storage_deletions "
            "WHERE next_attempt_at <= now() ORDER BY next_attempt_at, id LIMIT %s "
            "FOR UPDATE SKIP LOCKED",
            (limit,),
        ).fetchall()
        for row in rows:
            try:
                storage.delete(row["object_key"])
            except Exception as exc:  # noqa: BLE001 - any backend failure is retried, not fatal
                attempts = row["attempts"] + 1
                delay = min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2**attempts)
                # Type name only: messages may carry signed URLs.
                conn.execute(
                    "UPDATE storage_deletions SET attempts = %s, last_error = %s, "
                    "next_attempt_at = now() + make_interval(secs => %s) WHERE id = %s",
                    (attempts, type(exc).__name__, delay, row["id"]),
                )
            else:
                conn.execute("DELETE FROM storage_deletions WHERE id = %s", (row["id"],))
                done += 1
    return done


_USER_KEYS_SQL = """
SELECT jp.object_key AS k FROM job_pages jp JOIN jobs j ON j.id = jp.job_id WHERE j.user_id = %(u)s
UNION SELECT thumbnail_key FROM scores WHERE user_id = %(u)s AND thumbnail_key IS NOT NULL
UNION SELECT a.file_key FROM audio_tracks a JOIN scores s ON s.id = a.score_id WHERE s.user_id = %(u)s
UNION SELECT t.metadata_key FROM timing_metadata t JOIN scores s ON s.id = t.score_id WHERE s.user_id = %(u)s
"""


def run_purges(storage: Storage) -> int:
    """Hard-delete every account marked deleted, queueing its objects for removal.

    One transaction per user, so a failure leaves that account marked for the next run.
    ``storage`` is accepted for loop symmetry; objects go through the durable queue instead.

    Returns:
        Number of accounts purged.
    """
    with db.transaction() as conn:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM users WHERE deleted_at IS NOT NULL ORDER BY id"
            ).fetchall()
        ]
    purged = 0
    for user_id in ids:
        try:
            with db.transaction() as conn:
                # Lock so two loops (or workers) cannot both purge this user.
                locked = conn.execute(
                    "SELECT id FROM users WHERE id = %s AND deleted_at IS NOT NULL "
                    "FOR UPDATE SKIP LOCKED",
                    (user_id,),
                ).fetchone()
                if locked is None:
                    continue
                keys = [r["k"] for r in conn.execute(_USER_KEYS_SQL, {"u": user_id}).fetchall()]
                queue_deletion(conn, keys)
                conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
                conn.execute(
                    "INSERT INTO purge_log (user_ref, completed_at) VALUES (%s, now())", (user_id,)
                )
        except Exception as exc:  # noqa: BLE001 - one user's failure must not block the others
            LOG.error("account purge failed user_ref=%s (%s)", user_id, type(exc).__name__)
            continue
        LOG.info("account purge complete user_ref=%s", user_id)
        purged += 1
    return purged


def run_prune(conn: Conn, hit_max_age_s: int = THROTTLE_HIT_MAX_AGE_S) -> int:
    """Delete expired throttle, session and reset-token rows; returns rows removed.

    Args:
        conn: Connection inside the caller's transaction.
        hit_max_age_s: Age past which throttle hits are dead; must cover the longest window.
    """
    grace = STALE_ROW_GRACE_S
    statements: tuple[tuple[str, int], ...] = (
        ("DELETE FROM throttle_hits WHERE created_at < now() - make_interval(secs => %(s)s)",
         hit_max_age_s),
        ("DELETE FROM sessions WHERE expires_at < now() - make_interval(secs => %(s)s) "
         "OR revoked_at < now() - make_interval(secs => %(s)s)", grace),
        ("DELETE FROM password_reset_tokens WHERE expires_at < now() - make_interval(secs => %(s)s) "
         "OR used_at < now() - make_interval(secs => %(s)s)", grace),
        ("DELETE FROM throttle_backoff WHERE last_failure_at < now() - make_interval(secs => %(s)s)",
         BACKOFF_IDLE_S),
    )
    return sum(conn.execute(sql, {"s": secs}).rowcount for sql, secs in statements)


def start_loop(app: Flask) -> threading.Thread:
    """Start the daemon thread that runs purge, deletion and prune every interval."""
    cfg: Settings = app.config[SETTINGS_KEY]
    interval = cfg.background_interval_s
    hit_max_age_s = max(
        cfg.login_ip_window_s,
        cfg.signup_ip_window_s,
        cfg.change_password_window_s,
        THROTTLE_HIT_MAX_AGE_S,  # hourly reset buckets
    )

    def _step(name: str, fn: Callable[[], object]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - the loop must survive any step failure
            LOG.error("background %s failed: %s", name, describe_exception(exc))

    def _prune() -> None:
        with db.transaction() as conn:
            run_prune(conn, hit_max_age_s)

    def _loop() -> None:
        storage: Storage = app.extensions["storage"]
        while True:
            with app.app_context():
                _step("purges", lambda: run_purges(storage))
                _step("deletions", lambda: run_deletions(storage))
                _step("prune", _prune)
            time.sleep(interval)

    thread = threading.Thread(target=_loop, name="piya-background", daemon=True)
    thread.start()
    return thread
