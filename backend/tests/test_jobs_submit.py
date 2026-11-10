"""Tests for POST /api/jobs and POST /api/jobs/pdf (PIYA-101, PIYA-310, PIYA-323)."""

from __future__ import annotations

import gc
import io
import json
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image
from werkzeug.test import EnvironBuilder, run_wsgi_app

from backend import db
from backend.app import create_app
from backend.config import Settings
from backend.storage import MemoryStorage

PASSWORD = "Secret123zz"
MAX_PAGES = 20
RATE_LIMIT = 10
CSID = "123E4567-E89B-12D3-A456-426614174000"


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _img(fmt: str, size: tuple[int, int] = (40, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, fmt)
    return buf.getvalue()


def _pdf(pages: int) -> bytes:
    imgs = [Image.new("RGB", (200, 280), "white") for _ in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def _signup(client: FlaskClient, email: str = "a@example.com") -> dict[str, str]:
    res = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "passwordConfirmation": PASSWORD},
    )
    assert res.status_code == 201
    return {"Authorization": f"Bearer {res.get_json()['data']['sessionToken']}"}


def _post(
    client: FlaskClient,
    headers: dict[str, str],
    path: str = "/api/jobs",
    *,
    pages: list[bytes] | None = None,
    files: list[bytes] | None = None,
    **fields: Any,
) -> Any:
    data: dict[str, Any] = dict(fields)
    if pages is not None:
        data["pages"] = [(io.BytesIO(p), f"p{i}.bin") for i, p in enumerate(pages)]
    if files is not None:
        data["file"] = [(io.BytesIO(f), f"f{i}.bin") for i, f in enumerate(files)]
    return client.post(path, data=data, headers=headers, content_type="multipart/form-data")


def _jobs() -> list[dict[str, Any]]:
    with db.transaction() as conn:
        return conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()


def _storage(app: Flask) -> MemoryStorage:
    storage = app.extensions["storage"]
    assert isinstance(storage, MemoryStorage)
    return storage


def _err(res: Any, status: int, code: str) -> dict[str, Any]:
    assert res.status_code == status, res.get_json()
    error: dict[str, Any] = res.get_json()["error"]
    assert error["code"] == code
    return error


@pytest.fixture
def headers(client: FlaskClient) -> dict[str, str]:
    return _signup(client)


@pytest.fixture
def make_app(settings: Settings) -> Iterator[Callable[..., FlaskClient]]:
    """Client for an app with overridden settings; closes the pool afterwards."""

    def build(**overrides: Any) -> FlaskClient:
        app = create_app(replace(settings, **overrides))
        app.config["TESTING"] = True
        return app.test_client()

    yield build
    db.close_pool()


def test_submit_images_202_shape(client: FlaskClient, app: Flask, headers: dict[str, str]) -> None:
    res = _post(client, headers, pages=[_img("JPEG"), _img("PNG")], title="Bayan Ko")
    assert res.status_code == 202
    body = res.get_json()
    assert body["message"] == "Score submitted for processing"
    data = body["data"]
    assert re.fullmatch(r"job_\d+", data["jobId"]) and isinstance(data["jobId"], str)
    assert (data["pageCount"], data["tempoBpm"], data["status"], data["title"]) == (2, 90, "queued", "Bayan Ko")
    assert data["submittedAt"].endswith("Z") and isinstance(data["userId"], int)
    assert not {"arranger", "keySignature", "timeSignature", "replacesJobId"} & set(data)
    with db.transaction() as conn:
        rows = conn.execute("SELECT page_index, object_key FROM job_pages ORDER BY page_index").fetchall()
    assert [r["page_index"] for r in rows] == [0, 1]
    storage = _storage(app)
    assert len(storage.objects) == 2
    assert all(Image.open(io.BytesIO(storage.objects[r["object_key"]])).format == "JPEG" for r in rows)
    with db.transaction() as conn:  # reservations released by the creating transaction
        assert conn.execute("SELECT count(*) AS n FROM storage_deletions").fetchone()["n"] == 0


