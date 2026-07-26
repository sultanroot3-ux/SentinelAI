"""Tests for the follow-up review findings fixed alongside the blockers.

Covers: the match_rate metric rename, bounded collection endpoints, Discord
webhook SSRF hardening, the API's own CSP header, and the guarantee that the
bootstrap password is never written to a log.
"""
import logging

import pytest

from app.services.notification_service import is_valid_discord_webhook


# ---------------------------------------------------------------------------
# Misleading metric renamed: recognition_accuracy -> match_rate
# ---------------------------------------------------------------------------
def test_summary_exposes_match_rate_not_accuracy(client, admin_headers):
    resp = client.get("/api/analytics/summary", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "match_rate" in body
    assert "recognition_accuracy" not in body, (
        "the old name implied a correctness measure the number does not provide"
    )
    assert isinstance(body["match_rate"], (int, float))
    assert 0.0 <= body["match_rate"] <= 100.0


def test_summary_keeps_its_other_fields(client, admin_headers):
    body = client.get("/api/analytics/summary", headers=admin_headers).json()
    for field in ("total_users", "today_visitors", "today_unknown", "open_cases"):
        assert field in body


# ---------------------------------------------------------------------------
# Bounded collection endpoints
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/api/users", "/api/visitors", "/api/cameras"])
def test_collection_reports_total_count(client, admin_headers, path):
    resp = client.get(path, headers=admin_headers)
    assert resp.status_code == 200
    assert "X-Total-Count" in resp.headers
    assert int(resp.headers["X-Total-Count"]) >= 0


@pytest.mark.parametrize("path", ["/api/users", "/api/visitors", "/api/cameras"])
def test_collection_respects_limit(client, admin_headers, path):
    resp = client.get(path, headers=admin_headers, params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()) <= 1


def test_collection_rejects_oversized_limit(client, admin_headers):
    """The cap must be enforced server-side, not merely defaulted."""
    resp = client.get("/api/users", headers=admin_headers, params={"limit": 100000})
    assert resp.status_code == 422


def test_collection_rejects_negative_offset(client, admin_headers):
    assert client.get(
        "/api/users", headers=admin_headers, params={"offset": -1}
    ).status_code == 422


@pytest.fixture()
def _several_users(client, admin_headers):
    """Guarantee at least three users exist, independent of test ordering."""
    for i in range(3):
        client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "name": f"Page Probe {i}",
                "email": f"page-probe-{i}@example.com",
                "username": f"page_probe_{i}",
                "password": "page-probe-pass-1",
                "role": "receptionist",
            },
        )
    total = int(
        client.get("/api/users", headers=admin_headers).headers["X-Total-Count"]
    )
    assert total >= 3, f"expected at least 3 users, found {total}"
    return total


def test_offset_pages_through_results(client, admin_headers, _several_users):
    first = client.get(
        "/api/users", headers=admin_headers, params={"limit": 1, "offset": 0}
    ).json()
    second = client.get(
        "/api/users", headers=admin_headers, params={"limit": 1, "offset": 1}
    ).json()
    assert len(first) == 1 and len(second) == 1
    assert first[0]["id"] != second[0]["id"]


def test_truncation_is_advertised(client, admin_headers, _several_users):
    """A client must be able to tell it did not receive the whole collection."""
    resp = client.get("/api/users", headers=admin_headers, params={"limit": 1})
    assert resp.headers.get("X-Result-Truncated") == "true"


def test_full_page_is_not_marked_truncated(client, admin_headers, _several_users):
    total = _several_users
    resp = client.get("/api/users", headers=admin_headers, params={"limit": total})
    assert "X-Result-Truncated" not in resp.headers


# ---------------------------------------------------------------------------
# Discord webhook SSRF hardening
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com/api/webhooks/123/abc",
        "https://discordapp.com/api/webhooks/123/abc",
        "https://ptb.discord.com/api/webhooks/1/2",
    ],
)
def test_valid_discord_webhooks_accepted(url):
    assert is_valid_discord_webhook(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://discord.com/api/webhooks/1/2",            # plaintext
        "https://169.254.169.254/latest/meta-data/",       # cloud metadata
        "https://localhost/api/webhooks/1/2",              # loopback
        "https://10.0.0.5/api/webhooks/1/2",               # private range
        "https://evil.com/api/webhooks/1/2",               # arbitrary host
        "https://discord.com.evil.com/api/webhooks/1/2",   # suffix confusion
        "https://user:pass@discord.com/api/webhooks/1/2",  # embedded creds
        "https://discord.com:8080/api/webhooks/1/2",       # port smuggling
        "https://discord.com/not-a-webhook",               # wrong path
        "not-a-url",
        "",
    ],
)
def test_ssrf_targets_rejected(url):
    assert is_valid_discord_webhook(url) is False


