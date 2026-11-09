"""Request-body helpers that turn malformed client input into 400 ApiError responses."""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from flask import request
from werkzeug.datastructures import MultiDict

from backend.envelope import ApiError


def json_body() -> dict[str, object]:
    """Return the request's JSON object body.

    Arrays, null, scalars, unparseable text and a non-JSON content type are all rejected as
    ``invalid_json``. ``silent=True`` stops Flask answering with its HTML 400, which would bypass
    the envelope.

    Raises:
        ApiError: 400 ``invalid_json`` when the body is not a JSON object.
    """
    body = request.get_json(silent=True) if request.is_json else None
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_json", "Request body must be a JSON object")
    return body


def require_str(body: Mapping[str, object], field: str) -> str:
    """Return ``body[field]`` if it is a string with non-whitespace content.

    The value is returned unstripped: passwords may legitimately begin or end with spaces.

    Raises:
        ApiError: 400 ``missing_field`` naming ``field`` when absent, non-string or blank.
    """
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "missing_field", f"{field} is required", field=field)
    return value


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LENGTH = 8
# Bounds work before the regex (quadratic backtracking) and memory held under HASH_SEMAPHORE.
MAX_EMAIL_LENGTH = 254  # RFC 5321
MAX_PASSWORD_LENGTH = 1024


def normalize_email(raw: object, field: str = "email") -> str:
    """Trim and lower-case an email so it matches the ``users.email`` CHECK constraint.

    Raises:
        ApiError: 400 ``missing_field`` when absent/blank, 400 ``invalid_email`` when malformed.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "missing_field", f"{field} is required", field=field)
    email = raw.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.match(email):
        raise ApiError(400, "invalid_email", "Email address is not valid", field=field)
    return email


def check_password_policy(password: str, field: str) -> None:
    """Require 8-1024 characters with a letter and a digit.

    Raises:
        ApiError: 400 ``weak_password`` naming ``field``.
    """
    has_letter = any(ch.isalpha() for ch in password)
    has_digit = any(ch.isdigit() for ch in password)
    too_short = len(password) < _MIN_PASSWORD_LENGTH
    too_long = len(password) > MAX_PASSWORD_LENGTH
    if too_short or too_long or not has_letter or not has_digit:
        raise ApiError(
            400,
            "weak_password",
            "Password must be at least 8 characters and include a letter and a digit",
            field=field,
        )


# --- Score metadata (PIYA-101 AC8, PIYA-323) ---------------------------------------------------
MAX_TEXT_LENGTH = 120
MIN_TEMPO_BPM = 30
MAX_TEMPO_BPM = 240
DEFAULT_TEMPO_BPM = 90
_MAX_TEMPO_DIGITS = 3  # bounds int() work on hostile input
KEY_SIGNATURES = frozenset(
    {"C", "G", "D", "A", "E", "B", "F#", "C#", "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"}
)
TIME_SIGNATURES = frozenset({"4/4", "3/4", "2/4", "6/8", "2/2"})
_JOB_REF = re.compile(r"job_([1-9][0-9]{0,17})")  # ASCII digits only; fits bigint
_UUID_CANONICAL = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
CONTROL_CATEGORY = "Cc"


@dataclass(frozen=True)
class ScoreMetadata:
    """Validated, normalised submission metadata.

    ``replaces_ref_invalid`` is separate from ``replaces_job_id`` because a malformed
    ``replacesJobId`` must surface as 404 at the retake step of the error precedence, not as a
    400 here.
    """

    title: str
    arranger: str | None
    tempo_bpm: int
    tempo_source: Literal["user", "fallback", "default"]
    key_signature: str | None
    time_signature: str | None
    replaces_job_id: int | None
    replaces_ref_invalid: bool = False


def parse_job_ref(ref: str) -> int | None:
    """Parse the app's ``"job_<n>"`` string; None when malformed."""
    match = _JOB_REF.fullmatch(ref)
    return int(match.group(1)) if match else None


def _single(form: MultiDict[str, str], field: str, *, reject_control: bool = False) -> str | None:
    """The trimmed single value of ``field``; None when absent or whitespace-only.

    With ``reject_control`` the NFC value is checked for Cc characters BEFORE trimming, so
    a trailing newline is rejected (AC8) while a whitespace-only value is still "absent".

    Raises:
        ApiError: 400 ``duplicate_field`` when sent more than once.
    """
    values = form.getlist(field)
    if len(values) > 1:
        raise ApiError(400, "duplicate_field", f"{field} was sent more than once", field=field)
    if not values:
        return None
    raw = unicodedata.normalize("NFC", values[0])
    if not raw.strip():
        return None
    if reject_control and any(unicodedata.category(ch) == CONTROL_CATEGORY for ch in raw):
        raise ApiError(400, f"{field}_invalid", f"{field} contains control characters", field=field)
    return raw.strip()


