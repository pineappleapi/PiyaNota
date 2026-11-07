"""Tests for atomic job completion (PIYA-321) and the operator jobs CLI."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from PIL import Image

from backend import completion, db
from backend.config import Settings
from backend.scripts import jobs_cli
from backend.storage import MemoryStorage

VOICES = ("soprano", "alto", "tenor", "bass")
REVIEW = {"reviewNeeded": False, "reasons": [], "items": [], "truncated": False}
PAGE_SQL = (
    "INSERT INTO job_pages (job_id, page_index, object_key, width, height) VALUES (%s, 0, %s, 800, 600)"
)


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """Point the CLI's load_settings() at the test database."""
    monkeypatch.setenv("PIYA_ENV", "test")
    monkeypatch.setenv("PIYA_DATABASE_URL", settings.database_url)


def _jpeg(size: tuple[int, int] = (800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "JPEG")
    return buf.getvalue()


def _user(conn: Any) -> int:
    row = conn.execute("INSERT INTO users (email, password_hash) VALUES ('a@example.com', 'x') RETURNING id").fetchone()
    return int(row["id"])


def _job(conn: Any, user_id: int, **extra: Any) -> int:
    cols = {"user_id": user_id, "status": "queued", "source": "images", "page_count": 2, "title": "Bayan Ko",
            "arranger": "Pia", "tempo_bpm": 100, "tempo_source": "user", "key_signature": "G",
            "time_signature": "3/4", **extra}
    row = conn.execute(
        f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
        list(cols.values()),
    ).fetchone()
    return int(row["id"])


def _args(tag: str = "") -> dict[str, Any]:
    return dict(
        audio_keys={v: f"audio/{tag}{v}.mp3" for v in VOICES}, timing_key=f"timing/{tag}t.json",
        failed_voices=[], failed_voice_causes={}, review=REVIEW, muted_measures=[],
        thumbnail_key=f"thumbs/{tag}t.jpg",
        midi_keys={v: f"midi/{tag}{v}.mid" for v in VOICES},
        midi_combined_key=f"midi/{tag}combined.mid",
    )


def test_complete_creates_score_copying_metadata(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        score_id = completion.complete_job(conn, job_id, **_args())
        score = conn.execute("SELECT * FROM scores WHERE id = %s", (score_id,)).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        tracks = conn.execute("SELECT count(*) AS n FROM audio_tracks WHERE score_id = %s", (score_id,)).fetchone()
    assert (score["title"], score["arranger"], score["page_count"], score["tempo_bpm"]) == ("Bayan Ko", "Pia", 2, 100)
    assert (score["tempo_source"], score["key_signature"], score["time_signature"]) == ("user", "G", "3/4")
    assert (job["status"], job["score_id"], job["percent_complete"]) == ("complete", score_id, 100)
    assert job["completed_at"] is not None and tracks["n"] == 4


def test_complete_is_atomic(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
    bad = {**_args(), "audio_keys": {"soprano": "a", "alto": "b", "tenor": "c", "bogus": "d"}}
    with pytest.raises(Exception, match="audio_tracks"), db.transaction() as conn:
        completion.complete_job(conn, job_id, **bad)
    with db.transaction() as conn:
        assert conn.execute("SELECT status FROM jobs").fetchone()["status"] == "queued"
        assert conn.execute("SELECT count(*) AS n FROM scores").fetchone()["n"] == 0


def test_complete_cancelled_job_returns_none(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn), status="cancelled")
        assert completion.complete_job(conn, job_id, **_args()) is None
        assert conn.execute("SELECT count(*) AS n FROM scores").fetchone()["n"] == 0


def _completed_original(conn: Any, user_id: int) -> tuple[int, int]:
    old_job = _job(conn, user_id)
    conn.execute(PAGE_SQL, (old_job, "pages/old.jpg"))
    score_id = completion.complete_job(conn, old_job, **_args("old-"))
    assert score_id is not None
    conn.execute("UPDATE scores SET last_accessed_at = '2026-01-01T00:00:00Z' WHERE id = %s", (score_id,))
    return old_job, score_id


def test_retake_completion_updates_same_score(app: Flask) -> None:
    with db.transaction() as conn:
        user_id = _user(conn)
        old_job, score_id = _completed_original(conn, user_id)
        retake = _job(conn, user_id, replaces_job_id=old_job, title="Bayan Ko 2")
        assert completion.complete_job(conn, retake, **_args("new-")) == score_id
        score = conn.execute("SELECT * FROM scores WHERE id = %s", (score_id,)).fetchone()
        old = conn.execute("SELECT * FROM jobs WHERE id = %s", (old_job,)).fetchone()
        new = conn.execute("SELECT * FROM jobs WHERE id = %s", (retake,)).fetchone()
        rows = conn.execute("SELECT file_key FROM audio_tracks WHERE score_id = %s", (score_id,)).fetchall()
        midi_rows = conn.execute("SELECT midi_key FROM audio_tracks WHERE score_id = %s", (score_id,)).fetchall()
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions").fetchall()}
    assert score["title"] == "Bayan Ko 2" and score["last_accessed_at"].year == 2026
    assert {r["file_key"] for r in rows} == {f"audio/new-{v}.mp3" for v in VOICES}
    assert {"audio/old-soprano.mp3", "timing/old-t.json", "thumbs/old-t.jpg", "pages/old.jpg"} <= queued
    assert {f"midi/old-{v}.mid" for v in VOICES} <= queued  # no MIDI blob left behind by the replace
    assert not {f"midi/new-{v}.mid" for v in VOICES} & queued
    assert {r["midi_key"] for r in midi_rows} == {f"midi/new-{v}.mid" for v in VOICES}
    assert score["midi_combined_key"] == "midi/new-combined.mid"
    assert "midi/old-combined.mid" in queued and "midi/new-combined.mid" not in queued  # FR-12 on retake
    assert (old["superseded_by_job_id"], old["score_id"]) == (retake, None)
    assert (new["status"], new["score_id"]) == ("complete", score_id)


def test_retake_of_deleted_score_cancels(app: Flask) -> None:
    with db.transaction() as conn:
        user_id = _user(conn)
        old_job, score_id = _completed_original(conn, user_id)
        retake = _job(conn, user_id, replaces_job_id=old_job)
        conn.execute("DELETE FROM scores WHERE id = %s", (score_id,))
        assert completion.complete_job(conn, retake, **_args("new-")) is None
        assert conn.execute("SELECT status FROM jobs WHERE id = %s", (retake,)).fetchone()["status"] == "cancelled"


def test_cli_complete_end_to_end(app: Flask, cli_env: None, tmp_path: Path) -> None:
    storage = MemoryStorage()
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        conn.execute(PAGE_SQL, (job_id, "pages/p0.jpg"))
    storage.put("pages/p0.jpg", _jpeg(), "image/jpeg")
    for voice in VOICES:
        (tmp_path / f"{voice}.mp3").write_bytes(b"ID3" + voice.encode())
    assert jobs_cli.main(["complete", str(job_id), "--audio-dir", str(tmp_path)], storage=storage) == 0
    with db.transaction() as conn:
        score = conn.execute("SELECT * FROM scores").fetchone()
        tracks = conn.execute("SELECT file_key FROM audio_tracks").fetchall()
        left = conn.execute("SELECT count(*) AS n FROM storage_deletions").fetchone()["n"]
    assert len(tracks) == 4 and left == 0 and score["review"]["reviewNeeded"] is True
    thumb = Image.open(io.BytesIO(storage.objects[score["thumbnail_key"]]))
    assert max(thumb.size) == completion.THUMBNAIL_LONG_SIDE_PX
    assert all(t["file_key"] in storage.objects for t in tracks)


def test_cli_rejects_midi(app: Flask, cli_env: None, tmp_path: Path) -> None:
    (tmp_path / "soprano.mid").write_bytes(b"MThd")
    assert jobs_cli.main(["complete", "1", "--audio-dir", str(tmp_path)], storage=MemoryStorage()) == 2


def test_cli_missing_audio_dir_exits_2(
    app: Flask, cli_env: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope"
    assert jobs_cli.main(["complete", "1", "--audio-dir", str(missing)], storage=MemoryStorage()) == 2
    assert "not a directory" in capsys.readouterr().err


def test_cli_fetch_pages_and_fail(app: Flask, cli_env: None, tmp_path: Path) -> None:
    storage = MemoryStorage()
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        conn.execute(PAGE_SQL, (job_id, "pages/p0.jpg"))
    storage.put("pages/p0.jpg", b"jpg", "image/jpeg")
    assert jobs_cli.main(["fetch-pages", str(job_id), str(tmp_path / "out")], storage=storage) == 0
    assert (tmp_path / "out" / "page_000.jpg").read_bytes() == b"jpg"
    assert jobs_cli.main(["fail", str(job_id), "no_staves", "--page", "0"], storage=storage) == 0
    with db.transaction() as conn:
        row = conn.execute("SELECT status, failure_reason, failure_page_index FROM jobs").fetchone()
    assert (row["status"], row["failure_reason"], row["failure_page_index"]) == ("failed", "no_staves", 0)


def test_complete_already_complete_returns_none(app: Flask) -> None:
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn))
        first = completion.complete_job(conn, job_id, **_args())
        assert completion.complete_job(conn, job_id, **_args("again-")) is None
        assert conn.execute("SELECT count(*) AS n FROM scores").fetchone()["n"] == 1
        assert conn.execute("SELECT score_id FROM jobs").fetchone()["score_id"] == first


def _cli_job(tmp_path: Path, **extra: Any) -> tuple[int, MemoryStorage]:
    storage = MemoryStorage()
    with db.transaction() as conn:
        job_id = _job(conn, _user(conn), **extra)
        conn.execute(PAGE_SQL, (job_id, "pages/p0.jpg"))
    storage.put("pages/p0.jpg", _jpeg(), "image/jpeg")
    for voice in VOICES:
        (tmp_path / f"{voice}.mp3").write_bytes(b"ID3")
    return job_id, storage


def test_cli_cancelled_job_discards_uploads(app: Flask, cli_env: None, tmp_path: Path) -> None:
    job_id, storage = _cli_job(tmp_path, status="cancelled")
    assert jobs_cli.main(["complete", str(job_id), "--audio-dir", str(tmp_path)], storage=storage) == 1
    assert set(storage.objects) == {"pages/p0.jpg"}


def test_cli_discards_uploads_on_exception(
    app: Flask, cli_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id, storage = _cli_job(tmp_path)

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(completion, "complete_job", boom)
    with pytest.raises(RuntimeError):
        jobs_cli.main(["complete", str(job_id), "--audio-dir", str(tmp_path)], storage=storage)
    assert set(storage.objects) == {"pages/p0.jpg"}


def test_cli_report_failed_voice_needs_no_mp3_and_validation(app: Flask, cli_env: None, tmp_path: Path) -> None:
    job_id, storage = _cli_job(tmp_path)
    (tmp_path / "tenor.mp3").unlink()
    report = tmp_path / "r.json"
    report.write_text('{"failedVoices": ["Tenor"], "review": {}}', "utf-8")
    base = ["complete", str(job_id), "--audio-dir", str(tmp_path)]
    assert jobs_cli.main([*base, "--failed", "kazoo:x"], storage=storage) == 2
    assert jobs_cli.main([*base, "--report", str(report)], storage=storage) == 0
    with db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audio_tracks").fetchone()["n"] == 3
        assert conn.execute("SELECT review FROM scores").fetchone()["review"] == {}


def test_cli_fail_missing_job_exits_1(app: Flask, cli_env: None) -> None:
    assert jobs_cli.main(["fail", "999", "x"], storage=MemoryStorage()) == 1
