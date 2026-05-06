"""
Tests for Phase 3: Authentication & Users.

Coverage:
  - auth_service unit tests (hashing, JWT, API key generation)
  - /auth/register — first user becomes admin, subsequent require auth
  - /auth/login — valid creds, bad creds, inactive account
  - /auth/refresh — happy path, wrong token type
  - /auth/me — JWT bearer, X-API-Key header, no auth
  - /auth/me/password — change password
  - /auth/users — admin list, non-admin forbidden
  - /auth/users/{id}/role — change role, invalid role
  - /auth/users/{id} DELETE — deactivate, self-deactivate guard
  - /auth/api-keys — create, list, revoke, revoked key rejected
  - RBAC enforcement — rep cannot reach manager-only routes
"""
import pytest
from jose import jwt

from app.config import settings
from app.services.auth_service import (
    create_token,
    decode_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# auth_service unit tests
# ---------------------------------------------------------------------------

def test_password_roundtrip():
    hashed = hash_password("secret123")
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)


def test_password_hashes_differ():
    assert hash_password("abc") != hash_password("abc")


def test_create_and_decode_access_token():
    token = create_token("user-1", "rep", "access")
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["role"] == "rep"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    token = create_token("user-1", "admin", "refresh")
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_decode_invalid_token_raises():
    from jose import JWTError
    with pytest.raises(JWTError):
        decode_token("not.a.token")


def test_generate_api_key_format():
    raw, prefix, key_hash = generate_api_key()
    assert raw.startswith("sdr_")
    assert len(raw) == 68          # "sdr_" + 64 hex chars
    assert raw.startswith(prefix)
    assert len(prefix) == 12
    assert key_hash == hash_api_key(raw)


