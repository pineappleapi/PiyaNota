"""Score upload intake: POST /api/jobs (images) and POST /api/jobs/pdf (PIYA-101, 310, 320, 323).

Error precedence (PIYA-101 AC9) is implemented by the order of the steps in ``_submit``: 401,
replay of a known ``clientSubmissionId``, 409 submission_cancelled, 429 rate_limited, 413, 400 field errors, 400 input-shape
errors, 415, 422, 400 too_many_pages, retake checks, 409 score_limit_reached, 429 too_many_active_jobs, 429 queue_full.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Literal, cast

import psycopg
from flask import Blueprint, Response, current_app, g, request
from werkzeug.datastructures import FileStorage, MultiDict
from werkzeug.exceptions import RequestEntityTooLarge

from backend import access, background, db, security, standardize, throttle
from backend.config import SETTINGS_KEY, Settings
from backend.envelope import ApiError, iso_z, ok
from backend.failure_codes import failure_code
from backend.logutil import log_event
from backend.standardize import MAX_PDF_PAGES, StandardPage
from backend.storage import get_storage, new_key
from backend.validation import (
    ScoreMetadata,
    parse_client_submission_id,
    parse_job_ref,
    parse_score_metadata,
)

LOG = logging.getLogger(__name__)
jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

SUBMIT_BUCKET = "submit"
SUBMIT_WINDOW_S = 3600
QUEUE_FULL_RETRY_AFTER_S = 600
ACTIVE_JOBS_RETRY_AFTER_S = 60
STATUS_READ_BUCKET = "status_read"
STATUS_READ_WINDOW_S = 60
LIST_READ_BUCKET = "jobs_list"
CANCEL_SUBMISSION_BUCKET = "cancel_submission"
SNIFF_BYTES = 16
MSG_IMAGES = "Score submitted for processing"
MSG_PDF = "PDF rasterized and submitted for processing"
_IN_FLIGHT = "jobs_one_retake_in_flight"
_CSID_INDEX = "jobs_user_client_submission_idx"
_FINISHED = ("complete", "failed", "cancelled")
_UNREADABLE = "unreadable"
MAX_SCORES_PER_USER = 20
LIST_WINDOW_DAYS = 7  # finished jobs older than this drop off the list; active jobs never do
LIST_MAX_ITEMS = 50  # hard cap; well above MAX_SCORES_PER_USER live scores plus failed/cancelled jobs
Source = Literal["images", "pdf"]
Conn = psycopg.Connection[dict[str, Any]]

__all__ = ["jobs_bp", "job_ref", "parse_job_ref", "create_job", "submitted_payload"]


def job_ref(job_id: int) -> str:
    """The app-facing job reference, ``"job_<id>"``."""
    return f"job_{job_id}"


def submitted_payload(job_row: Mapping[str, Any]) -> dict[str, Any]:
    """The 202 ``data`` object; optional metadata appears only when present."""
    data: dict[str, Any] = {
        "jobId": job_ref(job_row["id"]),
        "userId": job_row["user_id"],
        "pageCount": job_row["page_count"],
        "status": "queued",
        "submittedAt": iso_z(job_row["created_at"]),
        "title": job_row["title"],
        "tempoBpm": job_row["tempo_bpm"],
    }
    for key, column in (("arranger", "arranger"), ("keySignature", "key_signature"),
                        ("timeSignature", "time_signature")):
        if job_row[column] is not None:
            data[key] = job_row[column]
    if job_row["replaces_job_id"] is not None:
        data["replacesJobId"] = job_ref(job_row["replaces_job_id"])
    return data


def _settings() -> Settings:
    return cast(Settings, current_app.config[SETTINGS_KEY])


def find_replay(user_id: int, client_id: uuid.UUID | None) -> dict[str, Any] | None:
    """The caller's existing job for this idempotency key, if any."""
    if client_id is None:
        return None
    with db.transaction() as conn:
        row: dict[str, Any] | None = conn.execute(
            "SELECT * FROM jobs WHERE user_id = %s AND client_submission_id = %s", (user_id, client_id)
        ).fetchone()
    return row


