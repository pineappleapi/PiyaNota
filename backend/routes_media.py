"""Signed media download for the db storage backend: GET/HEAD /media/<key>?exp=..&sig=..

No auth header: the HMAC signature on (key, expiry) is the capability, which is what lets the
Android player and a plain <audio> element fetch a link without extra headers. The blueprint is
registered only when storage_backend == "db".
"""

from __future__ import annotations

import hmac
import re
import time
from typing import cast

from flask import Blueprint, Response, current_app, request

from backend import db
from backend.config import SETTINGS_KEY, Settings
from backend.envelope import ApiError
from backend.storage import sign_media

media_bp = Blueprint("media", __name__)

# ASCII-only and length-capped: str.isdigit() accepts characters int() rejects, and huge digit
# strings make int() raise, either of which would be a logged 500 for an unauthenticated caller.
_MAX_NUMBER_DIGITS = 12
_EXP_RE = re.compile(rf"[0-9]{{1,{_MAX_NUMBER_DIGITS}}}", re.ASCII)
_RANGE_RE = re.compile(rf"^bytes=([0-9]{{0,{_MAX_NUMBER_DIGITS}}})-([0-9]{{0,{_MAX_NUMBER_DIGITS}}})$", re.ASCII)
_HEADERS = {
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, max-age=0",
    "X-Content-Type-Options": "nosniff",
}
# One body for expired and forged links so a caller cannot tell which check failed.
_BAD_LINK = ApiError(403, "forbidden", "Link is invalid or has expired")


def _parse_range(header: str, length: int) -> tuple[int, int] | None:
    """Return inclusive (first, last) byte offsets, or None when unsatisfiable or malformed.

    Only a single range is supported; multi-range requests are answered with 416.
    """
    match = _RANGE_RE.match(header.strip())
    if match is None:
        return None
    start_s, end_s = match.groups()
    if start_s == "" and end_s == "":
        return None
    if start_s == "":  # suffix form: the last n bytes
        suffix = int(end_s)
        if suffix == 0 or length == 0:
            return None
        return max(length - suffix, 0), length - 1
    first = int(start_s)
    last = int(end_s) if end_s else length - 1
    if first >= length or last < first:
        return None
    return first, min(last, length - 1)


def _verify_link(key: str, settings: Settings) -> None:
    """Raise the uniform 403 unless exp and sig are single, well-formed, valid and unexpired."""
    exps = request.args.getlist("exp")
    sigs = request.args.getlist("sig")
    if len(exps) != 1 or len(sigs) != 1 or _EXP_RE.fullmatch(exps[0]) is None:
        raise _BAD_LINK
    exp = int(exps[0])
    expected = sign_media(key, exp, settings.media_hmac_key)
    # Compare before the expiry check so timing does not depend on which part is wrong.
    sig_ok = hmac.compare_digest(sigs[0].encode("utf-8"), expected.encode("utf-8"))
    if not sig_ok or exp < time.time():
        raise _BAD_LINK


@media_bp.get("/media/<path:key>")
def get_media(key: str) -> Response:
    """Serve a stored blob, honouring a single Range, after verifying the link signature.

    A full GET reads the row once; HEAD and Range requests read only the length (and the slice),
    so audio seeks do not pull the whole blob out of Postgres each time.
    """
    _verify_link(key, cast(Settings, current_app.config[SETTINGS_KEY]))
    range_header = request.headers.get("Range")
    full_body = range_header is None and request.method == "GET"

    with db.transaction() as conn:
        if full_body:
            row = conn.execute(
                "SELECT content_type, data, octet_length(data) AS length FROM blobs WHERE key = %s", (key,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT content_type, octet_length(data) AS length FROM blobs WHERE key = %s", (key,)
            ).fetchone()
        if row is None:
            raise ApiError(404, "not_found", "Not found")
        length = int(row["length"])

        status = 200
        headers = dict(_HEADERS)
        first, last = 0, length - 1
        if range_header is not None:
            span = _parse_range(range_header, length)
            if span is None:
                return Response(status=416, headers={**headers, "Content-Range": f"bytes */{length}"})
            first, last = span
            status = 206
            headers["Content-Range"] = f"bytes {first}-{last}/{length}"
        headers["Content-Length"] = str(last - first + 1 if length else 0)

        if full_body:
            body = bytes(row["data"])
        elif request.method == "GET":
            # substring() is 1-based.
            part = conn.execute(
                "SELECT substring(data from %s for %s) AS part FROM blobs WHERE key = %s",
                (first + 1, last - first + 1, key),
            ).fetchone()
            body = b"" if part is None else bytes(part["part"])
        else:
            body = b""
    response = Response(body, status=status, headers=headers, content_type=row["content_type"])
    # Response() recomputes Content-Length from the (empty, for HEAD) body; restore the real one.
    response.headers["Content-Length"] = headers["Content-Length"]
    return response
