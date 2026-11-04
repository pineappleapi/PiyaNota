"""Signed media download for the db storage backend: GET/HEAD /media/<key>?exp=..&sig=..

No auth header: the HMAC signature on (key, expiry) is the capability, which is what lets the
Android player and a plain <audio> element fetch a link without extra headers.
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

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CACHE_CONTROL = "private, max-age=0"
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


@media_bp.get("/media/<path:key>")
def get_media(key: str) -> Response:
    """Serve a stored blob, honouring a single Range, after verifying the link signature."""
    settings = cast(Settings, current_app.config[SETTINGS_KEY])
    exp_raw = request.args.get("exp", "")
    sig = request.args.get("sig", "")
    expected = sign_media(key, int(exp_raw) if exp_raw.isdigit() else -1, settings.media_hmac_key)
    # Compare before the expiry check so timing does not depend on which part is wrong.
    sig_ok = hmac.compare_digest(sig.encode("utf-8"), expected.encode("utf-8"))
    if not exp_raw.isdigit() or not sig_ok or int(exp_raw) < time.time():
        raise _BAD_LINK

    with db.transaction() as conn:
        row = conn.execute("SELECT content_type, data FROM blobs WHERE key = %s", (key,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Not found")
    data = bytes(row["data"])
    length = len(data)

    status = 200
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": _CACHE_CONTROL,
    }
    range_header = request.headers.get("Range")
    if range_header is not None:
        span = _parse_range(range_header, length)
        if span is None:
            return Response(status=416, headers={**headers, "Content-Range": f"bytes */{length}"})
        first, last = span
        data = data[first : last + 1]
        status = 206
        headers["Content-Range"] = f"bytes {first}-{last}/{length}"
    return Response(data, status=status, headers=headers, content_type=row["content_type"])
