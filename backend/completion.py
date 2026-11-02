"""Atomic job completion (PIYA-321) and failure marking, used by the operator CLI."""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from PIL import Image
from psycopg.types.json import Jsonb

from backend import background

Conn = psycopg.Connection[dict[str, Any]]

THUMBNAIL_LONG_SIDE_PX = 400
THUMBNAIL_JPEG_QUALITY = 80
_FINISHED = ("complete", "failed", "cancelled")
_SCORE_COPY_COLS = (
    "title, arranger, page_count, tempo_bpm, tempo_source, key_signature, time_signature"
)


def make_thumbnail(page_jpeg: bytes) -> bytes:
    """JPEG whose long side is THUMBNAIL_LONG_SIDE_PX (never upscaled)."""
    with Image.open(io.BytesIO(page_jpeg)) as img:
        thumb = img.convert("RGB")
    thumb.thumbnail((THUMBNAIL_LONG_SIDE_PX, THUMBNAIL_LONG_SIDE_PX))
    out = io.BytesIO()
    thumb.save(out, "JPEG", quality=THUMBNAIL_JPEG_QUALITY)
    return out.getvalue()


def _cancel(conn: Conn, job_id: int) -> None:
    conn.execute("UPDATE jobs SET status = 'cancelled' WHERE id = %s", (job_id,))


def complete_job(
    conn: Conn,
    job_id: int,
    *,
    audio_keys: Mapping[str, str],
    timing_key: str,
    failed_voices: Sequence[str],
    failed_voice_causes: Mapping[str, str],
    review: Mapping[str, object],
    muted_measures: Sequence[Mapping[str, object]],
    thumbnail_key: str | None,
) -> int | None:
    """Turn a job into a finished score in the caller's transaction (PIYA-321 AC4/AC5).

    Lock order follows the ERD: score, then new job, then old job. The caller owns the transaction
    so a failure anywhere rolls the whole completion back.

    Returns:
        The score id, or None when the job was cancelled, purged, or its retake target score is
        gone; the caller must then delete the objects it uploaded.
    """
    # Unlocked peek only to find which score to lock first.
    peek = conn.execute("SELECT replaces_job_id FROM jobs WHERE id = %s", (job_id,)).fetchone()
    if peek is None:
        return None
    old_peek = None
    if peek["replaces_job_id"] is not None:
        old_peek = conn.execute(
            "SELECT score_id FROM jobs WHERE id = %s", (peek["replaces_job_id"],)
        ).fetchone()
    old_score_id = old_peek["score_id"] if old_peek else None
    old_score = None
    if old_score_id is not None:
        old_score = conn.execute("SELECT * FROM scores WHERE id = %s FOR UPDATE", (old_score_id,)).fetchone()
    job = conn.execute("SELECT * FROM jobs WHERE id = %s FOR UPDATE", (job_id,)).fetchone()
    if job is None or job["status"] == "cancelled":
        return None
    old_job = None
    if job["replaces_job_id"] is not None:
        old_job = conn.execute("SELECT * FROM jobs WHERE id = %s FOR UPDATE", (job["replaces_job_id"],)).fetchone()
    retake_of_score = old_job is not None and old_job["status"] == "complete"
    if retake_of_score and (old_score is None or old_job is None or old_job["score_id"] != old_score["id"]):
        _cancel(conn, job_id)  # the score was deleted while the retake ran
        return None

    fields = (
        job["title"], job["arranger"], job["page_count"], job["tempo_bpm"], job["tempo_source"],
        job["key_signature"], job["time_signature"], thumbnail_key,
        Jsonb(dict(review)), Jsonb(list(muted_measures)), Jsonb(list(failed_voices)),
        Jsonb(dict(failed_voice_causes)),
    )
    if retake_of_score and old_score is not None and old_job is not None:
        score_id: int = old_score["id"]
        conn.execute(
            f"UPDATE scores SET ({_SCORE_COPY_COLS}, thumbnail_key, review, muted_measures, "
            "failed_voices, failed_voice_causes) = (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "WHERE id = %s",
            (*fields, score_id),
        )
        old_keys = [
            r["k"]
            for r in conn.execute(
                "SELECT file_key AS k FROM audio_tracks WHERE score_id = %(s)s "
                "UNION SELECT metadata_key FROM timing_metadata WHERE score_id = %(s)s "
                "UNION SELECT object_key FROM job_pages WHERE job_id = %(j)s",
                {"s": score_id, "j": old_job["id"]},
            ).fetchall()
        ]
        if old_score["thumbnail_key"] is not None:
            old_keys.append(old_score["thumbnail_key"])
        background.queue_deletion(conn, old_keys)
        conn.execute("DELETE FROM audio_tracks WHERE score_id = %s", (score_id,))
        conn.execute("DELETE FROM timing_metadata WHERE score_id = %s", (score_id,))
        conn.execute("DELETE FROM job_pages WHERE job_id = %s", (old_job["id"],))
        conn.execute(
            "UPDATE jobs SET superseded_by_job_id = %s, score_id = NULL WHERE id = %s",
            (job_id, old_job["id"]),
        )
    else:
        row = conn.execute(
            f"INSERT INTO scores (user_id, {_SCORE_COPY_COLS}, thumbnail_key, review, muted_measures, "
            "failed_voices, failed_voice_causes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (job["user_id"], *fields),
        ).fetchone()
        if row is None:
            raise RuntimeError("score insert returned no row")
        score_id = row["id"]

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO audio_tracks (score_id, voice, file_key) VALUES (%s, %s, %s)",
            [(score_id, voice, key) for voice, key in audio_keys.items()],
        )
    conn.execute("INSERT INTO timing_metadata (score_id, metadata_key) VALUES (%s, %s)", (score_id, timing_key))
    conn.execute(
        "UPDATE jobs SET status = 'complete', score_id = %s, completed_at = now(), percent_complete = 100, "
        "failed_voices = %s, failed_voice_causes = %s WHERE id = %s",
        (score_id, Jsonb(list(failed_voices)), Jsonb(dict(failed_voice_causes)), job_id),
    )
    new_keys = [*audio_keys.values(), timing_key] + ([thumbnail_key] if thumbnail_key else [])
    background.release_keys(conn, new_keys)
    return score_id


def fail_job(conn: Conn, job_id: int, reason: str, page_index: int | None) -> None:
    """Mark an unfinished job failed; a finished or cancelled job is left alone."""
    conn.execute(
        "UPDATE jobs SET status = 'failed', failure_reason = %s, failure_page_index = %s "
        "WHERE id = %s AND status <> ALL(%s)",
        (reason, page_index, job_id, list(_FINISHED)),
    )