def test_settings_rejects_non_discord_webhook(client, admin_headers):
    resp = client.put(
        "/api/settings",
        headers=admin_headers,
        json={"discord_webhook_url": "https://169.254.169.254/latest/meta-data/"},
    )
    assert resp.status_code == 422
    assert "discord" in resp.json()["detail"].lower()


def test_settings_accepts_valid_discord_webhook(client, admin_headers):
    resp = client.put(
        "/api/settings",
        headers=admin_headers,
        json={"discord_webhook_url": "https://discord.com/api/webhooks/1/tok"},
    )
    assert resp.status_code == 200


def test_send_discord_refuses_bad_url_without_network(monkeypatch):
    """A stored bad URL must be refused at send time too, never fetched."""
    from app.services import notification_service

    called = []
    monkeypatch.setattr(
        notification_service.requests, "post",
        lambda *a, **k: called.append(a) or (_ for _ in ()).throw(
            AssertionError("network call attempted for a rejected URL")
        ),
    )
    notification_service._send_discord(
        {"discord_webhook_url": "https://169.254.169.254/"}, "t", "m", "alert"
    )
    assert called == []


# ---------------------------------------------------------------------------
# API-level CSP (nginx is not the only path to the backend)
# ---------------------------------------------------------------------------
def test_api_sets_its_own_csp(client):
    resp = client.get("/api/health")
    csp = resp.headers.get("Content-Security-Policy")
    assert csp is not None, "the API must not rely on nginx for its CSP"
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_existing_security_headers_still_present(client):
    resp = client.get("/api/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"


# ---------------------------------------------------------------------------
# Bootstrap credential must never reach the logs
# ---------------------------------------------------------------------------
def test_seed_does_not_log_the_bootstrap_password(caplog):
    """Re-running the seed must not emit the password into any log record."""
    from app.main import _seed_database_once

    with caplog.at_level(logging.DEBUG, logger="sentinelai"):
        _seed_database_once()

    combined = " ".join(r.getMessage() for r in caplog.records)
    assert "admin123" not in combined, "bootstrap password leaked into the log"


def test_seed_source_contains_no_plaintext_password_in_log_call():
    """Guard the specific regression: a literal password inside a log call."""
    import inspect

    from app import main

    source = inspect.getsource(main)
    for line in source.splitlines():
        if "logger." in line:
            assert "admin123" not in line, f"password in log statement: {line.strip()}"


# ---------------------------------------------------------------------------
# Report exports are bounded
# ---------------------------------------------------------------------------
def _make_recognition_log(db):
    """One recognition inside the daily report window."""
    from datetime import datetime

    from app.models.models import RecognitionLog

    row = RecognitionLog(
        user_id=None, camera="test-cam", score=0.9, timestamp=datetime.utcnow()
    )
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("fmt", ["csv", "json", "pdf", "xlsx"])
def test_report_refuses_oversized_export(client, admin_headers, db_session, monkeypatch, fmt):
    """Every format must hit the row cap, not just the ones that build in memory.

    Silently truncating an export is worse than refusing it: the operator gets
    a file that looks complete and is not.
    """
    from app.api import reports

    row = _make_recognition_log(db_session)
    try:
        monkeypatch.setattr(reports, "MAX_REPORT_ROWS", 0)
        resp = client.get(
            "/api/reports/visitors",
            headers=admin_headers,
            params={"period": "daily", "format": fmt},
        )
        assert resp.status_code == 413, resp.text
        assert "export limit" in resp.json()["detail"]
    finally:
        db_session.delete(row)
        db_session.commit()


def test_report_succeeds_below_the_cap(client, admin_headers, db_session):
    row = _make_recognition_log(db_session)
    try:
        resp = client.get(
            "/api/reports/visitors",
            headers=admin_headers,
            params={"period": "daily", "format": "json"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] >= 1
    finally:
        db_session.delete(row)
        db_session.commit()
