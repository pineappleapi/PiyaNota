"""Tests for PIYA-321 piano settings (GET/PUT /api/users/me/piano-settings)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from flask.testing import FlaskClient

from backend import db
from backend.app import create_app
from backend.config import Settings
from backend.tests.test_account import _auth, _signup

URL = "/api/users/me/piano-settings"


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _iso(delta: timedelta = timedelta()) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _put(client: FlaskClient, token: str, **body: Any) -> Any:
    return client.put(URL, json=body, headers=_auth(token))


def test_requires_auth(client: FlaskClient) -> None:
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={"octave": 4}).status_code == 401
    assert client.get(URL, headers=_auth("bogus")).status_code == 401


@pytest.mark.parametrize(
    ("query", "octave"),
    [("?voice=tenor", 3), ("?voice=Bass", 3), ("?voice=soprano", 4), ("?voice=alto", 4),
     ("?voice=notSure", 4), ("?voice=conductor", 4), ("?voice=zzz", 4), ("", 4)],
)
def test_get_default_from_voice(client: FlaskClient, query: str, octave: int) -> None:
    token = _signup(client)
    res = client.get(URL + query, headers=_auth(token))
    assert res.status_code == 200
    assert res.get_json()["data"] == {"octave": octave, "updatedAt": None, "isDefault": True}


def test_default_follows_voice_until_saved(client: FlaskClient) -> None:
    token = _signup(client)
    assert client.get(URL + "?voice=tenor", headers=_auth(token)).get_json()["data"]["octave"] == 3
    assert client.get(URL + "?voice=soprano", headers=_auth(token)).get_json()["data"]["octave"] == 4
    _put(client, token, octave=5)
    data = client.get(URL + "?voice=tenor", headers=_auth(token)).get_json()["data"]
    assert data["octave"] == 5 and data["isDefault"] is False


def test_put_saves_and_shapes_match(client: FlaskClient) -> None:
    token = _signup(client)
    res = _put(client, token, octave=2)
    body = res.get_json()
    assert res.status_code == 200 and body["success"] is True and body["status"] == 200
    assert set(body["data"]) == {"octave", "updatedAt", "isDefault"}
    assert body["data"]["octave"] == 2 and body["data"]["isDefault"] is False
    assert client.get(URL, headers=_auth(token)).get_json()["data"] == body["data"]


@pytest.mark.parametrize(
    ("body", "code"),
    [({}, "octave_missing"), ({"octave": "4"}, "octave_invalid"), ({"octave": 4.5}, "octave_invalid"),
     ({"octave": 4.0}, "octave_invalid"), ({"octave": None}, "octave_invalid"),
     ({"octave": True}, "octave_invalid"), ({"octave": 1}, "octave_out_of_range"),
     ({"octave": 7}, "octave_out_of_range"),
     ({"octave": 4, "clientUpdatedAt": "yesterday"}, "client_updated_at_invalid"),
     ({"octave": 4, "clientUpdatedAt": 5}, "client_updated_at_invalid"),
     ({"octave": 4, "clientUpdatedAt": "2026-11-10T09:15:00"}, "client_updated_at_invalid")],
)
def test_put_validation(client: FlaskClient, body: dict[str, Any], code: str) -> None:
    token = _signup(client)
    res = _put(client, token, **body)
    assert res.status_code == 400
    assert res.get_json()["message"] == code
    assert res.get_json()["error"]["code"] == code


def test_future_client_time_rejected_small_skew_ok(client: FlaskClient) -> None:
    token = _signup(client)
    assert _put(client, token, octave=4, clientUpdatedAt=_iso(timedelta(minutes=10))).status_code == 400
    assert _put(client, token, octave=4, clientUpdatedAt=_iso(timedelta(minutes=2))).status_code == 200


def test_future_client_time_clamped_to_server_now(client: FlaskClient) -> None:
    token = _signup(client)
    before = datetime.now(timezone.utc).replace(microsecond=0)
    res = _put(client, token, octave=5, clientUpdatedAt=_iso(timedelta(minutes=4)))
    stored = datetime.fromisoformat(res.get_json()["data"]["updatedAt"].replace("Z", "+00:00"))
    assert before <= stored <= datetime.now(timezone.utc)
    # Not pinned in the future: a later write (also clamped to now) still wins.
    res = _put(client, token, octave=3, clientUpdatedAt=_iso(timedelta(seconds=2)))
    assert res.get_json()["data"]["octave"] == 3


def test_stale_write_keeps_newer(client: FlaskClient) -> None:
    token = _signup(client)
    newer = _iso(timedelta(minutes=-1))
    assert _put(client, token, octave=5, clientUpdatedAt=newer).status_code == 200
    res = _put(client, token, octave=3, clientUpdatedAt=_iso(timedelta(minutes=-30)))
    assert res.status_code == 200
    assert res.get_json()["data"] == {"octave": 5, "updatedAt": newer, "isDefault": False}
    res = _put(client, token, octave=6, clientUpdatedAt=newer)  # equal timestamp overwrites
    assert res.get_json()["data"]["octave"] == 6 and res.get_json()["data"]["updatedAt"] == newer


def test_put_idempotent_and_server_time_default(client: FlaskClient) -> None:
    token = _signup(client)
    for _ in range(3):
        res = _put(client, token, octave=4)
        assert res.status_code == 200 and res.get_json()["data"]["octave"] == 4
    assert res.get_json()["data"]["updatedAt"] is not None


def test_users_isolated(client: FlaskClient) -> None:
    a = _signup(client)
    res = client.post("/api/auth/signup", json={
        "email": "b@example.com", "password": "Secret123zz", "passwordConfirmation": "Secret123zz"})
    b = res.get_json()["data"]["sessionToken"]
    _put(client, a, octave=6)
    assert client.get(URL, headers=_auth(b)).get_json()["data"]["isDefault"] is True
    with db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM piano_settings").fetchone()["n"] == 1


def test_rate_limited(settings: Settings) -> None:
    app = create_app(replace(settings, piano_settings_per_minute=2))
    app.config["TESTING"] = True
    client = app.test_client()
    token = _signup(client)
    assert client.get(URL, headers=_auth(token)).status_code == 200
    assert client.get(URL, headers=_auth(token)).status_code == 200
    res = client.get(URL, headers=_auth(token))
    assert res.status_code == 429 and res.get_json()["error"]["code"] == "rate_limited"
    db.close_pool()