def _text(form: MultiDict[str, str], field: str, *, required: bool) -> str | None:
    value = _single(form, field, reject_control=True)
    if value is None:
        if required:
            raise ApiError(400, f"{field}_required", f"{field} is required", field=field)
        return None
    if len(value) > MAX_TEXT_LENGTH:
        raise ApiError(400, f"{field}_too_long", f"{field} is too long", field=field)
    return value


def _tempo(form: MultiDict[str, str], field: str) -> int | None:
    value = _single(form, field)
    if value is None:
        return None
    # isdecimal() would accept Arabic-Indic digits; the contract is ASCII only.
    valid = value.isascii() and value.isdigit() and len(value) <= _MAX_TEMPO_DIGITS
    if not valid or not MIN_TEMPO_BPM <= int(value) <= MAX_TEMPO_BPM:
        raise ApiError(400, "invalid_tempo", f"{field} must be {MIN_TEMPO_BPM}-{MAX_TEMPO_BPM}", field=field)
    return int(value)


def _enum(form: MultiDict[str, str], field: str, allowed: frozenset[str], code: str) -> str | None:
    value = _single(form, field)
    if value is not None and value not in allowed:
        raise ApiError(400, code, f"{field} is not a recognised value", field=field)
    return value


def parse_score_metadata(form: MultiDict[str, str]) -> ScoreMetadata:
    """Validate the text parts of a submission (PIYA-101 AC8 and PIYA-323).

    Control characters (including newlines and tabs) are rejected before trimming, so
    a trailing newline gives ``title_invalid``.

    Raises:
        ApiError: 400 with the field's code; ``duplicate_field`` for a repeated field or for
            ``tempoBpm`` sent together with ``fallbackTempoBpm``.
    """
    title = _text(form, "title", required=True) or ""  # required=True never returns None
    arranger = _text(form, "arranger", required=False)
    tempo = _tempo(form, "tempoBpm")
    fallback = _tempo(form, "fallbackTempoBpm")
    if tempo is not None and fallback is not None:
        raise ApiError(400, "duplicate_field", "Send tempoBpm or fallbackTempoBpm, not both",
                       field="fallbackTempoBpm")
    key = _enum(form, "keySignature", KEY_SIGNATURES, "invalid_key_signature")
    time_sig = _enum(form, "timeSignature", TIME_SIGNATURES, "invalid_time_signature")
    ref = _single(form, "replacesJobId")
    replaces = parse_job_ref(ref) if ref is not None else None
    source: Literal["user", "fallback", "default"] = "user"
    if tempo is None:
        tempo, source = (fallback, "fallback") if fallback is not None else (DEFAULT_TEMPO_BPM, "default")
    return ScoreMetadata(
        title=title, arranger=arranger, tempo_bpm=tempo, tempo_source=source,
        key_signature=key, time_signature=time_sig, replaces_job_id=replaces,
        replaces_ref_invalid=ref is not None and replaces is None,
    )


def parse_client_submission_id(form: MultiDict[str, str]) -> uuid.UUID | None:
    """The optional ``clientSubmissionId`` idempotency key as a UUID; None when absent/blank.

    Only the 8-4-4-4-12 hyphenated form is accepted (any case), so equal ids always compare equal
    after lower-casing.

    Raises:
        ApiError: 400 ``invalid_client_submission_id`` when malformed or repeated.
    """
    field = "clientSubmissionId"
    try:
        value = _single(form, field)
    except ApiError:
        raise ApiError(400, "invalid_client_submission_id", f"{field} was sent more than once",
                       field=field) from None
    if value is None:
        return None
    if not _UUID_CANONICAL.fullmatch(value):
        raise ApiError(400, "invalid_client_submission_id", f"{field} must be a UUID", field=field)
    return uuid.UUID(value.lower())


def clean_title(value: object) -> str:
    """Validated title for PATCH /api/scores; a required, never-empty string."""
    return clean_text(value, "title", required=True) or ""  # required=True never returns None


def clean_arranger(value: object) -> str | None:
    """Validated arranger for PATCH /api/scores; None clears it."""
    return clean_text(value, "arranger", required=False)


def clean_text(value: object, field: str, *, required: bool) -> str | None:
    """Apply the submission title/arranger rules to one JSON value (PATCH /api/scores).

    Raises:
        ApiError: 400 ``<field>_required``, ``<field>_invalid`` or ``<field>_too_long``.
    """
    if value is not None and not isinstance(value, str):
        raise ApiError(400, f"{field}_invalid", f"{field} must be a string", field=field)
    return _text(MultiDict([] if value is None else [(field, value)]), field, required=required)
