"""Contract tests J1-J8 against the real app and Postgres: response shapes only.

Deep logic lives in the per-feature files; these pin the keys, types, status codes and headers
the Flutter app builds to (joint-contract.md, "as built" bullets).
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from backend import background, db
from backend.storage import MemoryStorage
from backend.tests.test_account import EMAIL, PASSWORD, WRONG, _auth, _login, _signup
from backend.tests.test_account_delete import _delete, _seed_blobs
from backend.tests.test_jobs_submit import _err, _img, _post, _storage, headers  # noqa: F401
from backend.tests.test_password_reset import MemoryMailer, _confirm, _request, _verify, _wrong
from backend.tests.test_score_limit import _fill, _upload
from backend.tests.test_scores import VOICES, _score, _uid

FILE_KEYS = {"url", "fileId", "sizeBytes"}
LOGIN_WAIT_S = 30


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


@pytest.fixture
def mail(app: Flask) -> MemoryMailer:
    m = app.extensions["mailer"]
    assert isinstance(m, MemoryMailer)
    return m


def _bad_login(client: FlaskClient) -> Any:
    return _login(client, WRONG)


def test_j1_verify_shapes(client: FlaskClient, mail: MemoryMailer) -> None:
    _signup(client)
    assert _verify(client, "123456").get_json()["error"]["code"] == "reset_token_expired_or_invalid"
    _request(client)
    code = mail.sent[0][1]
    res = _verify(client, _wrong(code))
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "reset_code_invalid"
    res = _verify(client, code)
    secs = res.get_json()["data"]["expiresInSeconds"]
    assert res.status_code == 200 and isinstance(secs, int) and secs >= 1
    for _ in range(3):
        _verify(client, _wrong(code))
    res = _verify(client, _wrong(code))  # 5th wrong
    assert res.status_code == 400
    assert res.get_json()["error"]["retryAfterSeconds"] == LOGIN_WAIT_S
    assert res.headers["Retry-After"] == str(LOGIN_WAIT_S)
    with db.transaction() as conn:  # code survived verify: /confirm still accepts it
        conn.execute("UPDATE throttle_backoff SET wait_until = now() - interval '1 second'")
    assert _confirm(client, code).status_code == 200


def test_j2_login_ladder_shapes(client: FlaskClient) -> None:
    _signup(client)
    for remaining in (4, 3, 2, 1):
        res = _bad_login(client)
        err = res.get_json()["error"]
        assert res.status_code == 401 and err["code"] == "invalid_credentials"
        assert err["attemptsRemaining"] == remaining and "retryAfterSeconds" not in err
    res = _bad_login(client)
    err = res.get_json()["error"]
    assert res.status_code == 401 and err["code"] == "invalid_credentials"
    assert err["retryAfterSeconds"] == LOGIN_WAIT_S and "attemptsRemaining" not in err
    assert res.headers["Retry-After"] == str(LOGIN_WAIT_S)
    res = _login(client)  # right password during the wait is still refused
    assert res.status_code == 429 and res.get_json()["error"]["code"] == "rate_limited"
    assert int(res.headers["Retry-After"]) > 0


def test_j3_delete_account_shapes(client: FlaskClient) -> None:
    token = _signup(client)
    res = _delete(client, token, WRONG)
    assert res.status_code == 403 and res.get_json()["error"]["code"] == "invalid_current_password"
    assert _delete(client, token).status_code == 200
    assert client.get("/api/scores", headers=_auth(token)).status_code == 401
    assert _login(client).status_code == 401
    assert _signup(client)  # same email signs up again (asserts 201)


def test_j4_result_shape(client: FlaskClient, headers: dict[str, str]) -> None:
    uid = _uid()
    with_midi, _ = _score(uid, tag="m", midi=True)
    old, _ = _score(uid, tag="o")
    storage = _storage(client.application)
    for key in ("timing/m.json", "pages/m0.jpg", "pages/m1.jpg", *(f"audio/m{v}.mp3" for v in VOICES),
                *(f"midi/m{v}.mid" for v in VOICES)):
        storage.put(key, b"x", "x")
    data = client.get(f"/api/scores/{with_midi}/result", headers=headers).get_json()["data"]
    assert {"audioTracks", "scoreImages", "timingMetadataUrl", "review"} <= set(data)  # old keys stay
    assert set(data["audioFiles"]) == set(VOICES) and set(data["midiTracks"]) == set(VOICES)
    entries = [*data["audioFiles"].values(), *data["pageFiles"], data["timingFile"],
               *data["midiTracks"].values()]
    assert len(data["pageFiles"]) == 2
    for e in entries:
        assert set(e) == FILE_KEYS and isinstance(e["fileId"], str) and isinstance(e["sizeBytes"], int)
    data = client.get(f"/api/scores/{old}/result", headers=headers).get_json()["data"]
    assert data["midiTracks"] is None and set(data["audioFiles"]) == set(VOICES)


def test_j5_percent_complete_shape(client: FlaskClient, headers: dict[str, str]) -> None:
    ref = _post(client, headers, pages=[_img("JPEG")], title="t").get_json()["data"]["jobId"]
    base = set(client.get(f"/api/jobs/{ref}", headers=headers).get_json()["data"])
    for status, pct in (("preprocessing", 5), ("transcribing", 80), ("synthesizing", 99)):
        with db.transaction() as conn:
            conn.execute("UPDATE jobs SET status = %s, percent_complete = %s", (status, pct))
        data = client.get(f"/api/jobs/{ref}", headers=headers).get_json()["data"]
        assert type(data["percentComplete"]) is int and 0 <= data["percentComplete"] < 100
        assert set(data) - base <= {"currentPage"} and base <= set(data)


def test_j6_storage_failure_leaves_nothing(client: FlaskClient, headers: dict[str, str]) -> None:
    storage = _storage(client.application)

    def boom(key: str, data: bytes, content_type: str) -> None:
        raise ConnectionError("down")

    storage.put = boom  # type: ignore[method-assign]
    res = _post(client, headers, pages=[_img("JPEG")], title="t")
    assert res.status_code == 500 and "error" in res.get_json()
    with db.transaction() as conn:
        for table in ("jobs", "job_pages", "scores", "storage_deletions"):
            n = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]  # noqa: S608
            assert n == 0, table
    assert storage.objects == {}


def test_j8_score_limit_shapes(client: FlaskClient, headers: dict[str, str]) -> None:
    scores = _fill(20)
    error = _err(_upload(client, headers), 409, "score_limit_reached")
    assert error["limit"] == 20
    assert client.delete(f"/api/scores/{scores[0][0]}", headers=headers).status_code == 200
    _err(client.get(f"/api/scores/{scores[0][0]}/result", headers=headers), 404, "score_not_found")
    assert _upload(client, headers).status_code == 202


def test_account_delete_leaves_no_blob_with_midi_key(app: Flask, client: FlaskClient) -> None:
    token = _signup(client)
    uid, keys = _seed_blobs(app, EMAIL)
    assert any(k.startswith("midi/") for k in keys)
    assert _delete(client, token).status_code == 200
    storage = app.extensions["storage"]
    assert isinstance(storage, MemoryStorage)
    background.run_deletions(storage)
    assert not (keys & set(storage.objects))
