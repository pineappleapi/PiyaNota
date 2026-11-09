"""Score cap of 20 and the 7-day soft-delete window (V2 B11, J8)."""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from backend import background, db
from backend.routes_jobs import MAX_SCORES_PER_USER
from backend.tests.test_jobs_submit import _err, _img, _post, _signup, _storage, headers  # noqa: F401
from backend.tests.test_scores import VOICES, _retake, _score, _uid

FAILED = "incomplete_voice_sequence"
UNREADABLE_TENOR = '{"tenor": "unreadable"}'


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _fill(count: int) -> list[tuple[int, int]]:
    uid = _uid()
    return [_score(uid, f"S{i}", tag=f"s{i}") for i in range(count)]


def _job(status: str, failure_reason: str | None = None) -> int:
    with db.transaction() as conn:
        row = conn.execute(
            "INSERT INTO jobs (user_id, status, source, page_count, title, tempo_source, failure_reason) "
            "VALUES (%s, %s, 'images', 1, 't', 'user', %s) RETURNING id",
            (_uid(), status, failure_reason),
        ).fetchone()
    return int(row["id"])


def _age(score_id: int, interval: str) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE scores SET deleted_at = now() - %s::interval WHERE id = %s", (interval, score_id))


def _upload(client: FlaskClient, headers: dict[str, str], **kw: Any) -> Any:
    return _post(client, headers, pages=[_img("JPEG")], title="t", **kw)


def _queued() -> set[str]:
    with db.transaction() as conn:
        return {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions")}


def _purge() -> int:
    with db.transaction() as conn:
        return background.purge_deleted_scores(conn)


def test_21st_upload_409_with_limit(client: FlaskClient, headers: dict[str, str]) -> None:
    _fill(MAX_SCORES_PER_USER)
    error = _err(_upload(client, headers), 409, "score_limit_reached")
    assert error["limit"] == 20


def test_below_limit_allowed(client: FlaskClient, headers: dict[str, str]) -> None:
    _fill(MAX_SCORES_PER_USER - 1)
    assert _upload(client, headers).status_code == 202


def test_converting_jobs_count(client: FlaskClient, headers: dict[str, str]) -> None:
    _fill(MAX_SCORES_PER_USER - 1)
    _job("queued")
    _err(_upload(client, headers), 409, "score_limit_reached")


def test_fail_fast_before_page_upload(client: FlaskClient, app: Flask, headers: dict[str, str]) -> None:
    _fill(MAX_SCORES_PER_USER)
    storage = _storage(app)

    def no_put(key: str, data: bytes, content_type: str) -> None:
        raise AssertionError("page uploaded although the user is at the limit")

    storage.put = no_put  # type: ignore[method-assign]
    _err(_upload(client, headers), 409, "score_limit_reached")


def test_delete_one_lets_next_through(client: FlaskClient, headers: dict[str, str]) -> None:
    scores = _fill(MAX_SCORES_PER_USER)
    _err(_upload(client, headers), 409, "score_limit_reached")
    assert client.delete(f"/api/scores/{scores[0][0]}", headers=headers).status_code == 200
    assert _upload(client, headers).status_code == 202


def test_retake_of_complete_score_not_blocked(client: FlaskClient, headers: dict[str, str]) -> None:
    scores = _fill(MAX_SCORES_PER_USER)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET failed_voice_causes = %s WHERE id = %s", (UNREADABLE_TENOR, scores[0][1]))
    assert _upload(client, headers, replacesJobId=f"job_{scores[0][1]}").status_code == 202
    # The running retake of a complete score adds no slot, but a new upload is still refused.
    _err(_upload(client, headers), 409, "score_limit_reached")


def test_retake_of_failed_job_counts(client: FlaskClient, headers: dict[str, str]) -> None:
    _fill(MAX_SCORES_PER_USER)
    failed = _job("failed", FAILED)
    _err(_upload(client, headers, replacesJobId=f"job_{failed}"), 409, "score_limit_reached")


def test_deleted_score_invisible_and_404(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, jid = _score(_uid(), tag="d")
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET failed_voice_causes = %s WHERE id = %s", (UNREADABLE_TENOR, jid))
    assert client.delete(f"/api/scores/{sid}", headers=headers).status_code == 200
    assert client.get("/api/scores", headers=headers).get_json()["data"]["scores"] == []
    _err(client.get(f"/api/scores/{sid}/result", headers=headers), 404, "score_not_found")
    _err(client.patch(f"/api/scores/{sid}", json={"title": "x"}, headers=headers), 404, "score_not_found")
    _err(client.delete(f"/api/scores/{sid}", headers=headers), 404, "score_not_found")
    _err(_upload(client, headers, replacesJobId=f"job_{jid}"), 404, "job_not_found")


def test_purge_waits_for_day_7_then_removes_everything(client: FlaskClient, headers: dict[str, str]) -> None:
    uid = _uid()
    sid, jid = _score(uid, tag="d", midi=True)
    rid = _retake(uid, jid, "transcribing")
    keep, _ = _score(uid, "Keep", tag="k")
    expected = {"thumbs/dt.jpg", "timing/d.json", "pages/d0.jpg", "pages/d1.jpg", "pages/retake0.jpg",
                *(f"audio/d{v}.mp3" for v in VOICES), *(f"midi/d{v}.mid" for v in VOICES)}
    assert client.delete(f"/api/scores/{sid}", headers=headers).status_code == 200
    _age(sid, "6 days")
    assert _purge() == 0
    with db.transaction() as conn:
        assert conn.execute("SELECT 1 FROM scores WHERE id = %s", (sid,)).fetchone() is not None
    assert not (_queued() & {"audio/dsoprano.mp3", "timing/d.json", "thumbs/dt.jpg", "pages/d0.jpg"})
    _age(sid, "7 days 1 minute")
    assert _purge() == 1
    assert expected <= _queued()
    with db.transaction() as conn:
        assert conn.execute("SELECT 1 FROM scores WHERE id = %s", (sid,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM jobs WHERE id = ANY(%s)", ([jid, rid],)).fetchone() is None
        assert conn.execute("SELECT count(*) AS n FROM job_pages").fetchone()["n"] == 2  # only Keep's pages
        assert conn.execute("SELECT 1 FROM scores WHERE id = %s", (keep,)).fetchone() is not None
    before = _queued()
    assert _purge() == 0  # idempotent
    assert _queued() == before


def test_account_delete_purges_soft_deleted_blobs(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid(), tag="d")
    assert client.delete(f"/api/scores/{sid}", headers=headers).status_code == 200
    with db.transaction() as conn:
        background.purge_user(conn, _uid())
    assert {"audio/dsoprano.mp3", "timing/d.json", "thumbs/dt.jpg", "pages/d0.jpg"} <= _queued()


def test_purge_failure_on_one_score_does_not_block_others(
    client: FlaskClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = _uid()
    ids = [_score(uid, f"S{i}", tag=f"p{i}")[0] for i in range(3)]
    for sid in ids:
        assert client.delete(f"/api/scores/{sid}", headers=headers).status_code == 200
        _age(sid, "8 days")
    real = background.queue_deletion

    def flaky(conn: Any, keys: Any) -> None:
        keys = list(keys)
        if any("p1" in k for k in keys):
            raise RuntimeError("boom")
        real(conn, keys)

    monkeypatch.setattr(background, "queue_deletion", flaky)
    assert _purge() == 2
    with db.transaction() as conn:
        left = [r["id"] for r in conn.execute("SELECT id FROM scores")]
    assert left == [ids[1]]