def _accepted(job_row: Mapping[str, Any]) -> tuple[Response, int]:
    message = MSG_PDF if job_row["source"] == "pdf" else MSG_IMAGES
    return ok(submitted_payload(job_row), 202, message)


def _check_retake(conn: Conn, old_id: int, *, lock: bool) -> str:
    """AC12 checks in the required order; returns the old job's status.

    Raises:
        ApiError: 404 ``job_not_found``, 409 ``retake_in_progress``, 409 ``not_retakeable``.
    """
    old = access.owned_job(conn, old_id, for_update=lock)
    if old["score_id"] is not None and conn.execute(
        "SELECT 1 FROM scores WHERE id = %s AND deleted_at IS NULL", (old["score_id"],)
    ).fetchone() is None:
        raise ApiError(404, "job_not_found", "Job not found")  # its score is in the recovery window
    running = conn.execute(
        "SELECT 1 FROM jobs WHERE replaces_job_id = %s AND status <> ALL(%s)", (old_id, list(_FINISHED))
    ).fetchone()
    if running is not None:
        raise ApiError(409, "retake_in_progress", "A retake of this job is already running")
    causes = old["failed_voice_causes"]
    unreadable = isinstance(causes, dict) and _UNREADABLE in causes.values()
    retakeable = old["superseded_by_job_id"] is None and (
        old["status"] == "failed"  # any failure reason: the app lets a failed row be retaken
        or (old["status"] == "complete" and unreadable)
    )
    if not retakeable:
        raise ApiError(409, "not_retakeable", "This job cannot be retaken")
    status: str = old["status"]
    return status


def _check_score_limit(conn: Conn, user_id: int) -> None:
    """Raise 409 when live scores plus converting jobs reach the cap.

    One statement: completion flips a job to complete and inserts its score without our lock, so
    two separate counts could each miss it. A retake of a complete job is excluded because its
    score is already counted; a retake of a failed job is not, since it inserts a new score.

    Raises:
        ApiError: 409 ``score_limit_reached``.
    """
    row = conn.execute(
        "SELECT (SELECT count(*) FROM scores WHERE user_id = %(u)s AND deleted_at IS NULL)"
        " + (SELECT count(*) FROM jobs j LEFT JOIN jobs old ON old.id = j.replaces_job_id"
        "    WHERE j.user_id = %(u)s AND j.status <> ALL(%(f)s)"
        "    AND COALESCE(old.status, '') <> 'complete') AS n",
        {"u": user_id, "f": list(_FINISHED)},
    ).fetchone()
    if row is not None and row["n"] >= MAX_SCORES_PER_USER:
        raise ApiError(409, "score_limit_reached", "You have reached the maximum number of scores",
                       limit=MAX_SCORES_PER_USER)


def _check_active_cap(conn: Conn, user_id: int, client_id: uuid.UUID | None, limit: int) -> None:
    """Raise 429 when the user already has ``limit`` queued or running jobs.

    A submit repeating an existing clientSubmissionId is a replay, not a new job, so it is never
    counted against the cap (create_job's unique index then returns the existing job).

    Raises:
        ApiError: 429 ``too_many_active_jobs``.
    """
    if client_id is not None and conn.execute(
        "SELECT 1 FROM jobs WHERE user_id = %s AND client_submission_id = %s", (user_id, client_id)
    ).fetchone() is not None:
        return
    row = conn.execute(
        "SELECT count(*) AS n FROM jobs WHERE user_id = %s AND status <> ALL(%s)", (user_id, list(_FINISHED))
    ).fetchone()
    if row is not None and row["n"] >= limit:
        raise ApiError(429, "too_many_active_jobs", "You already have the maximum number of conversions running",
                       limit=limit, retry_after=ACTIVE_JOBS_RETRY_AFTER_S)


