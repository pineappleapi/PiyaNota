"""Cross-user denial for every user-scoped endpoint (PIYA-315 AC3, PIYA-308 AC2)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from backend import db
from backend.tests.test_jobs_submit import _err, _img, _post, _signup, _user_id
from backend.tests.test_scores import _score

# (method, path template, body); every parameterised url_map rule must appear here.
SCOPED: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/jobs/job_{job}", None),
    ("POST", "/api/jobs/job_{job}/cancel", None),
    ("GET", "/api/scores/{score}/result", None),
    ("PATCH", "/api/scores/{score}", {"title": "Hijacked"}),
    ("DELETE", "/api/scores/{score}", None),
]


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _snapshot() -> list[Any]:
    with db.transaction() as conn:
        return [
            conn.execute("SELECT * FROM scores ORDER BY id").fetchall(),
            conn.execute("SELECT * FROM jobs ORDER BY id").fetchall(),
        ]


@pytest.fixture
def two_users(client: FlaskClient) -> tuple[dict[str, str], dict[str, str], int, int]:
    ha = _signup(client, "a@example.com")
    hb = _signup(client, "b@example.com")
    score, job = _score(_user_id("a@example.com"))
    return ha, hb, score, job


@pytest.mark.parametrize(("method", "template", "body"), SCOPED)
def test_every_scoped_endpoint_denies_other_user(
    client: FlaskClient,
    two_users: tuple[dict[str, str], dict[str, str], int, int],
    method: str,
    template: str,
    body: dict[str, Any] | None,
) -> None:
    ha, hb, score, job = two_users
    url = template.format(job=job, score=score)
    before = _snapshot()
    res = client.open(url, method=method, json=body, headers=hb)
    assert res.status_code == 404, res.get_json()
    assert _snapshot() == before
    # Positive control, after the state check since it may mutate: the owner is not denied, so
    # the 404 above came from ownership and not from a wrong URL.
    assert client.open(url, method=method, json=body, headers=ha).status_code != 404


def test_retake_of_other_users_job_denied(
    client: FlaskClient, two_users: tuple[dict[str, str], dict[str, str], int, int]
) -> None:
    _, hb, _, job = two_users
    before = _snapshot()
    res = _post(client, hb, pages=[_img("JPEG")], title="t", replacesJobId=f"job_{job}")
    _err(res, 404, "job_not_found")
    assert _snapshot() == before


def test_score_list_contains_only_callers(
    client: FlaskClient, two_users: tuple[dict[str, str], dict[str, str], int, int]
) -> None:
    _, hb, score, _ = two_users
    res = client.get("/api/scores", headers=hb)
    assert res.status_code == 200
    assert str(score) not in str(res.get_json()["data"])
    mine, _ = _score(_user_id("b@example.com"), title="Mine")
    assert mine != score
    assert "Mine" in str(client.get("/api/scores", headers=hb).get_json()["data"])
    assert "Bayan Ko" not in str(client.get("/api/scores", headers=hb).get_json()["data"])


def _norm(path: str) -> str:
    return re.sub(r"<[^>]+>|\{\w+\}", "<>", path).replace("job_<>", "<>")


def test_route_inventory_complete(app: Flask) -> None:
    """Fails when someone adds a parameterised route without listing it above."""
    listed = {(m, _norm(t)) for m, t, _ in SCOPED}
    found = {
        (m, _norm(r.rule))
        for r in app.url_map.iter_rules()
        if "<" in r.rule and r.endpoint != "static"
        for m in (r.methods or set()) - {"HEAD", "OPTIONS"}
    }
    assert found <= listed, sorted(found - listed)
