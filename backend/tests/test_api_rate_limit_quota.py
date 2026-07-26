"""API tests: per-user quotas on the expensive AI endpoints (B3).

The quota is enforced before the upload is decoded and before any inference
runs, so these tests are fast and do not need the AI engine installed.
"""
import io

import pytest

from app.core import rate_limit
from app.core.shared_state import shared_state


@pytest.fixture(autouse=True)
def _clean_quota_state():
    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


def _tiny_upload():
    return {"file": ("frame.jpg", io.BytesIO(b"not-a-real-jpeg"), "image/jpeg")}


# ---- recognition ----------------------------------------------------------
def test_recognition_quota_eventually_returns_429(client, admin_headers):
    capacity = int(rate_limit.QUOTAS["recognition"][0])
    statuses = [
        client.post(
            "/api/recognition/frame", headers=admin_headers, files=_tiny_upload()
        ).status_code
        for _ in range(capacity + 5)
    ]
    assert 429 in statuses, "recognition endpoint accepted unlimited requests"
    # Everything before the first 429 must be a normal (non-quota) response.
    first_429 = statuses.index(429)
    assert first_429 >= 1
    assert all(s != 429 for s in statuses[:first_429])


def test_recognition_429_carries_retry_after(client, admin_headers):
    capacity = int(rate_limit.QUOTAS["recognition"][0])
    resp = None
    for _ in range(capacity + 5):
        resp = client.post(
            "/api/recognition/frame", headers=admin_headers, files=_tiny_upload()
        )
        if resp.status_code == 429:
            break
    assert resp is not None and resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) >= 1
    assert "rate limit" in resp.json()["detail"].lower()


def test_quota_is_per_user_not_global(client, admin_headers, officer_headers):
    """One user exhausting their bucket must not block another user."""
    capacity = int(rate_limit.QUOTAS["recognition"][0])
    for _ in range(capacity + 5):
        client.post("/api/recognition/frame", headers=admin_headers, files=_tiny_upload())
    admin_resp = client.post(
        "/api/recognition/frame", headers=admin_headers, files=_tiny_upload()
    )
    officer_resp = client.post(
        "/api/recognition/frame", headers=officer_headers, files=_tiny_upload()
    )
    assert admin_resp.status_code == 429
    assert officer_resp.status_code != 429


# ---- investigation --------------------------------------------------------
def test_investigation_has_a_tighter_quota_than_recognition():
    inv_cap, inv_rate = rate_limit.QUOTAS["investigation"]
    rec_cap, rec_rate = rate_limit.QUOTAS["recognition"]
    assert inv_cap < rec_cap and inv_rate < rec_rate


def test_investigation_quota_returns_429(client, admin_headers):
    capacity = int(rate_limit.QUOTAS["investigation"][0])
    statuses = [
        client.post(
            "/api/investigation/analyze", headers=admin_headers, files=_tiny_upload()
        ).status_code
        for _ in range(capacity + 4)
    ]
    assert 429 in statuses


def test_investigation_quota_exceeded_is_audited(client, admin_headers):
    capacity = int(rate_limit.QUOTAS["investigation"][0])
    for _ in range(capacity + 4):
        client.post(
            "/api/investigation/analyze", headers=admin_headers, files=_tiny_upload()
        )
    audit = client.get(
        "/api/audit", headers=admin_headers, params={"action": "quota_exceeded"}
    )
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1


# ---- stream tokens --------------------------------------------------------
def test_stream_token_quota_returns_429(client, admin_headers):
    capacity = int(rate_limit.QUOTAS["stream_token"][0])
    statuses = [
        client.post("/api/camera/stream-token", headers=admin_headers).status_code
        for _ in range(capacity + 5)
    ]
    assert 200 in statuses
    assert 429 in statuses


# ---- unauthenticated callers never reach the quota ------------------------
def test_quota_requires_authentication_first(client):
    """An anonymous caller gets 401, not a quota decision."""
    resp = client.post("/api/recognition/frame", files=_tiny_upload())
    assert resp.status_code == 401


# ---- unit-level behaviour -------------------------------------------------
def test_check_quota_allows_unknown_name_but_warns():
    allowed, retry = rate_limit.check_quota("no-such-endpoint", user_id=1)
    assert allowed is True and retry == 0


def test_check_quota_uses_shared_state():
    """Quota state must live in shared_state so it is correct across workers."""
    rate_limit.reset_all()
    capacity = int(rate_limit.QUOTAS["recognition"][0])
    for _ in range(capacity):
        assert rate_limit.check_quota("recognition", 4242)[0] is True
    assert rate_limit.check_quota("recognition", 4242)[0] is False
    # Clearing shared state must clear the quota — proving that is where it lives.
    shared_state.reset_all()
    assert rate_limit.check_quota("recognition", 4242)[0] is True
