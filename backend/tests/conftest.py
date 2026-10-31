"""Shared fixtures: env=test settings, app/client, DB pool lifecycle and table truncation."""

from __future__ import annotations

import os
from collections.abc import Iterator

from psycopg import sql
import pytest
from flask import Flask
from flask.testing import FlaskClient

from backend import db
from backend.app import create_app
from backend.config import Settings, load_settings

TEST_DATABASE_URL_DEFAULT = "postgresql://piya:piya@localhost:55432/piya_test"


@pytest.fixture
def settings() -> Settings:
    """Test configuration: in-memory storage and mail, cheap Argon2 so tests stay fast."""
    return load_settings(
        {
            "PIYA_ENV": "test",
            "PIYA_DATABASE_URL": os.environ.get("TEST_DATABASE_URL", TEST_DATABASE_URL_DEFAULT),
            "PIYA_STORAGE_BACKEND": "memory",
            "PIYA_MAIL_BACKEND": "memory",
            "PIYA_ARGON2_TIME_COST": "1",
            "PIYA_ARGON2_MEMORY_KIB": "8",
        }
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[Flask]:
    flask_app = create_app(settings)
    flask_app.config["TESTING"] = True
    yield flask_app
    db.close_pool()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def db_clean(app: Flask) -> None:
    """Empty every public table before the test.

    Tables are discovered at run time, so this works before the schema exists and does nothing
    while there are no tables.
    """
    with db.transaction() as conn:
        rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
        names = [row["tablename"] for row in rows]
        if names:
            table_list = sql.SQL(", ").join(sql.Identifier(name) for name in names)
            conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(table_list))
