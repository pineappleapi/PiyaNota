"""Forward/backward SQL migration runner (PIYA-312).

Files live in backend/migrations as NNNN_name.up.sql / NNNN_name.down.sql. Each migration runs in
one transaction together with its schema_migrations row, so a failure leaves nothing half-applied.

CLI: python -m backend.migrate {status|up|down} [--to VERSION]   (reads DATABASE_URL)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import tuple_row

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATE_LOCK_KEY = 0x70697961  # arbitrary app-wide constant ("piya"); any int64 works if unique per app
_UP_NAME = re.compile(r"^(\d{4})_[\w-]+\.up\.sql$")
# Sorts before every real version, so down(to=BASE_VERSION) reverts everything.
BASE_VERSION = "0000"

Conn = psycopg.Connection[Any]


def _discover(migrations_dir: Path) -> list[tuple[str, Path]]:
    found = sorted(
        (m.group(1), path)
        for path in migrations_dir.glob("*.up.sql")
        if (m := _UP_NAME.match(path.name))
    )
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError(f"duplicate migration version in {migrations_dir}")
    return found


def _down_path(up_path: Path) -> Path:
    return up_path.with_name(up_path.name.replace(".up.sql", ".down.sql"))


def _applied(conn: Conn) -> set[str]:
    # Created here (not in 0001) because the runner needs it before any migration has run.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def status(conn: Conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple[str, bool]]:
    """Return (version, applied) for every migration file, oldest first."""
    applied = _applied(conn)
    return [(version, version in applied) for version, _ in _discover(migrations_dir)]


def up(conn: Conn, to: str | None = None, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations up to and including `to` (default: all). Returns versions applied."""
    # Two containers booting together (a rolling deploy) would both run the same DDL; the second
    # waits here, then sees the versions already recorded and applies nothing.
    conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATE_LOCK_KEY,))
    try:
        applied = _applied(conn)
        done: list[str] = []
        for version, path in _discover(migrations_dir):
            if version in applied or (to is not None and version > to):
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            done.append(version)
        return done
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATE_LOCK_KEY,))


def down(conn: Conn, to: str, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Revert applied migrations newer than `to`, newest first. Returns versions reverted."""
    applied = _applied(conn)
    done: list[str] = []
    for version, path in reversed(_discover(migrations_dir)):
        if version not in applied or version <= to:
            continue
        down_path = _down_path(path)
        if not down_path.exists():
            raise FileNotFoundError(f"missing down migration: {down_path}")
        with conn.transaction():
            conn.execute(down_path.read_text(encoding="utf-8"))
            conn.execute("DELETE FROM schema_migrations WHERE version = %s", (version,))
        done.append(version)
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.migrate")
    parser.add_argument("command", choices=["status", "up", "down"])
    parser.add_argument("--to", help="target version (required for down)")
    args = parser.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    if args.command == "down" and args.to is None:
        print("down requires --to VERSION (use 0000 to revert everything)", file=sys.stderr)
        return 2
    with psycopg.connect(url, autocommit=True) as conn:
        if args.command == "status":
            print(f"{'VERSION':<10}APPLIED")
            for version, is_applied in status(conn):
                print(f"{version:<10}{'yes' if is_applied else 'no'}")
        elif args.command == "up":
            print("applied:", ", ".join(up(conn, args.to)) or "nothing")
        else:
            print("reverted:", ", ".join(down(conn, args.to)) or "nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
