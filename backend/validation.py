"""Request-body helpers that turn malformed client input into 400 ApiError responses."""

from __future__ import annotations

from collections.abc import Mapping

from flask import request

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