def test_submit_echoes_optional_metadata(client: FlaskClient, headers: dict[str, str]) -> None:
    res = _post(
        client, headers, pages=[_img("JPEG")], title="  Ave  ", arranger="Pia",
        tempoBpm="120", keySignature="Eb", timeSignature="6/8",
    )
    data = res.get_json()["data"]
    assert res.status_code == 202
    assert (data["title"], data["arranger"], data["tempoBpm"]) == ("Ave", "Pia", 120)
    assert (data["keySignature"], data["timeSignature"]) == ("Eb", "6/8")


@pytest.mark.parametrize(
    ("fields", "code", "field"),
    [
        ({}, "title_required", "title"),
        ({"title": "a" * 121}, "title_too_long", "title"),
        ({"title": "a\nb"}, "title_invalid", "title"),
        ({"title": "t", "arranger": "a" * 121}, "arranger_too_long", "arranger"),
        ({"title": "Title\n"}, "title_invalid", "title"),
        ({"title": "t", "arranger": "Pia\t"}, "arranger_invalid", "arranger"),
        ({"title": "t", "tempoBpm": "29"}, "invalid_tempo", "tempoBpm"),
        ({"title": "t", "tempoBpm": "٩٠"}, "invalid_tempo", "tempoBpm"),
        ({"title": "t", "fallbackTempoBpm": "241"}, "invalid_tempo", "fallbackTempoBpm"),
        ({"title": "t", "keySignature": "eb"}, "invalid_key_signature", "keySignature"),
        ({"title": "t", "timeSignature": "5/4"}, "invalid_time_signature", "timeSignature"),
        ({"title": "t", "tempoBpm": "100", "fallbackTempoBpm": "100"}, "duplicate_field", None),
        ({"title": ["a", "b"]}, "duplicate_field", "title"),
    ],
)
def test_metadata_errors(
    client: FlaskClient, headers: dict[str, str], fields: dict[str, Any], code: str, field: str | None
) -> None:
    res = _post(client, headers, pages=[_img("JPEG")], **fields)
    error = _err(res, 400, code)
    if field is not None:
        assert error["field"] == field


def test_fallback_tempo_settled(client: FlaskClient, headers: dict[str, str]) -> None:
    res = _post(client, headers, pages=[_img("JPEG")], title="t", fallbackTempoBpm="100")
    assert res.get_json()["data"]["tempoBpm"] == 100
    res = _post(client, headers, pages=[_img("JPEG")], title="t")
    assert res.get_json()["data"]["tempoBpm"] == 90
    res = _post(client, headers, pages=[_img("JPEG")], title="t", tempoBpm="77")
    assert res.get_json()["data"]["tempoBpm"] == 77
    assert [(j["tempo_bpm"], j["tempo_source"]) for j in _jobs()] == [
        (100, "fallback"), (90, "default"), (77, "user"),
    ]


