"""JSON response envelope, the ApiError exception, and UTC timestamp formatting."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Response, jsonify


class ApiError(Exception):
    """An expected, client-facing failure rendered through the JSON error envelope.

    The message is returned to the client verbatim, so it must never contain internal detail.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        field: str | None = None,
        page_index: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.page_index = page_index
        self.retry_after = retry_after


def ok(data: object, status: int, message: str) -> tuple[Response, int]:
    """Build a success envelope with the four contract keys: data, success, status, message."""
    return jsonify({"data": data, "success": True, "status": status, "message": message}), status


def error_response(exc: ApiError) -> tuple[Response, int]:
    """Build an error envelope. ``error`` has no message key; optional keys appear only when set."""
    detail: dict[str, object] = {"code": exc.code}
    if exc.field is not None:
        detail["field"] = exc.field
    if exc.page_index is not None:
        detail["pageIndex"] = exc.page_index
    if exc.retry_after is not None:
        detail["retryAfterSeconds"] = exc.retry_after
    response = jsonify(
        {
            "data": None,
            "success": False,
            "status": exc.status,
            "message": exc.message,
            "error": detail,
        }
    )
    if exc.retry_after is not None:
        response.headers["Retry-After"] = str(exc.retry_after)
    return response, exc.status


def iso_z(moment: datetime) -> str:
    """Format an aware datetime as UTC ISO-8601 with a ``Z`` suffix, to whole seconds.

    Naive datetimes are rejected because astimezone() would silently read them as server-local time.

    Raises:
        ValueError: The datetime has no tzinfo.
    """
    if moment.tzinfo is None:
        raise ValueError("iso_z requires a timezone-aware datetime")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
