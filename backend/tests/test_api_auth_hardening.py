"""Integration tests: rate limiting, refresh rotation, logout, change-password."""
import pytest

from app.core import rate_limit
from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clean_rate_limit():
    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


def _login(client, username, password):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
def test_login_locked_after_five_failures(client):
    for _ in range(5):
        assert _login(client, "admin", "wrong").status_code == 401
    resp = _login(client, "admin", "wrong")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    # Even the CORRECT password is rejected while locked
    assert _login(client, "admin", "admin123").status_code == 429


def test_rate_limit_is_per_username(client):
    for _ in range(5):
        _login(client, "someone-else", "wrong")
    # a different username from the same IP is unaffected
    assert _login(client, "admin", "admin123").status_code == 200


def test_success_clears_failure_counter(client):
    for _ in range(4):
        _login(client, "admin", "wrong")
    assert _login(client, "admin", "admin123").status_code == 200
    # counter was reset — 4 more failures still allowed before lockout
    for _ in range(4):
        assert _login(client, "admin", "wrong").status_code == 401


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------
def test_login_returns_refresh_token(client):
    body = _login(client, "admin", "admin123").json()
    assert body["refresh_token"]
    assert body["access_token"] != body["refresh_token"]


def test_refresh_rotates_single_use(client):
    refresh1 = _login(client, "admin", "admin123").json()["refresh_token"]

    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh1})
    assert resp.status_code == 200
    pair2 = resp.json()
    assert pair2["access_token"] and pair2["refresh_token"] != refresh1

    # The consumed token must be dead
    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh1})
    assert resp.status_code == 401

    # The rotated token still works
    resp = client.post(
        "/api/auth/refresh", json={"refresh_token": pair2["refresh_token"]}
    )
    assert resp.status_code == 200


def test_access_token_cannot_be_used_to_refresh(client):
    access = _login(client, "admin", "admin123").json()["access_token"]
    resp = client.post("/api/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


def test_refresh_token_cannot_be_used_for_access(client):
    refresh = _login(client, "admin", "admin123").json()["refresh_token"]
    resp = client.get("/api/users", headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401


def test_logout_revokes_refresh_token(client):
    body = _login(client, "admin", "admin123").json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    resp = client.post(
        "/api/auth/logout", headers=headers,
        json={"refresh_token": body["refresh_token"]},
    )
    assert resp.status_code == 200
    resp = client.post(
        "/api/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Password change / first-login reset
# ---------------------------------------------------------------------------
def test_seeded_admin_must_change_password(client):
    body = _login(client, "admin", "admin123").json()
    assert body["user"]["must_change_password"] is True


def test_change_password_flow(client, admin_headers):
    # create a throwaway user to avoid breaking the shared admin fixture
    client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "name": "Pw User",
            "email": "pw@example.com",
            "username": "pwuser",
            "password": "original-pass-1",
            "role": "receptionist",
        },
    )
    body = _login(client, "pwuser", "original-pass-1").json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    # wrong current password
    resp = client.post(
        "/api/auth/change-password", headers=headers,
        json={"current_password": "nope", "new_password": "brand-new-pass-1"},
    )
    assert resp.status_code == 401

    # too-short new password
    resp = client.post(
        "/api/auth/change-password", headers=headers,
        json={"current_password": "original-pass-1", "new_password": "short"},
    )
    assert resp.status_code == 422

    # success
    resp = client.post(
        "/api/auth/change-password", headers=headers,
        json={"current_password": "original-pass-1", "new_password": "brand-new-pass-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is False

    # old password dead, new one works, old refresh token revoked
    assert _login(client, "pwuser", "original-pass-1").status_code == 401
    assert _login(client, "pwuser", "brand-new-pass-1").status_code == 200
    resp = client.post(
        "/api/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert resp.status_code == 401


def test_short_password_rejected_on_user_create(client, admin_headers):
    resp = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "name": "Weak",
            "email": "weak@example.com",
            "username": "weakpw",
            "password": "abc",
            "role": "receptionist",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Production config validation
# ---------------------------------------------------------------------------
def test_production_refuses_dev_secret():
    from app.core.config import _DEV_SECRET_KEY

    s = Settings(
        ENV="production", SECRET_KEY=_DEV_SECRET_KEY, DATABASE_URL="postgresql://x/y"
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        s.validate_for_environment()


def test_production_refuses_missing_database_url():
    s = Settings(ENV="production", SECRET_KEY="x" * 40, DATABASE_URL="")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        s.validate_for_environment()


def test_production_accepts_safe_config():
    s = Settings(
        ENV="production", SECRET_KEY="x" * 40, DATABASE_URL="postgresql://x/y"
    )
    s.validate_for_environment()  # no raise


def test_development_allows_defaults():
    Settings(ENV="development").validate_for_environment()  # no raise