def test_hash_api_key_deterministic():
    raw, _, _ = generate_api_key()
    assert hash_api_key(raw) == hash_api_key(raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register(client, email="admin@test.com", password="password123", role="rep"):
    return client.post("/auth/register", json={"email": email, "password": password, "role": role})


def _login(client, email, password="password123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def _auth_headers(client, email="admin@test.com", password="password123"):
    r = _login(client, email, password)
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def test_first_user_becomes_admin(client):
    r = _register(client, role="rep")
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "admin"


def test_register_duplicate_email(client):
    _register(client, email="admin@test.com")
    headers = _auth_headers(client, "admin@test.com")
    r = client.post(
        "/auth/register",
        json={"email": "admin@test.com", "password": "password123", "role": "rep"},
        headers=headers,
    )
    assert r.status_code == 409


def test_register_weak_password(client):
    r = _register(client, password="short")
    assert r.status_code == 422


def test_second_registration_requires_admin_auth(client):
    _register(client, email="admin@test.com")
    r = _register(client, email="other@test.com")
    assert r.status_code == 401


def test_admin_can_register_second_user(client):
    _register(client, email="admin@test.com")
    headers = _auth_headers(client, "admin@test.com")
    r = client.post(
        "/auth/register",
        json={"email": "rep@test.com", "password": "password123", "role": "rep"},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "rep"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_success(client):
    _register(client)
    r = _login(client, "admin@test.com")
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client):
    _register(client)
    r = _login(client, "admin@test.com", "wrongpass")
    assert r.status_code == 401


def test_login_unknown_email(client):
    r = _login(client, "nobody@test.com")
    assert r.status_code == 401


def test_login_inactive_account(client, test_session_factory):
    _register(client, email="admin@test.com")
    headers = _auth_headers(client, "admin@test.com")
    # Create a second user and deactivate them
    client.post(
        "/auth/register",
        json={"email": "rep@test.com", "password": "password123", "role": "rep"},
        headers=headers,
    )
    rep_headers = _auth_headers(client, "rep@test.com")
    # Get the rep's user ID
    me = client.get("/auth/me", headers=rep_headers).json()
    client.delete(f"/auth/users/{me['id']}", headers=headers)
    r = _login(client, "rep@test.com")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def test_refresh_token(client):
    _register(client)
    login_data = _login(client, "admin@test.com").json()
    r = client.post("/auth/refresh", json={"refresh_token": login_data["refresh_token"]})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_refresh_with_access_token_fails(client):
    _register(client)
    login_data = _login(client, "admin@test.com").json()
    r = client.post("/auth/refresh", json={"refresh_token": login_data["access_token"]})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------

def test_get_me_with_bearer(client):
    _register(client)
    headers = _auth_headers(client)
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "admin@test.com"


def test_get_me_no_auth(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_get_me_with_api_key(client):
    _register(client)
    bearer = _auth_headers(client)
    key_r = client.post("/auth/api-keys", json={"name": "test-key"}, headers=bearer)
    raw_key = key_r.json()["key"]
    r = client.get("/auth/me", headers={"X-API-Key": raw_key})
    assert r.status_code == 200
    assert r.json()["email"] == "admin@test.com"


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

def test_change_password(client):
    _register(client)
    headers = _auth_headers(client)
    r = client.put(
        "/auth/me/password",
        json={"current_password": "password123", "new_password": "newpassword456"},
        headers=headers,
    )
    assert r.status_code == 204
    # Old password no longer works
    assert _login(client, "admin@test.com", "password123").status_code == 401
    # New password works
    assert _login(client, "admin@test.com", "newpassword456").status_code == 200


def test_change_password_wrong_current(client):
    _register(client)
    headers = _auth_headers(client)
    r = client.put(
        "/auth/me/password",
        json={"current_password": "wrong", "new_password": "newpassword456"},
        headers=headers,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# User management (admin)
# ---------------------------------------------------------------------------

def _setup_two_users(client):
    """Returns (admin_headers, rep_id, rep_headers)."""
    _register(client, email="admin@test.com")
    admin_h = _auth_headers(client, "admin@test.com")
    client.post(
        "/auth/register",
        json={"email": "rep@test.com", "password": "password123", "role": "rep"},
        headers=admin_h,
    )
    rep_h = _auth_headers(client, "rep@test.com")
    rep_id = client.get("/auth/me", headers=rep_h).json()["id"]
    return admin_h, rep_id, rep_h


def test_list_users_admin(client):
    _setup_two_users(client)
    admin_h = _auth_headers(client, "admin@test.com")
    r = client.get("/auth/users", headers=admin_h)
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_list_users_rep_forbidden(client):
    _, _, rep_h = _setup_two_users(client)
    r = client.get("/auth/users", headers=rep_h)
    assert r.status_code == 403


def test_change_user_role(client):
    admin_h, rep_id, _ = _setup_two_users(client)
    r = client.put(f"/auth/users/{rep_id}/role", params={"role": "manager"}, headers=admin_h)
    assert r.status_code == 200
    assert r.json()["role"] == "manager"


def test_change_user_role_invalid(client):
    admin_h, rep_id, _ = _setup_two_users(client)
    r = client.put(f"/auth/users/{rep_id}/role", params={"role": "superuser"}, headers=admin_h)
    assert r.status_code == 400


def test_deactivate_user(client):
    admin_h, rep_id, _ = _setup_two_users(client)
    r = client.delete(f"/auth/users/{rep_id}", headers=admin_h)
    assert r.status_code == 204


def test_cannot_deactivate_self(client):
    _register(client, email="admin@test.com")
    admin_h = _auth_headers(client, "admin@test.com")
    admin_id = client.get("/auth/me", headers=admin_h).json()["id"]
    r = client.delete(f"/auth/users/{admin_id}", headers=admin_h)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------

def test_create_api_key(client):
    _register(client)
    headers = _auth_headers(client)
    r = client.post("/auth/api-keys", json={"name": "my-key"}, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "my-key"
    assert body["key"].startswith("sdr_")
    assert "key_prefix" in body


def test_list_api_keys(client):
    _register(client)
    headers = _auth_headers(client)
    client.post("/auth/api-keys", json={"name": "key-1"}, headers=headers)
    client.post("/auth/api-keys", json={"name": "key-2"}, headers=headers)
    r = client.get("/auth/api-keys", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_revoke_api_key(client):
    _register(client)
    headers = _auth_headers(client)
    key_r = client.post("/auth/api-keys", json={"name": "key-1"}, headers=headers)
    key_id = key_r.json()["id"]
    raw_key = key_r.json()["key"]

    r = client.delete(f"/auth/api-keys/{key_id}", headers=headers)
    assert r.status_code == 204

    # Revoked key should now be rejected
    r2 = client.get("/auth/me", headers={"X-API-Key": raw_key})
    assert r2.status_code == 401


def test_raw_key_not_in_list_response(client):
    _register(client)
    headers = _auth_headers(client)
    client.post("/auth/api-keys", json={"name": "key-1"}, headers=headers)
    keys = client.get("/auth/api-keys", headers=headers).json()
    for k in keys:
        assert "key" not in k or k.get("key") is None


# ---------------------------------------------------------------------------
# RBAC enforcement on lead routes
# ---------------------------------------------------------------------------

def test_rep_cannot_access_stats(client):
    _register(client, email="admin@test.com")
    admin_h = _auth_headers(client, "admin@test.com")
    client.post(
        "/auth/register",
        json={"email": "rep@test.com", "password": "password123", "role": "rep"},
        headers=admin_h,
    )
    rep_h = _auth_headers(client, "rep@test.com")
    r = client.get("/leads/stats", headers=rep_h)
    assert r.status_code == 403


def test_unauthenticated_leads_rejected(client):
    r = client.get("/leads")
    assert r.status_code == 401


def test_rep_can_list_leads(client):
    _register(client, email="admin@test.com")
    admin_h = _auth_headers(client, "admin@test.com")
    client.post(
        "/auth/register",
        json={"email": "rep@test.com", "password": "password123", "role": "rep"},
        headers=admin_h,
    )
    rep_h = _auth_headers(client, "rep@test.com")
    r = client.get("/leads", headers=rep_h)
    assert r.status_code == 200
