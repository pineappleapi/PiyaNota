"""Tests for logout, account info, change password and delete account (PIYA-305/306/307/322)."""

from __future__ import annotations

from typing import Any

import pytest
from flask.testing import FlaskClient

from backend import db

PASSWORD = "Secret123zz"
NEW_PASSWORD = "Brandnew456yy"
EMAIL = "a@example.com"
WRONG = "Wrong123zzzz"
RATE_LIMIT = 5


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _signup(client: FlaskClient) -> str:
    res = client.post(
        "/api/auth/signup",
        json={"email": EMAIL, "password": PASSWORD, "passwordConfirmation": PASSWORD},
    )
    assert res.status_code == 201
    token: str = res.get_json()["data"]["sessionToken"]
    return token


def _login(client: FlaskClient, password: str = PASSWORD) -> Any:
    return client.post("/api/auth/login", json={"email": EMAIL, "password": password})


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _change(client: FlaskClient, token: str, **body: str) -> Any:
    return client.post("/api/auth/change-password", json=body, headers=_auth(token))


def test_logout_revokes(client: FlaskClient) -> None:
    token = _signup(client)
    res = client.post("/api/auth/logout", headers=_auth(token))
    assert res.status_code == 200
    assert client.get("/api/account", headers=_auth(token)).status_code == 401
    assert client.post("/api/auth/logout", headers=_auth(token)).status_code == 401


def test_account_info_trimmed(client: FlaskClient) -> None:
    token = _signup(client)
    res = client.get("/api/account", headers=_auth(token))
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert set(data) == {"email", "role", "accountCreatedAt"}
    assert data["email"] == EMAIL
    assert data["accountCreatedAt"].endswith("Z")


def test_change_password_flow(client: FlaskClient) -> None:
    token = _signup(client)
    other = _login(client).get_json()["data"]["sessionToken"]
    res = _change(client, token, currentPassword=WRONG, newPassword=NEW_PASSWORD)
    assert res.status_code == 403
    assert res.get_json()["error"]["code"] == "invalid_current_password"
    res = _change(client, token, currentPassword=PASSWORD, newPassword="short")
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "weak_password"
    assert res.get_json()["error"]["field"] == "newPassword"
    res = _change(client, token, currentPassword=PASSWORD)
    assert res.status_code == 400
    assert res.get_json()["error"]["field"] == "newPassword"
    res = _change(client, token, currentPassword=PASSWORD, newPassword=NEW_PASSWORD)
    assert res.status_code == 200
    assert client.get("/api/account", headers=_auth(token)).status_code == 200
    assert client.get("/api/account", headers=_auth(other)).status_code == 401
    assert _login(client, NEW_PASSWORD).status_code == 200
    assert _login(client, PASSWORD).status_code == 401


def test_change_password_rate_limit(client: FlaskClient) -> None:
    token = _signup(client)
    for _ in range(RATE_LIMIT):
        res = _change(client, token, currentPassword=WRONG, newPassword=NEW_PASSWORD)
        assert res.status_code == 403
    res = _change(client, token, currentPassword=PASSWORD, newPassword=NEW_PASSWORD)
    assert res.status_code == 429
    assert res.get_json()["error"]["code"] == "rate_limited"
    assert int(res.headers["Retry-After"]) > 0


def test_change_password_ignores_role(client: FlaskClient) -> None:
    token = _signup(client)
    res = _change(
        client, token, currentPassword=PASSWORD, newPassword=NEW_PASSWORD, role="choir_director"
    )
    assert res.status_code == 200
    assert client.get("/api/account", headers=_auth(token)).get_json()["data"]["role"] != (
        "choir_director"
    )


def test_delete_account_requires_password(client: FlaskClient) -> None:
    token = _signup(client)
    res = client.delete("/api/account", json={"password": WRONG}, headers=_auth(token))
    assert res.status_code == 403
    assert res.get_json()["error"]["code"] == "invalid_current_password"
    res = client.delete("/api/account", json={}, headers=_auth(token))
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "missing_field"


def test_delete_account_purges_and_revokes(client: FlaskClient) -> None:
    token = _signup(client)
    res = client.delete("/api/account", json={"password": PASSWORD}, headers=_auth(token))
    assert res.status_code == 200
    assert res.get_json()["data"] is None
    with db.transaction() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = %s", (EMAIL,)).fetchone()
    assert row is None  # purged inline (B3)
    assert client.get("/api/account", headers=_auth(token)).status_code == 401
    res = _login(client)
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "invalid_credentials"
    res = client.post(
        "/api/auth/signup",
        json={"email": EMAIL, "password": PASSWORD, "passwordConfirmation": PASSWORD},
    )
    assert res.status_code == 201


def test_delete_account_rate_limit(client: FlaskClient) -> None:
    token = _signup(client)
    for _ in range(RATE_LIMIT):
        res = client.delete("/api/account", json={"password": WRONG}, headers=_auth(token))
        assert res.status_code == 403
    res = client.delete("/api/account", json={"password": PASSWORD}, headers=_auth(token))
    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) > 0
    assert client.get("/api/account", headers=_auth(token)).status_code == 200
