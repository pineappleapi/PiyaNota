"""Tests for GET /api/jobs/<ref> and POST /api/jobs/<ref>/cancel (PIYA-102, PIYA-114)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from flask.testing import FlaskClient

from backend import db
from backend.tests.test_jobs_submit import _err, _img, _post, _signup, headers, make_app  # noqa: F401

READ_LIMIT = 3


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _submit(client: FlaskClient, headers: dict[str, str]) -> str:
    res = _post(client, headers, pages=[_img("JPEG"), _img("JPEG")], title="Bayan Ko")
    return str(res.get_json()["data"]["jobId"])


def _id(ref: str) -> int:
    return int(ref.split("_")[1])


def test_status_queued_shape(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _submit(client, headers)
    res = client.get(f"/api/jobs/{ref}", headers=headers)
    assert res.status_code == 200
    body = res.get_json()
    assert body["message"] == "Processing status retrieved"
    data = body["data"]
    assert set(data) == {
        "jobId", "status", "totalPages", "percentComplete", "failureReason", "failedVoices",
        "failedVoiceCauses", "title", "tempoBpm", "clientSubmissionId", "createdAt",
    }
    assert (data["jobId"], data["status"], data["totalPages"]) == (ref, "queued", 2)
    assert data["failureReason"] is None and data["failedVoices"] is None
    assert data["failedVoiceCauses"] is None and "scoreId" not in data


def test_status_in_progress_has_current_page(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _submit(client, headers)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status='transcribing', current_page=2, percent_complete=40")
    data = client.get(f"/api/jobs/{ref}", headers=headers).get_json()["data"]
    assert (data["currentPage"], data["percentComplete"]) == (2, 40)


def test_status_failed_has_reason_and_page(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _submit(client, headers)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status='failed', failure_reason='no_staves', failure_page_index=1")
    data = client.get(f"/api/jobs/{ref}", headers=headers).get_json()["data"]
    assert (data["failureReason"], data["pageIndex"]) == ("no_staves", 1)
    assert data["failedVoices"] is None and "currentPage" not in data


def test_status_complete_includes_score_and_voices(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _submit(client, headers)
    with db.transaction() as conn:
        user_id = conn.execute("SELECT user_id FROM jobs").fetchone()["user_id"]
        score = conn.execute(
            "INSERT INTO scores (user_id, title, page_count, tempo_source, review) "
            "VALUES (%s, 'Bayan Ko', 2, 'default', '{}') RETURNING id",
            (user_id,),
        ).fetchone()
        conn.execute(
            "UPDATE jobs SET status='complete', score_id=%s, percent_complete=100, arranger='Pia', "
            "key_signature='G', time_signature='3/4', "
            """failed_voices='["Tenor"]', failed_voice_causes='{"Tenor": "unreadable"}'""",
            (score["id"],),
        )
    data = client.get(f"/api/jobs/{ref}", headers=headers).get_json()["data"]
    assert data["scoreId"] == score["id"] and data["percentComplete"] == 100
    assert data["failedVoices"] == ["Tenor"] and data["failedVoiceCauses"] == {"Tenor": "unreadable"}
    assert (data["arranger"], data["keySignature"], data["timeSignature"]) == ("Pia", "G", "3/4")
    assert data["failureReason"] is None


def test_status_other_user_404(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _submit(client, headers)
    other = _signup(client, "b@example.com")
    _err(client.get(f"/api/jobs/{ref}", headers=other), 404, "job_not_found")


@pytest.mark.parametrize("ref", ["job_x", "7", "job_-1", "job_99999"])
def test_status_bad_ref_404(client: FlaskClient, headers: dict[str, str], ref: str) -> None:
    _err(client.get(f"/api/jobs/{ref}", headers=headers), 404, "job_not_found")


def test_status_read_limit_separate_from_submit(make_app: Callable[..., FlaskClient]) -> None:  # noqa: F811
    client = make_app(status_reads_per_minute=READ_LIMIT)
    hdrs = _signup(client)
    ref = _submit(client, hdrs)
    for _ in range(READ_LIMIT):
        assert client.get(f"/api/jobs/{ref}", headers=hdrs).status_code == 200
    err = _err(client.get(f"/api/jobs/{ref}", headers=hdrs), 429, "rate_limited")
    assert err["retryAfterSeconds"] >= 1
    assert _post(client, hdrs, pages=[_img("JPEG")], title="Again").status_code == 202


def test_cancel_queued(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _submit(client, headers)
    res = client.post(f"/api/jobs/{ref}/cancel", json={"jobId": "job_999"}, headers=headers)
    assert res.status_code == 200
    assert res.get_json()["data"] == {"jobId": ref, "status": "cancelled"}
    assert res.get_json()["message"] == "Processing cancelled"
    with db.transaction() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE id=%s", (_id(ref),)).fetchone()["status"] == "cancelled"
        keys = {r["object_key"] for r in conn.execute("SELECT object_key FROM job_pages").fetchall()}
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions").fetchall()}
    assert len(keys) == 2 and keys <= queued
    assert client.get(f"/api/jobs/{ref}", headers=headers).get_json()["data"]["status"] == "cancelled"


@pytest.mark.parametrize("status", ["complete", "failed", "cancelled"])
def test_cancel_terminal_409(client: FlaskClient, headers: dict[str, str], status: str) -> None:
    ref = _submit(client, headers)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status=%s", (status,))
    _err(client.post(f"/api/jobs/{ref}/cancel", headers=headers), 409, "job_terminal")


def test_cancel_other_user_404(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _submit(client, headers)
    other = _signup(client, "b@example.com")
    _err(client.post(f"/api/jobs/{ref}/cancel", headers=other), 404, "job_not_found")
    _err(client.post("/api/jobs/job_x/cancel", headers=other), 404, "job_not_found")
    with db.transaction() as conn:
        assert conn.execute("SELECT status FROM jobs").fetchone()["status"] == "queued"


def test_status_unowned_ids_are_metered(make_app: Callable[..., FlaskClient]) -> None:  # noqa: F811
    client = make_app(status_reads_per_minute=READ_LIMIT)
    hdrs = _signup(client)
    for _ in range(READ_LIMIT):
        _err(client.get("/api/jobs/job_99999", headers=hdrs), 404, "job_not_found")
    _err(client.get("/api/jobs/job_99999", headers=hdrs), 429, "rate_limited")


def test_cancel_job_with_score_locks_score_then_job(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _submit(client, headers)
    with db.transaction() as conn:
        user_id = conn.execute("SELECT user_id FROM jobs").fetchone()["user_id"]
        score = conn.execute(
            "INSERT INTO scores (user_id, title, page_count, tempo_source, review) "
            "VALUES (%s, 'Bayan Ko', 2, 'default', '{}') RETURNING id",
            (user_id,),
        ).fetchone()
        conn.execute("UPDATE jobs SET status='transcribing', score_id=%s", (score["id"],))
    res = client.post(f"/api/jobs/{ref}/cancel", headers=headers)
    assert res.status_code == 200
    with db.transaction() as conn:
        assert conn.execute("SELECT status FROM jobs").fetchone()["status"] == "cancelled"


LIST_CSID = "11111111-2222-4333-8444-555555555555"


def _list(client: FlaskClient, headers: dict[str, str]) -> list[dict[str, object]]:
    res = client.get("/api/jobs", headers=headers)
    assert res.status_code == 200
    return list(res.get_json()["data"]["jobs"])


def test_list_requires_auth(client: FlaskClient) -> None:
    assert client.get("/api/jobs").status_code == 401


def test_list_scoped_ordered_and_echoes_fields(client: FlaskClient, headers: dict[str, str]) -> None:
    first = _post(client, headers, pages=[_img("JPEG")], title="One", clientSubmissionId=LIST_CSID)
    second = _submit(client, headers)
    other = _signup(client, "b@example.com")
    _post(client, other, pages=[_img("JPEG")], title="Theirs")
    items = _list(client, headers)
    assert [i["jobId"] for i in items] == [second, first.get_json()["data"]["jobId"]]
    assert items[1]["clientSubmissionId"] == LIST_CSID and items[0]["clientSubmissionId"] is None
    assert {"title", "status", "percentComplete", "failureReason", "failedVoices", "createdAt"} <= set(items[0])
    assert len(_list(client, other)) == 1


def test_list_window_and_cap(client: FlaskClient, headers: dict[str, str]) -> None:
    from backend import routes_jobs

    for _ in range(3):
        _submit(client, headers)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status='failed', failure_reason='x', created_at = now() - interval '8 days'"
                     " WHERE id = (SELECT min(id) FROM jobs)")
        conn.execute("UPDATE jobs SET created_at = now() - interval '30 days'"
                     " WHERE id = (SELECT max(id) FROM jobs)")  # still queued: active stays listed
    assert len(_list(client, headers)) == 2
    routes_jobs.LIST_MAX_ITEMS, saved = 1, routes_jobs.LIST_MAX_ITEMS
    try:
        assert len(_list(client, headers)) == 1
    finally:
        routes_jobs.LIST_MAX_ITEMS = saved


def test_list_rate_limited(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(list_reads_per_minute=READ_LIMIT)
    headers = _signup(client)
    for _ in range(READ_LIMIT):
        assert client.get("/api/jobs", headers=headers).status_code == 200
    assert client.get("/api/jobs", headers=headers).status_code == 429


def test_list_and_status_polling_use_separate_buckets(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(list_reads_per_minute=READ_LIMIT, status_reads_per_minute=READ_LIMIT)
    headers = _signup(client)
    ref = _submit(client, headers)
    for _ in range(READ_LIMIT):
        assert client.get("/api/jobs", headers=headers).status_code == 200
    assert client.get("/api/jobs", headers=headers).status_code == 429
    assert client.get(f"/api/jobs/{ref}", headers=headers).status_code == 200  # list did not eat the poll budget


def test_list_omits_deleted_score_and_superseded_job(client: FlaskClient, headers: dict[str, str]) -> None:
    kept, deleted, replaced = _submit(client, headers), _submit(client, headers), _submit(client, headers)
    with db.transaction() as conn:
        uid = conn.execute("SELECT id FROM users").fetchone()["id"]
        score = conn.execute(
            "INSERT INTO scores (user_id, title, page_count, tempo_source, review, deleted_at) "
            "VALUES (%s, 'Gone', 2, 'default', '{}', now()) RETURNING id", (uid,)).fetchone()
        conn.execute("UPDATE jobs SET status='complete', score_id=%s WHERE id=%s", (score["id"], _id(deleted)))
        conn.execute("UPDATE jobs SET superseded_by_job_id=%s WHERE id=%s", (_id(kept), _id(replaced)))
    assert [i["jobId"] for i in _list(client, headers)] == [kept]
