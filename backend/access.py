"""Central record scoping (PIYA-315): every user-owned lookup filters by ``g.user.id`` in SQL.

Cross-user ids and missing ids are indistinguishable (both 404), so ids cannot be probed.
"""

from __future__ import annotations

from typing import Any

import psycopg
from flask import g

from backend.envelope import ApiError

Conn = psycopg.Connection[dict[str, Any]]


def owned_job(conn: Conn, job_id: int, *, for_update: bool = False) -> dict[str, Any]:
    """The caller's job row.

    Raises:
        ApiError: 404 ``job_not_found``.
    """
    row: dict[str, Any] | None = conn.execute(
        "SELECT * FROM jobs WHERE id = %s AND user_id = %s" + (" FOR UPDATE" if for_update else ""),
        (job_id, g.user.id),
    ).fetchone()
    if row is None:
        raise ApiError(404, "job_not_found", "Job not found")
    return row


def owned_score(conn: Conn, score_id: int, *, for_update: bool = False) -> dict[str, Any]:
    """The caller's score row.

    Raises:
        ApiError: 404 ``score_not_found``.
    """
    row: dict[str, Any] | None = conn.execute(
        "SELECT * FROM scores WHERE id = %s AND user_id = %s" + (" FOR UPDATE" if for_update else ""),
        (score_id, g.user.id),
    ).fetchone()
    if row is None:
        raise ApiError(404, "score_not_found", "Score not found")
    return row
