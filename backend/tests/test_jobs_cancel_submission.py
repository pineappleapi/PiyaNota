"""Cancel by clientSubmissionId, cancelled-retake restore, and worker failure text -> app code mapping."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from flask.testing import FlaskClient

from backend import db
from backend.tests.test_jobs_submit import _err, _img, _post, _signup, headers, make_app  # noqa: F401

READ_LIMIT = 3
CSID = "123e4567-e89b-12d3-a456-426614174000"
REAL_WORKER_REASONS = {  # exact strings the worker writes -> code the app's FailureReason parses
    "no readable page": "preprocessing_error",
    "unreadable page image": "preprocessing_error",
    "no readable staves": "no_staff_detected",
    "could not read the notation": "no_staff_detected",
    "no readable staves, please retake clearer photos of your pages": "incomplete_voice_sequence",
    "audio rendering failed": "synthesis_failed",
    "no playable audio could be built": "synthesis_failed",
    "max_runtime_exceeded": "stage_timeout",
    "worker_timeout": "server_restart",
    "service misconfigured": "internal_error",
    "conversion failed": "internal_error",
}


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _submit(client: FlaskClient, headers: dict[str, str]) -> str:
    return str(_post(client, headers, pages=[_img("JPEG")], title="Bayan Ko").get_json()["data"]["jobId"])


@pytest.mark.parametrize("raw,code", sorted(REAL_WORKER_REASONS.items()))
def test_real_worker_failure_text_maps_to_app_code(client: FlaskClient, headers: dict[str, str], raw: str, code: str) -> None:
    ref = _submit(client, headers)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status='failed', failure_reason=%s", (raw,))
    for data in (client.get(f"/api/jobs/{ref}", headers=headers).get_json()["data"],
                 client.get("/api/jobs", headers=headers).get_json()["data"]["jobs"][0]):
        assert (data["failureReason"], data["failureDetail"]) == (code, raw)


def test_every_worker_reason_constant_is_mapped() -> None:
    from backend.failure_codes import _CODES
    from backend.worker import main, pipeline

    for text in (*pipeline.STAGE_FAILURE_REASONS.values(), pipeline.NO_VOICES_REASON, pipeline.MISCONFIGURED_REASON,
                 main.UNEXPECTED_FAILURE_REASON, main.NO_PLAYBACK_FAILURE_REASON):
        assert text in _CODES, text


def test_cancel_submission_before_job_exists_blocks_later_submit(client: FlaskClient, headers: dict[str, str]) -> None:
    res = client.post(f"/api/jobs/by-submission/{CSID.upper()}/cancel", headers=headers)
    assert res.status_code == 200
    assert res.get_json()["data"] == {"clientSubmissionId": CSID, "jobId": None, "status": "cancelled"}
    assert client.post(f"/api/jobs/by-submission/{CSID}/cancel", headers=headers).status_code == 200  # idempotent
    _err(_post(client, headers, pages=[_img("JPEG")], title="t", clientSubmissionId=CSID), 409, "submission_cancelled")
    with db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0
    other = _signup(client, "b@example.com")  # owner-scoped: another user's same id is unaffected
    assert _post(client, other, pages=[_img("JPEG")], title="t", clientSubmissionId=CSID).status_code == 202


def test_cancel_submission_cancels_existing_job_and_replay_is_rejected(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _post(client, headers, pages=[_img("JPEG")], title="t", clientSubmissionId=CSID).get_json()["data"]["jobId"]
    res = client.post(f"/api/jobs/by-submission/{CSID}/cancel", headers=headers)
    assert res.get_json()["data"] == {"clientSubmissionId": CSID, "jobId": ref, "status": "cancelled"}
    assert client.get(f"/api/jobs/{ref}", headers=headers).get_json()["data"]["status"] == "cancelled"
    again = client.post(f"/api/jobs/by-submission/{CSID}/cancel", headers=headers)
    assert again.get_json()["data"]["status"] == "cancelled"
    _err(_post(client, headers, pages=[_img("JPEG")], title="t", clientSubmissionId=CSID), 409, "submission_cancelled")
    with db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM cancelled_submissions").fetchone()["n"] == 0


def test_cancel_submission_of_finished_job_reports_status(client: FlaskClient, headers: dict[str, str]) -> None:
    _post(client, headers, pages=[_img("JPEG")], title="t", clientSubmissionId=CSID)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status='failed', failure_reason='x'")
    res = client.post(f"/api/jobs/by-submission/{CSID}/cancel", headers=headers)
    assert (res.status_code, res.get_json()["data"]["status"]) == (200, "failed")


def test_cancel_submission_bad_id_unauthenticated_and_rate_limited(make_app: Callable[..., FlaskClient]) -> None:  # noqa: F811
    client = make_app(status_reads_per_minute=READ_LIMIT)
    hdrs = _signup(client)
    _err(client.post("/api/jobs/by-submission/not-a-uuid/cancel", headers=hdrs), 400, "invalid_client_submission_id")
    assert client.post(f"/api/jobs/by-submission/{CSID}/cancel").status_code == 401
    for _ in range(READ_LIMIT):
        assert client.post(f"/api/jobs/by-submission/{CSID}/cancel", headers=hdrs).status_code == 200
    _err(client.post(f"/api/jobs/by-submission/{CSID}/cancel", headers=hdrs), 429, "rate_limited")


def test_cancelled_retake_restores_the_failed_job(client: FlaskClient, headers: dict[str, str]) -> None:
    old = _submit(client, headers)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET status='failed', failure_reason='no readable staves'")
    retake = _post(client, headers, pages=[_img("JPEG")], title="t", replacesJobId=old).get_json()["data"]["jobId"]
    listed = [j["jobId"] for j in client.get("/api/jobs", headers=headers).get_json()["data"]["jobs"]]
    assert listed == [retake]
    assert client.post(f"/api/jobs/{retake}/cancel", headers=headers).status_code == 200
    listed = {j["jobId"] for j in client.get("/api/jobs", headers=headers).get_json()["data"]["jobs"]}
    assert old in listed
    assert _post(client, headers, pages=[_img("JPEG")], title="t", replacesJobId=old).status_code == 202  # retakeable again
