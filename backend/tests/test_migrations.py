"""Migration runner and initial schema tests.

Each test runs in a throwaway PostgreSQL schema (search_path pinned on the connection), so the
shared public schema that the rest of the suite relies on is never dropped.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from backend import migrate

TEST_DATABASE_URL_DEFAULT = "postgresql://piya:piya@localhost:55432/piya_test"
SCRATCH_SCHEMA = "mig_test"
ALL_VERSIONS = [v for v, _ in migrate._discover(migrate.MIGRATIONS_DIR)]
ERD_TABLES = {
    "users",
    "sessions",
    "password_reset_tokens",
    "jobs",
    "job_pages",
    "scores",
    "audio_tracks",
    "timing_metadata",
    "throttle_hits",
    "throttle_backoff",
    "storage_deletions",
    "blobs",
    "purge_log",
    "cancelled_submissions",
    "piano_settings",
    "schema_migrations",
}


def _url() -> str:
    return os.environ.get("TEST_DATABASE_URL", TEST_DATABASE_URL_DEFAULT)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[tuple[Any, ...]]]:
    """Autocommit connection whose search_path is an empty scratch schema."""
    with psycopg.connect(_url(), autocommit=True) as admin:
        admin.execute(f"DROP SCHEMA IF EXISTS {SCRATCH_SCHEMA} CASCADE")
        admin.execute(f"CREATE SCHEMA {SCRATCH_SCHEMA}")
    with psycopg.connect(_url(), autocommit=True, options=f"-c search_path={SCRATCH_SCHEMA}") as c:
        yield c
    with psycopg.connect(_url(), autocommit=True) as admin:
        admin.execute(f"DROP SCHEMA IF EXISTS {SCRATCH_SCHEMA} CASCADE")


@pytest.fixture
def migrated(conn: psycopg.Connection[tuple[Any, ...]]) -> psycopg.Connection[tuple[Any, ...]]:
    migrate.up(conn)
    return conn


def _tables(conn: psycopg.Connection[tuple[Any, ...]]) -> set[str]:
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s", (SCRATCH_SCHEMA,)
    ).fetchall()
    return {row[0] for row in rows}


def _user(conn: psycopg.Connection[tuple[Any, ...]], email: str = "a@example.com") -> int:
    row = conn.execute(
        "INSERT INTO users (email, password_hash) VALUES (%s, 'h') RETURNING id", (email,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _job(conn: psycopg.Connection[tuple[Any, ...]], user_id: int, **overrides: Any) -> int:
    values: dict[str, Any] = {
        "user_id": user_id,
        "status": "queued",
        "source": "images",
        "page_count": 1,
        "title": "Ave Maria",
        "tempo_source": "user",
    }
    values.update(overrides)
    cols = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    row = conn.execute(
        f"INSERT INTO jobs ({cols}) VALUES ({marks}) RETURNING id", tuple(values.values())
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_up_fresh_db_creates_all_tables(conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    assert migrate.up(conn) == ALL_VERSIONS
    assert _tables(conn) == ERD_TABLES


def test_up_is_idempotent(conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    migrate.up(conn)
    assert migrate.up(conn) == []


def test_status_reports_pending_and_applied(conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    assert migrate.status(conn) == [(v, False) for v in ALL_VERSIONS]
    migrate.up(conn)
    assert migrate.status(conn) == [(v, True) for v in ALL_VERSIONS]


def test_down_then_up_roundtrip(conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    migrate.up(conn)
    assert migrate.down(conn, to="0000") == ALL_VERSIONS[::-1]
    assert _tables(conn) <= {"schema_migrations"}
    assert migrate.status(conn) == [(v, False) for v in ALL_VERSIONS]
    assert migrate.up(conn) == ALL_VERSIONS
    assert _tables(conn) == ERD_TABLES


def test_failed_migration_rolls_back(
    conn: psycopg.Connection[tuple[Any, ...]], tmp_path: Path
) -> None:
    (tmp_path / "0002_bad.up.sql").write_text("CREATE TABLE t_ok(id int); SELECT 1/0;")
    (tmp_path / "0002_bad.down.sql").write_text("DROP TABLE IF EXISTS t_ok;")
    with pytest.raises(psycopg.errors.DivisionByZero):
        migrate.up(conn, migrations_dir=tmp_path)
    assert "t_ok" not in _tables(conn)
    assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone() == (0,)


def test_fk_cascade_user_delete(migrated: psycopg.Connection[tuple[Any, ...]]) -> None:
    uid = _user(migrated)
    score = migrated.execute(
        "INSERT INTO scores (user_id, title, page_count, tempo_source, review) "
        "VALUES (%s, 'T', 1, 'user', '{}') RETURNING id",
        (uid,),
    ).fetchone()
    assert score is not None
    job = _job(migrated, uid, score_id=score[0])
    migrated.execute(
        "INSERT INTO job_pages (job_id, page_index, object_key, width, height) "
        "VALUES (%s, 0, 'k', 10, 10)",
        (job,),
    )
    migrated.execute(
        "INSERT INTO audio_tracks (score_id, voice, file_key) VALUES (%s, 'alto', 'k')", (score[0],)
    )
    migrated.execute(
        "INSERT INTO timing_metadata (score_id, metadata_key) VALUES (%s, 'k')", (score[0],)
    )
    migrated.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, '\\x01', now())", (uid,)
    )
    migrated.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
        "VALUES (%s, '\\x01', now())",
        (uid,),
    )
    migrated.execute("DELETE FROM users")
    for table in (
        "scores", "jobs", "job_pages", "audio_tracks", "timing_metadata", "sessions",
        "password_reset_tokens",
    ):
        assert migrated.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table


@pytest.mark.parametrize(
    "overrides",
    [{"tempo_bpm": 29}, {"key_signature": "H"}, {"title": ""}, {"page_count": 21}],
)
def test_check_constraints(
    migrated: psycopg.Connection[tuple[Any, ...]], overrides: dict[str, Any]
) -> None:
    uid = _user(migrated)
    with pytest.raises(psycopg.errors.CheckViolation):
        _job(migrated, uid, **overrides)


def test_one_unfinished_retake_per_job(migrated: psycopg.Connection[tuple[Any, ...]]) -> None:
    uid = _user(migrated)
    original = _job(migrated, uid, status="complete")
    first = _job(migrated, uid, replaces_job_id=original)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _job(migrated, uid, replaces_job_id=original)
    migrated.execute("UPDATE jobs SET status = 'failed' WHERE id = %s", (first,))
    _job(migrated, uid, replaces_job_id=original)


def test_one_live_reset_code_per_user(migrated: psycopg.Connection[tuple[Any, ...]]) -> None:
    uid = _user(migrated)
    insert = "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, now())"
    migrated.execute(insert, (uid, b"a"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        migrated.execute(insert, (uid, b"b"))
    migrated.execute("UPDATE password_reset_tokens SET used_at = now()")
    migrated.execute(insert, (uid, b"b"))


def test_updated_at_trigger(migrated: psycopg.Connection[tuple[Any, ...]]) -> None:
    uid = _user(migrated)
    migrated.execute("UPDATE users SET role = 'choir_director' WHERE id = %s", (uid,))
    row = migrated.execute(
        "SELECT updated_at > created_at FROM users WHERE id = %s", (uid,)
    ).fetchone()
    assert row == (True,)


def test_0005_soft_delete_column_and_indexes(conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    def state() -> tuple[bool, set[str]]:
        col = conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'scores' AND column_name = 'deleted_at'", (SCRATCH_SCHEMA,)
        ).fetchone()
        idx = {r[0] for r in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename = 'scores'",
            (SCRATCH_SCHEMA,)).fetchall()}
        return col is not None, idx & {"scores_user_live_idx", "scores_deleted_at_idx"}

    migrate.up(conn)
    assert state() == (True, {"scores_user_live_idx", "scores_deleted_at_idx"})
    assert migrate.down(conn, to="0004") == ALL_VERSIONS[:3:-1]
    assert state() == (False, set())


def test_0006_midi_combined_key_column(conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    def has_col() -> bool:
        return conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'scores' AND column_name = 'midi_combined_key'", (SCRATCH_SCHEMA,)
        ).fetchone() is not None

    migrate.up(conn)
    assert has_col()
    assert migrate.down(conn, to="0005") == ALL_VERSIONS[:4:-1]
    assert not has_col()


def test_0008_job_started_at_column(conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    def nullable() -> str | None:
        row = conn.execute(
            "SELECT is_nullable FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'jobs' AND column_name = 'started_at'", (SCRATCH_SCHEMA,)
        ).fetchone()
        return None if row is None else str(row[0])

    migrate.up(conn)
    assert nullable() == "YES"
    migrate.down(conn, to="0007")
    assert nullable() is None
