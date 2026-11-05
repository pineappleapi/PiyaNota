"""A failed upload leaves nothing behind (V2 checks J6, B4).

The server needs no draft state: a ``scores`` row appears only when a job completes, and
``create_job`` discards its uploaded objects and reservations when storage fails.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from backend import db
from backend.storage import MemoryStorage

PASSWORD = "Secret123zz"
TABLES = ("jobs", "job_pages", "scores", "storage_deletions")


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, "JPEG")
    return buf.getvalue()


def _count(table: str) -> int:
    with db.transaction() as conn:
        return int(conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"])  # noqa: S608


@pytest.mark.parametrize("fail_on_call", [1, 2])
def test_storage_failure_leaves_no_rows_blobs_or_reservations(
    client: FlaskClient, app: Flask, fail_on_call: int
) -> None:
    res = client.post(
        "/api/auth/signup",
        json={"email": "a@example.com", "password": PASSWORD, "passwordConfirmation": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {res.get_json()['data']['sessionToken']}"}
    storage = app.extensions["storage"]
    assert isinstance(storage, MemoryStorage)
    real_put = storage.put
    calls: list[str] = []

    def flaky(key: str, data: bytes, content_type: str) -> None:
        calls.append(key)
        if len(calls) == fail_on_call:
            raise ConnectionError("boom")
        real_put(key, data, content_type)

    storage.put = flaky  # type: ignore[method-assign]
    data: dict[str, Any] = {
        "title": "t",
        "pages": [(io.BytesIO(_jpeg()), f"p{i}.jpg") for i in range(2)],
    }
    res = client.post("/api/jobs", data=data, headers=headers, content_type="multipart/form-data")

    assert res.status_code == 500
    assert len(calls) == fail_on_call  # the failure really happened mid-upload
    assert {t: _count(t) for t in TABLES} == dict.fromkeys(TABLES, 0)
    assert storage.objects == {}
