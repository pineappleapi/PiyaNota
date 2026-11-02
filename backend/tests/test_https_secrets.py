"""HTTPS enforcement (PIYA-317) and the tracked-secrets check (PIYA-318)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from backend.app import create_app
from backend.config import Settings
from backend.tests.test_jobs_submit import _err, make_app  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def test_http_rejected_when_https_required(make_app: Callable[..., FlaskClient]) -> None:
    client = make_app(require_https=True)
    _err(client.get("/api/account", headers={"X-Forwarded-Proto": "http"}), 400, "https_required")
    # Rejected before auth: a bad token on http is still https_required, not 401.
    assert client.get("/healthz", headers={"X-Forwarded-Proto": "http"}).status_code == 200
    _err(client.get("/api/account", headers={"X-Forwarded-Proto": "https"}), 401, "unauthorized")


def test_http_allowed_when_not_required(make_app: Callable[..., FlaskClient]) -> None:
    assert make_app(require_https=False).get("/healthz").status_code == 200


def test_prod_requires_https_flag(settings: Settings) -> None:
    with pytest.raises(RuntimeError, match="HTTPS"):
        create_app(replace(settings, env="prod", require_https=False))


def test_check_secrets_clean_repo() -> None:
    res = subprocess.run(
        [sys.executable, "backend/scripts/check_secrets.py"], cwd=ROOT, capture_output=True, text=True
    )
    assert res.returncode == 0, res.stdout + res.stderr
