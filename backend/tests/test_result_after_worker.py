"""App contract: what /result serves after the worker finishes a job (Task 6)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest
from flask import Flask

from backend import db
from backend.worker import main as worker_main
from backend.app import create_app
from backend.config import Settings
from backend.tests.test_jobs_submit import _signup
from backend.tests.test_worker_main import _jpeg, _result, _runner
from backend.worker.main import process_one

BASE = "https://piya.test"
PAGE_COUNT = 2


@pytest.fixture(autouse=True)
def _stub_combined_midi(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake pipeline result carries no bars; without a stub the job fails with no playable audio."""
    monkeypatch.setattr(worker_main, "_combined_midi", lambda result, timing: b"MThd-stub")


@pytest.fixture
def db_settings(settings: Settings) -> Settings:
    return dataclasses.replace(settings, storage_backend="db", public_base_url=BASE)


@pytest.fixture
def app(db_settings: Settings) -> Iterator[Flask]:
    flask_app = create_app(db_settings)
    flask_app.config["TESTING"] = True
    yield flask_app
    db.close_pool()


def test_result_serves_cleaned_pages_sizes_and_absolute_media_urls(
    app: Flask, db_settings: Settings, db_clean: None
) -> None:
    client = app.test_client()
    headers = _signup(client)
    storage = app.extensions["storage"]
    with db.transaction() as conn:
        uid = conn.execute("SELECT id FROM users").fetchone()["id"]
        job = conn.execute(
            "INSERT INTO jobs (user_id, status, source, page_count, title, tempo_bpm, tempo_source) "
            "VALUES (%s, 'queued', 'images', %s, 'Bayan Ko', 100, 'user') RETURNING id", (uid, PAGE_COUNT)).fetchone()
        for i in range(PAGE_COUNT):
            conn.execute("INSERT INTO job_pages (job_id, page_index, object_key, width, height) "
                         "VALUES (%s, %s, %s, 80, 60)", (job["id"], i, f"pages/old{i}.jpg"))
            storage.put(f"pages/old{i}.jpg", _jpeg(), "image/jpeg")
    result = _result(voices=("soprano", "alto", "bass"), failed=["tenor"])
    assert process_one(storage=storage, runner=_runner(result), settings=db_settings) is True
    with db.transaction() as conn:
        score_id = conn.execute("SELECT score_id FROM jobs WHERE id = %s", (job["id"],)).fetchone()["score_id"]

    data = client.get(f"/api/scores/{score_id}/result", headers=headers).get_json()["data"]
    assert data["scoreImageSizes"] == [{"width": 40, "height": 30}] * PAGE_COUNT
    assert set(data["audioTracks"]) == {"soprano", "alto", "bass"} and data["failedVoices"] == ["tenor"]
    urls = [*data["audioTracks"].values(), *data["scoreImages"], data["timingMetadataUrl"]]
    assert all(u.startswith(BASE + "/media/") for u in urls)
    audio = client.get(data["audioTracks"]["alto"].removeprefix(BASE))
    assert audio.status_code == 200 and audio.data == b"mp3-alto"
    timing = client.get(data["timingMetadataUrl"].removeprefix(BASE), headers={"Range": "bytes=0-"})
    assert timing.status_code == 206 and timing.get_json() == {"events": []}
