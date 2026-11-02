"""Score library, results, edit and delete (PIYA-308, PIYA-103 by score, V2 B5, PIYA-309)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

import psycopg
from flask import Blueprint, Response, current_app, g, request

from backend import access, background, db, security
from backend.config import SETTINGS_KEY, Settings
from backend.envelope import ApiError, iso_z, ok
from backend.routes_jobs import job_ref
from backend.storage import get_storage
from backend.validation import clean_arranger, clean_title, json_body

LOG = logging.getLogger(__name__)
scores_bp = Blueprint("scores", __name__, url_prefix="/api/scores")

MAX_SEARCH_LENGTH = 100
_FINISHED = ("complete", "failed", "cancelled")
Conn = psycopg.Connection[dict[str, Any]]


def _settings() -> Settings:
    return cast(Settings, current_app.config[SETTINGS_KEY])


def score_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    """Library entry; optional fields appear only when present."""
    data: dict[str, Any] = {
        "scoreId": row["id"],
        "title": row["title"],
        "lastProcessedAt": iso_z(row["created_at"]),
        "pageCount": row["page_count"],
    }
    if row["last_accessed_at"] is not None:
        data["lastAccessedAt"] = iso_z(row["last_accessed_at"])
    if row["arranger"] is not None:
        data["arranger"] = row["arranger"]
    if row["thumbnail_key"] is not None:
        data["thumbnailUrl"] = get_storage().signed_url(row["thumbnail_key"])
    return data


@scores_bp.get("")
@security.require_auth
def library() -> tuple[Response, int]:
    search = request.args.get("search", "").strip()
    if len(search) > MAX_SEARCH_LENGTH:
        raise ApiError(400, "search_too_long", "search is too long", field="search")
    sql = "SELECT * FROM scores WHERE user_id = %s"
    params: list[Any] = [g.user.id]
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += " AND (title ILIKE %s ESCAPE '\\' OR arranger ILIKE %s ESCAPE '\\')"
        params += [f"%{escaped}%"] * 2
    sql += " ORDER BY COALESCE(last_accessed_at, created_at) DESC, id DESC"
    with db.transaction() as conn:
        rows = conn.execute(sql, params).fetchall()
    return ok({"scores": [score_entry(r) for r in rows]}, 200, "Score library retrieved")


@scores_bp.get("/<int:score_id>/result")
@security.require_auth
def result(score_id: int) -> tuple[Response, int]:
    ttl = _settings().media_url_ttl_seconds
    storage = get_storage()
    with db.transaction() as conn:
        score = access.owned_score(conn, score_id)
        job = conn.execute(
            "SELECT id FROM jobs WHERE score_id = %s AND user_id = %s AND status = 'complete'",
            (score_id, g.user.id),
        ).fetchone()
        job_id = job["id"] if job else None
        tracks = conn.execute(
            "SELECT voice, file_key FROM audio_tracks WHERE score_id = %s", (score_id,)
        ).fetchall()
        timing = conn.execute(
            "SELECT metadata_key FROM timing_metadata WHERE score_id = %s", (score_id,)
        ).fetchone()
        pages = conn.execute(
            "SELECT object_key, width, height FROM job_pages WHERE job_id = %s ORDER BY page_index",
            (job_id,),
        ).fetchall()
    data: dict[str, Any] = {
        "jobId": job_ref(job_id) if job_id is not None else None,
        "scoreId": score["id"],
        "title": score["title"],
        "tempoBpm": score["tempo_bpm"],
        "audioTracks": {
            t["voice"]: storage.signed_url(t["file_key"], ttl_seconds=ttl) for t in tracks
        },
        "scoreImages": [storage.signed_url(p["object_key"], ttl_seconds=ttl) for p in pages],
        "scoreImageSizes": [{"width": p["width"], "height": p["height"]} for p in pages],
        "timingMetadataUrl": (
            storage.signed_url(timing["metadata_key"], ttl_seconds=ttl) if timing else None
        ),
        "review": score["review"],
        "mutedMeasures": score["muted_measures"],
        "failedVoices": score["failed_voices"],
        "failedVoiceCauses": score["failed_voice_causes"],
    }
    if score["arranger"] is not None:
        data["arranger"] = score["arranger"]
    try:
        with db.transaction() as conn:
            conn.execute(
                "UPDATE scores SET last_accessed_at = now() WHERE id = %s AND user_id = %s",
                (score_id, g.user.id),
            )
    except psycopg.Error:  # AC8: a failed touch must never fail the read
        LOG.warning("last_accessed_at update failed score_id=%s", score_id, exc_info=True)
    return ok(data, 200, "Processed score result retrieved")


def _lock_score_and_jobs(conn: Conn, score_id: int) -> tuple[dict[str, Any], list[int]]:
    """ERD lock order: the score, then its jobs."""
    score = access.owned_score(conn, score_id, for_update=True)
    jobs = conn.execute(
        "SELECT id FROM jobs WHERE score_id = %s AND user_id = %s ORDER BY id FOR UPDATE",
        (score_id, g.user.id),
    ).fetchall()
    return score, [j["id"] for j in jobs]


def _unfinished_retakes(conn: Conn, job_ids: list[int]) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM jobs WHERE replaces_job_id = ANY(%s) AND user_id = %s "
        "AND status <> ALL(%s) ORDER BY id FOR UPDATE",
        (job_ids, g.user.id, list(_FINISHED)),
    ).fetchall()
    return [r["id"] for r in rows]


@scores_bp.patch("/<int:score_id>")
@security.require_auth
def edit(score_id: int) -> tuple[Response, int]:
    body = json_body()
    title = clean_title(body["title"]) if "title" in body else None
    has_arranger = "arranger" in body
    arranger = clean_arranger(body.get("arranger"))
    with db.transaction() as conn:
        score, job_ids = _lock_score_and_jobs(conn, score_id)
        if _unfinished_retakes(conn, job_ids):
            raise ApiError(409, "retake_in_progress", "A retake of this score is running")
        new_title = title if title is not None else score["title"]
        new_arranger = arranger if has_arranger else score["arranger"]
        row = conn.execute(
            "UPDATE scores SET title = %s, arranger = %s, updated_at = now() "
            "WHERE id = %s AND user_id = %s RETURNING *",
            (new_title, new_arranger, score_id, g.user.id),
        ).fetchone()
        conn.execute(
            "UPDATE jobs SET title = %s, arranger = %s WHERE score_id = %s AND user_id = %s",
            (new_title, new_arranger, score_id, g.user.id),
        )
    if row is None:
        raise RuntimeError("score update returned no row")
    return ok(score_entry(row), 200, "Score updated")


@scores_bp.delete("/<int:score_id>")
@security.require_auth
def delete(score_id: int) -> tuple[Response, int]:
    with db.transaction() as conn:
        score, job_ids = _lock_score_and_jobs(conn, score_id)
        retakes = _unfinished_retakes(conn, job_ids)
        if retakes:
            conn.execute(
                "UPDATE jobs SET status = 'cancelled', updated_at = now() WHERE id = ANY(%s)",
                (retakes,),
            )
        keys = [
            r["k"]
            for r in conn.execute(
                "SELECT file_key AS k FROM audio_tracks WHERE score_id = %(s)s "
                "UNION SELECT metadata_key FROM timing_metadata WHERE score_id = %(s)s "
                "UNION SELECT object_key FROM job_pages WHERE job_id = ANY(%(j)s)",
                {"s": score_id, "j": [*job_ids, *retakes]},
            ).fetchall()
        ]
        if score["thumbnail_key"] is not None:
            keys.append(score["thumbnail_key"])
        background.queue_deletion(conn, keys)
        conn.execute("DELETE FROM jobs WHERE id = ANY(%s) AND user_id = %s", (job_ids, g.user.id))
        conn.execute("DELETE FROM scores WHERE id = %s AND user_id = %s", (score_id, g.user.id))
    return ok({"scoreId": score_id}, 200, "Score deleted")