def test_file_errors(client: FlaskClient, headers: dict[str, str]) -> None:
    jpg = _img("JPEG")
    _err(_post(client, headers, pages=[], title="t"), 400, "no_pages")
    _err(_post(client, headers, title="t"), 400, "no_pages")
    _err(_post(client, headers, pages=[jpg] * (MAX_PAGES + 1), title="t"), 400, "too_many_pages")
    err = _err(_post(client, headers, pages=[jpg, _img("GIF")], title="t"), 415, "unsupported_file_type")
    assert err["pageIndex"] == 1
    err = _err(_post(client, headers, pages=[jpg, jpg[: len(jpg) // 2]], title="t"), 422, "corrupt_image")
    assert err["pageIndex"] == 1
    _err(_post(client, headers, pages=[jpg, _pdf(1)], title="t"), 400, "mixed_input_types")
    _err(_post(client, headers, pages=[jpg], files=[_pdf(1)], title="t"), 400, "mixed_input_types")
    assert _jobs() == []


def test_corrupt_beats_too_many_pages(client: FlaskClient, headers: dict[str, str]) -> None:
    pages = [_img("JPEG")] * MAX_PAGES + [b"\xff\xd8\xffjunkjunkjunk"]
    _err(_post(client, headers, pages=pages, title="t"), 422, "corrupt_image")


def test_pixel_cap_beats_missing_title(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(max_image_pixels=100)
    headers = _signup(client)
    err = _err(_post(client, headers, pages=[_img("JPEG", (5, 5)), _img("PNG", (20, 20))]), 413, "image_pixels_too_large")
    assert err["pageIndex"] == 1


def test_pixel_cap_checked_beyond_twenty_parts(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(max_image_pixels=100)
    headers = _signup(client)
    pages = [_img("JPEG", (5, 5))] * MAX_PAGES + [_img("PNG", (20, 20))]
    err = _err(_post(client, headers, pages=pages, title="t"), 413, "image_pixels_too_large")
    assert err["pageIndex"] == MAX_PAGES


def test_precedence_field_error_beats_415(client: FlaskClient, headers: dict[str, str]) -> None:
    _err(_post(client, headers, pages=[_img("GIF")]), 400, "title_required")


def test_unauthorized(client: FlaskClient) -> None:
    assert _post(client, {}, pages=[_img("JPEG")], title="t").status_code == 401


def test_image_too_large_413(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(max_image_bytes=100)
    headers = _signup(client)
    err = _err(_post(client, headers, pages=[_img("PNG", (200, 200))], title="t"), 413, "file_too_large")
    assert err["pageIndex"] == 0


def test_oversize_body_json_413(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(max_content_length=1024 * 1024)
    headers = _signup(client)
    # Raw body: werkzeug's own multipart encoder would leak a temp file in the test client.
    res = client.post(
        "/api/jobs", data=b"x" * (2 * 1024 * 1024), headers=headers,
        content_type="multipart/form-data; boundary=x",
    )
    _err(res, 413, "request_too_large")
    assert res.is_json


# werkzeug aborts the multipart parse mid-file and drops its SpooledTemporaryFile without closing
# it; the object is unreachable from our code, so the resulting warning is expected here only.
@pytest.mark.filterwarnings("ignore::ResourceWarning", "ignore::pytest.PytestUnraisableExceptionWarning")
def test_chunked_oversize_body_413(make_app: Callable[..., FlaskClient]) -> None:
    """No Content-Length (chunked): the limit trips while reading, not from the header."""
    limit = 64 * 1024
    client = make_app(max_content_length=limit)
    headers = _signup(client)
    crlf = "\r\n"
    head = crlf.join([
        "--bnd", 'Content-Disposition: form-data; name="title"', "", "t",
        "--bnd", 'Content-Disposition: form-data; name="pages"; filename="a.jpg"',
        "Content-Type: image/jpeg", "", "",
    ])
    body = head.encode() + b"x" * (2 * limit) + f"{crlf}--bnd--{crlf}".encode()
    builder = EnvironBuilder(
        "/api/jobs", method="POST", input_stream=io.BytesIO(body), headers=headers,
        content_type="multipart/form-data; boundary=bnd",
    )
    environ = builder.get_environ()
    # The builder derives Content-Length from the stream; remove it so only the streaming limit
    # can trip (a chunked upload).
    del environ["CONTENT_LENGTH"]
    environ["wsgi.input_terminated"] = True
    # Straight to the WSGI app: the test client would recompute Content-Length from the stream.
    app_iter, status, _ = run_wsgi_app(client.application.wsgi_app, environ)
    payload = json.loads(b"".join(app_iter))
    assert status.startswith("413")
    assert payload["error"]["code"] == "request_too_large"
    assert _jobs() == []
    gc.collect()  # surface the leaked temp file inside this test's warning filter


def test_submit_pdf_202(client: FlaskClient, app: Flask, headers: dict[str, str]) -> None:
    res = _post(client, headers, "/api/jobs/pdf", files=[_pdf(2)], title="Doc")
    assert res.status_code == 202
    assert res.get_json()["message"] == "PDF rasterized and submitted for processing"
    assert res.get_json()["data"]["pageCount"] == 2
    assert [j["source"] for j in _jobs()] == ["pdf"]
    assert len(_storage(app).objects) == 2
    assert all(Image.open(io.BytesIO(v)).format == "JPEG" for v in _storage(app).objects.values())


def test_pdf_errors(client: FlaskClient, headers: dict[str, str]) -> None:
    path = "/api/jobs/pdf"
    _err(_post(client, headers, path, files=[_img("JPEG")], title="t"), 415, "unsupported_file_type")
    _err(_post(client, headers, path, files=[_pdf(1), _pdf(1)], title="t"), 400, "multiple_pdfs")
    _err(_post(client, headers, path, title="t"), 400, "no_pages")
    _err(_post(client, headers, path, files=[_pdf(1)], pages=[_img("JPEG")], title="t"), 400, "mixed_input_types")
    _err(_post(client, headers, path, files=[_pdf(21)], title="t"), 400, "too_many_pages")
    _err(_post(client, headers, path, files=[b"%PDF-1.7 garbage garbage"], title="t"), 422, "corrupt_or_encrypted_pdf")
    _err(_post(client, headers, path, files=[_pdf(1)]), 400, "title_required")
    assert _jobs() == []


def test_submit_rate_limit(client: FlaskClient, headers: dict[str, str]) -> None:
    for i in range(RATE_LIMIT):
        if i % 2:
            res = _post(client, headers, pages=[_img("JPEG")], title="t")
        else:
            res = _post(client, headers, "/api/jobs/pdf", files=[_pdf(1)], title="t")
        assert res.status_code == 202
    res = _post(client, headers, pages=[_img("JPEG")], title="t")
    _err(res, 429, "rate_limited")
    assert int(res.headers["Retry-After"]) > 0
    _err(_post(client, headers, "/api/jobs/pdf", files=[_pdf(1)], title="t"), 429, "rate_limited")
    assert len(_jobs()) == RATE_LIMIT


def test_failed_submit_does_not_count_toward_rate_limit(client: FlaskClient, headers: dict[str, str]) -> None:
    for _ in range(RATE_LIMIT + 2):
        _err(_post(client, headers, pages=[_img("JPEG")]), 400, "title_required")
    assert _post(client, headers, pages=[_img("JPEG")], title="t").status_code == 202


def _insert_job(user_id: int, status: str = "queued", **extra: Any) -> int:
    values: dict[str, Any] = {
        "user_id": user_id, "status": status, "source": "images", "page_count": 1,
        "title": "Old", "tempo_source": "default",
    }
    values.update(extra)
    cols = ", ".join(values)
    with db.transaction() as conn:
        row = conn.execute(
            f"INSERT INTO jobs ({cols}) VALUES ({', '.join(['%s'] * len(values))}) RETURNING id",
            tuple(values.values()),
        ).fetchone()
    assert row is not None
    return int(row["id"])


def _user_id(email: str = "a@example.com") -> int:
    with db.transaction() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
    assert row is not None
    return int(row["id"])


def test_queue_full(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(queue_capacity=1)
    headers = _signup(client)
    _insert_job(_user_id())
    res = _post(client, headers, pages=[_img("JPEG")], title="t")
    _err(res, 429, "queue_full")
    assert res.headers["Retry-After"] == "600"
    assert len(_jobs()) == 1


def test_no_partial_state(client: FlaskClient, app: Flask, headers: dict[str, str]) -> None:
    storage = _storage(app)
    real_put = storage.put
    calls: list[str] = []

    def flaky(key: str, data: bytes, content_type: str) -> None:
        calls.append(key)
        if len(calls) == 2:
            raise ConnectionError("boom")
        real_put(key, data, content_type)

    storage.put = flaky  # type: ignore[method-assign]
    res = _post(client, headers, pages=[_img("JPEG"), _img("JPEG")], title="t")
    assert res.status_code == 500
    assert _jobs() == []
    assert storage.objects == {}


def test_retake_rules(client: FlaskClient, headers: dict[str, str]) -> None:
    _signup(client, "b@example.com")
    foreign = _insert_job(_user_id("b@example.com"), "failed", failure_reason="incomplete_voice_sequence")
    queued = _insert_job(_user_id())
    failed = _insert_job(_user_id(), "failed", failure_reason="incomplete_voice_sequence")
    kw: dict[str, Any] = {"pages": [_img("JPEG")], "title": "t"}
    _err(_post(client, headers, replacesJobId=f"job_{foreign}", **kw), 404, "job_not_found")
    _err(_post(client, headers, replacesJobId=f"job_{queued}", **kw), 409, "not_retakeable")
    res = _post(client, headers, replacesJobId=f"job_{failed}", **kw)
    assert res.status_code == 202
    new_id = int(res.get_json()["data"]["jobId"].removeprefix("job_"))
    assert res.get_json()["data"]["replacesJobId"] == f"job_{failed}"
    jobs = {j["id"]: j for j in _jobs()}
    assert jobs[failed]["superseded_by_job_id"] == new_id
    assert jobs[new_id]["replaces_job_id"] == failed
    _err(_post(client, headers, replacesJobId=f"job_{failed}", **kw), 409, "retake_in_progress")


def test_retake_any_failure_reason_supersedes(client: FlaskClient, headers: dict[str, str]) -> None:
    failed = _insert_job(_user_id(), "failed", failure_reason="processing_timeout")
    res = _post(client, headers, pages=[_img("JPEG")], title="t", replacesJobId=f"job_{failed}")
    assert res.status_code == 202
    new_id = int(res.get_json()["data"]["jobId"].removeprefix("job_"))
    assert {j["id"]: j["superseded_by_job_id"] for j in _jobs()}[failed] == new_id
    listed = client.get("/api/jobs", headers=headers).get_json()["data"]
    assert f"job_{failed}" not in str(listed)


def test_retake_completed_job_with_unreadable_voice(client: FlaskClient, headers: dict[str, str]) -> None:
    done = _insert_job(_user_id(), "complete", failed_voice_causes=json.dumps({"tenor": "unreadable"}))
    clean = _insert_job(_user_id(), "complete")
    kw: dict[str, Any] = {"pages": [_img("JPEG")], "title": "t"}
    _err(_post(client, headers, replacesJobId=f"job_{clean}", **kw), 409, "not_retakeable")
    assert _post(client, headers, replacesJobId=f"job_{done}", **kw).status_code == 202
    # A completed job is superseded only when the retake completes, not at submit.
    assert {j["id"]: j["superseded_by_job_id"] for j in _jobs()}[done] is None


def test_retake_ref_string(client: FlaskClient, headers: dict[str, str]) -> None:
    failed = _insert_job(_user_id(), "failed", failure_reason="incomplete_voice_sequence")
    res = _post(client, headers, pages=[_img("JPEG")], title="t", replacesJobId=f"job_{failed}")
    assert res.status_code == 202


@pytest.mark.parametrize("ref", ["abc", "job_", "job_0x1", "12", "job_99999", "job_١"])
def test_retake_ref_malformed_404(client: FlaskClient, headers: dict[str, str], ref: str) -> None:
    _err(_post(client, headers, pages=[_img("JPEG")], title="t", replacesJobId=ref), 404, "job_not_found")


def test_client_submission_id_replay_returns_same_job(
    client: FlaskClient, app: Flask, headers: dict[str, str]
) -> None:
    kw: dict[str, Any] = {"pages": [_img("JPEG")], "title": "t", "clientSubmissionId": CSID}
    first = _post(client, headers, **kw)
    objects = dict(_storage(app).objects)
    with db.transaction() as conn:
        hits = conn.execute("SELECT count(*) AS n FROM throttle_hits").fetchone()["n"]
    second = _post(client, headers, **kw)
    assert (first.status_code, second.status_code) == (202, 202)
    assert second.get_json()["data"] == first.get_json()["data"]
    assert len(_jobs()) == 1
    assert _storage(app).objects == objects
    with db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM throttle_hits").fetchone()["n"] == hits
        stored = conn.execute("SELECT client_submission_id FROM jobs").fetchone()["client_submission_id"]
    assert stored == uuid.UUID(CSID)  # normalized to lowercase canonical, stored as uuid


def test_client_submission_id_replay_ignores_rate_limit(client: FlaskClient, headers: dict[str, str]) -> None:
    kw: dict[str, Any] = {"pages": [_img("JPEG")], "title": "t", "clientSubmissionId": CSID}
    assert _post(client, headers, **kw).status_code == 202
    for _ in range(RATE_LIMIT):
        _post(client, headers, pages=[_img("JPEG")], title="t")
    _err(_post(client, headers, pages=[_img("JPEG")], title="t"), 429, "rate_limited")
    assert _post(client, headers, **kw).status_code == 202


def test_client_submission_id_race_returns_existing(
    client: FlaskClient, app: Flask, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The replay lookup misses (simulated race) but the unique index catches the insert."""
    from backend import routes_jobs

    kw: dict[str, Any] = {"pages": [_img("JPEG")], "title": "t", "clientSubmissionId": CSID}
    first = _post(client, headers, **kw)
    keys_before = set(_storage(app).objects)
    real = routes_jobs.find_replay
    calls: list[int] = []

    def miss_once(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        calls.append(1)
        return None if len(calls) == 1 else real(*args, **kwargs)

    monkeypatch.setattr(routes_jobs, "find_replay", miss_once)
    second = _post(client, headers, **kw)
    assert second.status_code == 202
    assert second.get_json()["data"]["jobId"] == first.get_json()["data"]["jobId"]
    assert len(_jobs()) == 1
    new_keys = set(_storage(app).objects) - keys_before
    with db.transaction() as conn:
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions").fetchall()}
    assert queued == new_keys and len(new_keys) == 1  # queued for deletion; reservation released


@pytest.mark.parametrize("bad", ["abc", "123e4567e89b12d3a456426614174000", "{" + CSID + "}", "g" * 36])
def test_client_submission_id_malformed_400(client: FlaskClient, headers: dict[str, str], bad: str) -> None:
    res = _post(client, headers, pages=[_img("JPEG")], title="t", clientSubmissionId=bad)
    error = _err(res, 400, "invalid_client_submission_id")
    assert error["field"] == "clientSubmissionId"
    assert _jobs() == []


def test_client_submission_id_other_user_not_shared(client: FlaskClient, headers: dict[str, str]) -> None:
    other = _signup(client, "b@example.com")
    kw: dict[str, Any] = {"pages": [_img("JPEG")], "title": "t", "clientSubmissionId": CSID}
    a = _post(client, headers, **kw).get_json()["data"]["jobId"]
    b = _post(client, other, **kw)
    assert b.status_code == 202
    assert b.get_json()["data"]["jobId"] != a
    assert len(_jobs()) == 2


def test_active_job_cap_rejects_third_concurrent_job(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(max_active_jobs_per_user=2)
    headers = _signup(client)
    uid = _user_id()
    _insert_job(uid, "queued")
    _insert_job(uid, "transcribing")
    _insert_job(uid, "failed")  # finished jobs never count
    res = _post(client, headers, pages=[_img("JPEG")], title="t")
    error = _err(res, 429, "too_many_active_jobs")
    assert error["limit"] == 2
    assert res.headers["Retry-After"] == "60"
    assert len(_jobs()) == 3


def test_active_job_cap_counts_only_own_jobs(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(max_active_jobs_per_user=1)
    headers = _signup(client)
    _signup(client, "b@example.com")
    _insert_job(_user_id("b@example.com"), "queued")
    assert _post(client, headers, pages=[_img("JPEG")], title="t").status_code == 202


def test_active_job_cap_replay_with_same_client_submission_id_is_not_rejected(
    make_app: Callable[..., FlaskClient],
) -> None:
    client = make_app(max_active_jobs_per_user=1)
    headers = _signup(client)
    kw: dict[str, Any] = {"pages": [_img("JPEG")], "title": "t", "clientSubmissionId": CSID}
    first = _post(client, headers, **kw)
    second = _post(client, headers, **kw)  # at the cap now, but it is the same job
    assert (first.status_code, second.status_code) == (202, 202)
    assert second.get_json()["data"] == first.get_json()["data"]
    assert len(_jobs()) == 1
    _err(_post(client, headers, pages=[_img("JPEG")], title="t2"), 429, "too_many_active_jobs")