def _check_not_cancelled(conn: Conn, user_id: int, client_id: uuid.UUID | None) -> None:
    """Raise 409 when the app cancelled this clientSubmissionId before the job existed.

    Raises:
        ApiError: 409 ``submission_cancelled``.
    """
    if client_id is not None and conn.execute(
        "SELECT 1 FROM cancelled_submissions WHERE user_id = %s AND client_submission_id = %s",
        (user_id, client_id),
    ).fetchone() is not None:
        raise ApiError(409, "submission_cancelled", "This submission was cancelled")


def _discard(keys: list[str]) -> None:
    """Best-effort removal of uploaded objects after a failed creation.

    Reservations are dropped only when every delete succeeded; otherwise they stay and the
    durable queue removes the orphans within the grace period.
    """
    storage = get_storage()
    try:
        for key in keys:
            storage.delete(key)
    except Exception as exc:  # noqa: BLE001 - cleanup must never mask the original error
        LOG.error("page cleanup failed (%s); reservations will purge them", type(exc).__name__)
        return
    with db.transaction() as conn:
        background.release_keys(conn, keys)


def create_job(
    user_id: int,
    meta: ScoreMetadata,
    pages: list[StandardPage],
    source: Source,
    client_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Store the pages, then insert the job and its page rows in one transaction.

    Keys are reserved before the first upload so a crash cannot orphan objects, and released in
    the creating transaction. On any failure the uploaded objects are removed (PIYA-101 AC11).
    If a concurrent request with the same ``client_id`` wins the race, its job is returned and
    this request's objects are queued for deletion.

    Returns:
        The inserted ``jobs`` row, or the winning row of an idempotent replay.

    Raises:
        ApiError: 429 ``rate_limited`` (re-checked under lock), 404/409 retake errors.
    """
    cfg = _settings()
    storage = get_storage()
    keys = [new_key("pages", "jpg") for _ in pages]
    background.reserve_keys(keys)
    try:
        for key, page in zip(keys, pages):
            storage.put(key, page.jpeg, "image/jpeg")
        with db.transaction() as conn:
            # Authoritative limit check: the early one in _submit is lock-free and fail-fast only.
            subject = security.keyed_hash(str(user_id))
            throttle.lock_subject(conn, SUBMIT_BUCKET, subject)
            retry = throttle.window_retry_after(
                conn, SUBMIT_BUCKET, subject, cfg.submit_limit_per_hour, SUBMIT_WINDOW_S
            )
            if retry is not None:
                raise throttle.too_many(retry)
            _check_not_cancelled(conn, user_id, client_id)  # the cancel endpoint takes the same lock
            old_status = None
            if meta.replaces_job_id is not None:
                old_status = _check_retake(conn, meta.replaces_job_id, lock=True)
            if old_status != "complete":  # replacing a complete score never adds one
                _check_score_limit(conn, user_id)
            _check_active_cap(conn, user_id, client_id, cfg.max_active_jobs_per_user)  # under the user lock
            row = conn.execute(
                "INSERT INTO jobs (user_id, status, source, page_count, title, arranger, tempo_bpm, "
                "tempo_source, key_signature, time_signature, replaces_job_id, client_submission_id) "
                "VALUES (%s, 'queued', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (user_id, source, len(pages), meta.title, meta.arranger, meta.tempo_bpm,
                 meta.tempo_source, meta.key_signature, meta.time_signature, meta.replaces_job_id,
                 client_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("job insert returned no row")
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO job_pages (job_id, page_index, object_key, width, height) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    [(row["id"], i, k, p.width, p.height) for i, (k, p) in enumerate(zip(keys, pages))],
                )
            if old_status == "failed":  # a completed job is superseded when the retake completes
                conn.execute(
                    "UPDATE jobs SET superseded_by_job_id = %s WHERE id = %s", (row["id"], meta.replaces_job_id)
                )
            throttle.record_hit(conn, SUBMIT_BUCKET, subject)
            background.release_keys(conn, keys)
    except psycopg.errors.UniqueViolation as exc:
        index = exc.diag.constraint_name
        if index == _CSID_INDEX and client_id is not None:
            with db.transaction() as conn:
                # Release first: reservations and queued deletions share one table and key.
                background.release_keys(conn, keys)
                background.queue_deletion(conn, keys)
            existing = find_replay(user_id, client_id)
            if existing is not None:
                return existing
        _discard(keys)
        if index == _IN_FLIGHT:
            raise ApiError(409, "retake_in_progress", "A retake of this job is already running") from None
        raise
    except BaseException:
        _discard(keys)
        raise
    LOG.info("job submitted job_id=%s user_id=%s page_count=%s at=%s",
             row["id"], user_id, len(pages), iso_z(row["created_at"]))
    return cast(dict[str, Any], row)


def _head(part: FileStorage) -> bytes:
    head = part.stream.read(SNIFF_BYTES)
    part.stream.seek(0)
    return head


def _size(part: FileStorage) -> int:
    part.stream.seek(0, 2)
    size = part.stream.tell()
    part.stream.seek(0)
    return size


def _collect_images(parts: list[FileStorage], cfg: Settings) -> list[StandardPage]:
    """Sniff, then decode and standardize one page at a time (415, then 422, then page cap)."""
    kinds = [standardize.sniff(_head(p)) for p in parts]
    if "pdf" in kinds:
        if any(k in ("jpeg", "png") for k in kinds):
            raise ApiError(400, "mixed_input_types", "A PDF cannot be combined with images")
    for index, kind in enumerate(kinds):
        if kind not in ("jpeg", "png"):
            raise ApiError(415, "unsupported_file_type", "Only JPEG and PNG pages are accepted",
                           page_index=index)
    if len(parts) > MAX_PDF_PAGES:
        # Header-only so a hostile 100-page request cannot make us decode 100 images, yet a
        # corrupt part still reports 422 before too_many_pages.
        for index, part in enumerate(parts):
            standardize.verify_image(part.stream.read(), index)
        raise ApiError(400, "too_many_pages", f"A score may have at most {MAX_PDF_PAGES} pages")
    return [
        standardize.standardize_image(
            part.stream.read(), index, max_pixels=cfg.max_image_pixels, max_side_px=cfg.standard_max_side_px
        )
        for index, part in enumerate(parts)
    ]


def _collect_pdf(part: FileStorage, cfg: Settings) -> list[StandardPage]:
    pages: list[StandardPage] = []
    for index, image in enumerate(
        standardize.iter_pdf_pages(part.stream.read(), max_side_px=cfg.standard_max_side_px, dpi=cfg.pdf_render_dpi)
    ):
        pages.append(standardize.standardize_pil(image, index, max_side_px=cfg.standard_max_side_px))
    return pages


def _body_too_large() -> bool:
    """Declared body size over the limit; checked up front because werkzeug leaks the temp files
    of a multipart parse it aborts half-way."""
    length = request.content_length
    return length is not None and length > _settings().max_content_length


def _early_client_id() -> tuple[uuid.UUID | None, ApiError | None, bool]:
    """Parse ``clientSubmissionId`` for the replay lookup without letting its errors jump the queue.

    A malformed id (or an oversize body, which must lose to 429 in the precedence order) is
    deferred: the caller raises it at its proper step. The third item is True when the body is
    too large; the stream is then consumed, so the caller must not parse it again.
    """
    if _body_too_large():
        return None, None, True
    try:
        return parse_client_submission_id(request.form), None, False
    except ApiError as exc:
        return None, exc, False
    except RequestEntityTooLarge:
        return None, None, True


def _submit(source: Source) -> tuple[Response, int]:
    cfg = _settings()
    user_id: int = g.user.id
    client_id, client_id_error, body_too_large = _early_client_id()
    replay = find_replay(user_id, client_id)
    if replay is not None:
        if replay["status"] == "cancelled":  # a late retry must not look like a live 202
            raise ApiError(409, "submission_cancelled", "This submission was cancelled")
        return _accepted(replay)
    with db.transaction() as conn:  # before any body parsing: a cancelled upload costs nothing
        _check_not_cancelled(conn, user_id, client_id)

    subject = security.keyed_hash(str(user_id))
    with db.transaction() as conn:
        retry = throttle.window_retry_after(
            conn, SUBMIT_BUCKET, subject, cfg.submit_limit_per_hour, SUBMIT_WINDOW_S
        )
    if retry is not None:
        raise throttle.too_many(retry)

    if body_too_large:
        raise ApiError(413, "request_too_large", "Request Entity Too Large")
    form = cast("MultiDict[str, str]", request.form)
    image_parts = request.files.getlist("pages")
    pdf_parts = request.files.getlist("file")
    for index, part in enumerate(image_parts):
        if _size(part) > cfg.max_image_bytes:
            raise ApiError(413, "file_too_large", "A page image exceeds the size limit", page_index=index)
        if standardize.sniff(_head(part)) in ("jpeg", "png"):  # header-only, also beyond 20 parts
            standardize.check_pixels(part.stream.read(), index, cfg.max_image_pixels)
            part.stream.seek(0)
    for part in pdf_parts:
        if source == "pdf" and _size(part) > cfg.max_pdf_bytes:
            raise ApiError(413, "file_too_large", "The PDF exceeds the size limit")

    if client_id_error is not None:
        raise client_id_error
    meta = parse_score_metadata(form)

    if source == "images":
        if pdf_parts and image_parts:
            raise ApiError(400, "mixed_input_types", "Send either pages or a PDF, not both")
        if not image_parts:
            raise ApiError(400, "no_pages", "At least one page is required")
    else:
        if image_parts and pdf_parts:
            raise ApiError(400, "mixed_input_types", "A PDF cannot be combined with images")
        if len(pdf_parts) > 1:
            raise ApiError(400, "multiple_pdfs", "Send a single PDF")
        if not pdf_parts:
            raise ApiError(400, "no_pages", "A PDF is required")
        if standardize.sniff(_head(pdf_parts[0])) != "pdf":
            raise ApiError(415, "unsupported_file_type", "The file is not a PDF")

    pages = _collect_images(image_parts, cfg) if source == "images" else _collect_pdf(pdf_parts[0], cfg)

    with db.transaction() as conn:
        if meta.replaces_ref_invalid:
            raise ApiError(404, "job_not_found", "Job not found")
        old_status = None
        if meta.replaces_job_id is not None:
            old_status = _check_retake(conn, meta.replaces_job_id, lock=False)
        if old_status != "complete":  # lock-free fail-fast; create_job's locked check decides
            _check_score_limit(conn, user_id)
        _check_active_cap(conn, user_id, client_id, cfg.max_active_jobs_per_user)  # fail-fast, before upload
        queued = conn.execute("SELECT count(*) AS n FROM jobs WHERE status = 'queued'").fetchone()
    if queued is not None and queued["n"] >= cfg.queue_capacity:
        raise ApiError(429, "queue_full", "The processing queue is full",
                       retry_after=QUEUE_FULL_RETRY_AFTER_S)

    job_row = create_job(user_id, meta, pages, source, client_id)
    log_event(LOG, "score create", user_id=user_id, job_id=job_row["id"], pages=len(pages),
              in_bytes=request.content_length or 0)
    return _accepted(job_row)


@jobs_bp.post("")
@security.require_auth
def submit_images() -> tuple[Response, int]:
    return _submit("images")


@jobs_bp.post("/pdf")
@security.require_auth
def submit_pdf() -> tuple[Response, int]:
    return _submit("pdf")


def _status_payload(job: Mapping[str, Any]) -> dict[str, Any]:
    """The status ``data`` object; fields that do not apply to the job's state are null/omitted."""
    status = job["status"]
    data: dict[str, Any] = {
        "jobId": job_ref(job["id"]),
        "status": status,
        "totalPages": job["page_count"],
        "percentComplete": job["percent_complete"],
        "failureReason": failure_code(job["failure_reason"]) if status == "failed" else None,
        "failedVoices": job["failed_voices"] if status == "complete" else None,
        "failedVoiceCauses": job["failed_voice_causes"] if status == "complete" else None,
        "title": job["title"],
        "tempoBpm": job["tempo_bpm"],
        "clientSubmissionId": str(job["client_submission_id"]) if job["client_submission_id"] else None,
        "createdAt": iso_z(job["created_at"]),
    }
    if status not in _FINISHED and job["current_page"] is not None:
        data["currentPage"] = job["current_page"]
    if status == "failed":
        data["pageIndex"] = job["failure_page_index"]
        data["failureDetail"] = job["failure_reason"]  # raw worker text, for support/logs only
    if status == "complete":
        data["scoreId"] = job["score_id"]
    for key, column in (("arranger", "arranger"), ("keySignature", "key_signature"),
                        ("timeSignature", "time_signature")):
        if job[column] is not None:
            data[key] = job[column]
    return data


def _count_status_read(conn: Conn, bucket: str = STATUS_READ_BUCKET, limit: int | None = None) -> None:
    """Apply a per-user read limit (default: the per-job status one) and record this hit.

    Raises:
        ApiError: 429 ``rate_limited``.
    """
    subject = security.keyed_hash(str(g.user.id))
    throttle.lock_subject(conn, bucket, subject)
    retry = throttle.window_retry_after(
        conn, bucket, subject, limit if limit is not None else _settings().status_reads_per_minute,
        STATUS_READ_WINDOW_S,
    )
    if retry is not None:
        raise throttle.too_many(retry)
    throttle.record_hit(conn, bucket, subject)


@jobs_bp.get("")
@security.require_auth
def list_jobs() -> tuple[Response, int]:
    """The caller's active jobs plus those created in the last ``LIST_WINDOW_DAYS``, newest first.

    Lets the app rebuild library rows after being closed. Jobs whose score is in the recovery
    window are omitted, matching the 404 that status/result give for them. A job replaced by a
    retake (``superseded_by_job_id`` set) is omitted too, so the app sees one row per capture.
    """
    with db.transaction() as conn:
        _count_status_read(conn, LIST_READ_BUCKET, _settings().list_reads_per_minute)
        rows = conn.execute(
            "SELECT j.* FROM jobs j LEFT JOIN scores s ON s.id = j.score_id"
            " WHERE j.user_id = %(u)s AND s.deleted_at IS NULL AND j.superseded_by_job_id IS NULL"
            " AND (j.status <> ALL(%(f)s) OR j.created_at > now() - make_interval(days => %(d)s))"
            " ORDER BY j.created_at DESC, j.id DESC LIMIT %(n)s",
            {"u": g.user.id, "f": list(_FINISHED), "d": LIST_WINDOW_DAYS, "n": LIST_MAX_ITEMS},
        ).fetchall()
    return ok({"jobs": [_status_payload(r) for r in rows]}, 200, "Jobs retrieved")


@jobs_bp.get("/<ref>")
@security.require_auth
def job_status(ref: str) -> tuple[Response, int]:
    job_id = parse_job_ref(ref)
    if job_id is None:
        raise ApiError(404, "job_not_found", "Job not found")
    missing: ApiError | None = None
    with db.transaction() as conn:
        _count_status_read(conn)
        try:
            job = access.owned_job(conn, job_id)
        except ApiError as exc:
            missing = exc  # raised after commit so probing unowned ids still counts against the limit
    if missing is not None:
        raise missing
    return ok(_status_payload(job), 200, "Processing status retrieved")


@jobs_bp.post("/<ref>/cancel")
@security.require_auth
def cancel_job(ref: str) -> tuple[Response, int]:
    """Cancel a non-terminal job; the request body is ignored (the path is authoritative)."""
    job_id = parse_job_ref(ref)
    if job_id is None:
        raise ApiError(404, "job_not_found", "Job not found")
    with db.transaction() as conn:
        job = _cancel_in_txn(conn, job_id, tolerate_terminal=False)
    _log_cancel(job_id, job["status"])
    return ok({"jobId": ref, "status": "cancelled"}, 200, "Processing cancelled")


def _log_cancel(job_id: int, stage: str) -> None:
    LOG.info("job cancelled job_id=%s user_id=%s stage=%s at=%s",
             job_id, g.user.id, stage, iso_z(datetime.now(timezone.utc)))
    log_event(LOG, "job cancel", user_id=g.user.id, job_id=job_id)


def _cancel_in_txn(conn: Conn, job_id: int, *, tolerate_terminal: bool) -> dict[str, Any]:
    """Cancel one owned job; returns the row as it was before (its ``status`` tells what happened).

    A finished job raises 409 ``job_terminal``, or is returned untouched with ``tolerate_terminal``.
    Cancelling a retake restores the failed job it superseded, so the capture keeps one visible row.
    """
    # Read unlocked first only to learn score_id: the score must be locked before the job.
    job = access.owned_job(conn, job_id)
    if job["score_id"] is not None:  # ERD lock order: score before job
        access.owned_score(conn, job["score_id"], for_update=True)
    job = access.owned_job(conn, job_id, for_update=True)
    if job["status"] in _FINISHED:  # re-check: it may have finished while we waited for the lock
        if tolerate_terminal:
            return dict(job)
        raise ApiError(409, "job_terminal", "The job has already finished")
    conn.execute("UPDATE jobs SET status = 'cancelled', updated_at = now() WHERE id = %s", (job_id,))
    conn.execute("UPDATE jobs SET superseded_by_job_id = NULL WHERE superseded_by_job_id = %s", (job_id,))
    keys = [r["object_key"] for r in conn.execute(
        "SELECT object_key FROM job_pages WHERE job_id = %s", (job_id,)).fetchall()]
    background.queue_deletion(conn, keys)
    return dict(job)


@jobs_bp.post("/by-submission/<csid>/cancel")
@security.require_auth
def cancel_submission(csid: str) -> tuple[Response, int]:
    """Cancel by ``clientSubmissionId``, also before the upload's 202 ever reached the app.

    Idempotent and owner-scoped (the id is looked up only among the caller's jobs). If the job exists it
    is cancelled; if it already finished it is left alone and its status is reported; if no job exists
    yet a cancelled-intent is recorded so a submit with this id (now or still in flight) gets 409
    ``submission_cancelled`` instead of creating a job nobody wants.
    """
    client_id = parse_client_submission_id(MultiDict([("clientSubmissionId", csid)]))
    if client_id is None:
        raise ApiError(400, "invalid_client_submission_id", "clientSubmissionId must be a UUID")
    user_id: int = g.user.id
    subject = security.keyed_hash(str(user_id))
    with db.transaction() as conn:
        _count_status_read(conn, CANCEL_SUBMISSION_BUCKET)
        # Same lock create_job takes before inserting: either we see its job, or it sees our intent.
        throttle.lock_subject(conn, SUBMIT_BUCKET, subject)
        row = conn.execute("SELECT id FROM jobs WHERE user_id = %s AND client_submission_id = %s",
                           (user_id, client_id)).fetchone()
        job: dict[str, Any] | None = None
        if row is None:
            conn.execute("INSERT INTO cancelled_submissions (user_id, client_submission_id) VALUES (%s, %s) "
                         "ON CONFLICT DO NOTHING", (user_id, client_id))
        else:
            job = _cancel_in_txn(conn, row["id"], tolerate_terminal=True)
    status = "cancelled" if job is None or job["status"] not in _FINISHED else str(job["status"])
    if job is not None and job["status"] not in _FINISHED:
        _log_cancel(job["id"], job["status"])
    return ok({"clientSubmissionId": str(client_id), "jobId": None if job is None else job_ref(job["id"]),
               "status": status}, 200, "Submission cancelled")
