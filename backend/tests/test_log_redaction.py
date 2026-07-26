"""Credentials must never reach the log stream.

Two classes of leak are covered:

- Values the code logs on purpose (a Redis connection URL, a rejected webhook
  URL) — these must be redacted at the call site.
- Values a *third-party library* smuggles into text the code logs by accident.
  ``requests`` embeds the full request URL in the exception it raises, and both
  the Telegram bot token and the Discord webhook secret live in that URL, so a
  bare ``logger.exception()`` would publish them. These tests fail if anyone
  reverts to logging the raw exception.
"""
import logging

import pytest
import requests

from app.core.redaction import MASK, redact_endpoint, redact_url, scrub


# ---------------------------------------------------------------------------
# redact_url — connection strings (secret is in the userinfo)
# ---------------------------------------------------------------------------
def test_redact_url_masks_password_keeps_host():
    out = redact_url("redis://sentinel:hunter2@cache.internal:6379/0")
    assert "hunter2" not in out
    assert MASK in out
    # The useful diagnostic parts survive.
    assert "cache.internal" in out and "6379" in out and out.startswith("redis://")


def test_redact_url_handles_password_only_userinfo():
    out = redact_url("redis://:hunter2@cache:6379/1")
    assert "hunter2" not in out and "cache" in out


def test_redact_url_passes_through_when_no_credential():
    assert redact_url("redis://cache:6379/0") == "redis://cache:6379/0"


@pytest.mark.parametrize("value", [None, ""])
def test_redact_url_handles_unset(value):
    assert redact_url(value) == "<unset>"


def test_redact_url_refuses_to_echo_unparseable_values():
    """A malformed config value must not be echoed verbatim just in case."""
    assert redact_url("not a url at all") == "<unparseable-url>"


# ---------------------------------------------------------------------------
# redact_endpoint — webhooks (secret is in the path)
# ---------------------------------------------------------------------------
def test_redact_endpoint_drops_the_secret_path():
    secret = "123456:AAH-super-secret-bot-token"
    out = redact_endpoint(f"https://api.telegram.org/bot{secret}/sendMessage")
    assert secret not in out and "sendMessage" not in out
    assert out == f"https://api.telegram.org/{MASK}"


def test_redact_endpoint_drops_discord_webhook_secret():
    out = redact_endpoint(
        "https://discord.com/api/webhooks/98765432109876543/Xy-THIS-IS-THE-SECRET"
    )
    assert "THIS-IS-THE-SECRET" not in out and "98765432109876543" not in out
    assert out == f"https://discord.com/{MASK}"


# ---------------------------------------------------------------------------
# scrub — arbitrary text from third-party exceptions
# ---------------------------------------------------------------------------
def test_scrub_removes_secret_from_exception_text():
    token = "123456:AAH-super-secret-bot-token"
    exc = requests.HTTPError(
        f"401 Client Error: Unauthorized for url: "
        f"https://api.telegram.org/bot{token}/sendMessage"
    )
    out = scrub(exc, token)
    assert token not in out
    assert "401 Client Error" in out, "the diagnostic part must survive"


def test_scrub_ignores_short_values_to_avoid_mangling_text():
    """A 2-character 'secret' would blank out unrelated substrings."""
    assert scrub("chat 42 failed at 42%", "42") == "chat 42 failed at 42%"


def test_scrub_tolerates_none_secrets():
    assert scrub("nothing to hide", None) == "nothing to hide"


# ---------------------------------------------------------------------------
# Call sites: the notification channels
# ---------------------------------------------------------------------------
BOT_TOKEN = "7654321:AAF-quite-secret-telegram-token"
WEBHOOK = "https://discord.com/api/webhooks/12345678901234567/SECRET-WEBHOOK-VALUE"


def _raise_http_error_with_url(url_containing_secret):
    def _post(url, *args, **kwargs):
        raise requests.HTTPError(
            f"401 Client Error: Unauthorized for url: {url_containing_secret}"
        )

    return _post


def test_telegram_failure_does_not_log_the_bot_token(monkeypatch, caplog):
    from app.services import notification_service as ns

    monkeypatch.setattr(
        ns.requests,
        "post",
        _raise_http_error_with_url(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        ),
    )
    with caplog.at_level(logging.DEBUG):
        ns._send_telegram(
            {"telegram_bot_token": BOT_TOKEN, "telegram_chat_id": "999"},
            "title",
            "message",
            "alert",
        )

    assert caplog.records, "the failure must still be reported"
    assert BOT_TOKEN not in caplog.text, "bot token leaked into the log"


def test_discord_failure_does_not_log_the_webhook(monkeypatch, caplog):
    from app.services import notification_service as ns

    monkeypatch.setattr(ns, "is_valid_discord_webhook", lambda url: True)
    monkeypatch.setattr(ns.requests, "post", _raise_http_error_with_url(WEBHOOK))
    with caplog.at_level(logging.DEBUG):
        ns._send_discord({"discord_webhook_url": WEBHOOK}, "title", "message", "alert")

    assert caplog.records
    assert "SECRET-WEBHOOK-VALUE" not in caplog.text


def test_rejected_discord_webhook_is_not_logged_verbatim(caplog):
    """A non-Discord URL is still someone's credential — log the host only."""
    from app.services import notification_service as ns

    hostile = "https://evil.example.com/hook/SECRET-WEBHOOK-VALUE"
    with caplog.at_level(logging.DEBUG):
        ns._send_discord({"discord_webhook_url": hostile}, "t", "m", "alert")

    assert "SECRET-WEBHOOK-VALUE" not in caplog.text
    assert "evil.example.com" in caplog.text, "the destination is worth logging"


def test_email_failure_does_not_log_the_smtp_password(monkeypatch, caplog):
    from app.services import notification_service as ns

    password = "super-secret-smtp-password"

    class _Boom:
        def __enter__(self):
            raise RuntimeError(f"auth failed for password {password}")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ns.smtplib, "SMTP", lambda *a, **k: _Boom())
    with caplog.at_level(logging.DEBUG):
        ns._send_email(
            {
                "smtp_host": "smtp.example.com",
                "smtp_to": "ops@example.com",
                "smtp_password": password,
                "smtp_user": "ops",
            },
            "title",
            "message",
            "alert",
        )

    assert caplog.records
    assert password not in caplog.text


# ---------------------------------------------------------------------------
# Shared-state backend selection
# ---------------------------------------------------------------------------
def test_shared_state_startup_log_redacts_the_redis_url(monkeypatch, caplog):
    """Constructing SharedState with a credentialed URL must not log the password.

    Port 1 refuses the connection immediately, so this also exercises the
    "Redis configured but unreachable" branch — neither path may echo the
    password.
    """
    from app.core import shared_state as ss

    monkeypatch.setattr(
        ss.settings, "REDIS_URL", "redis://sentinel:hunter2@127.0.0.1:1/0"
    )
    with caplog.at_level(logging.DEBUG, logger="sentinelai.shared_state"):
        state = ss.SharedState()

    assert caplog.records, "backend selection must be logged"
    assert "hunter2" not in caplog.text
    # Degraded to memory because the connection failed, which is the documented
    # behaviour — and the reason the failure branch must also be redacted.
    assert state.is_shared is False


# ---------------------------------------------------------------------------
# Startup must state which shared-state backend is live (B4 observability)
# ---------------------------------------------------------------------------
def test_startup_reports_the_shared_state_backend(caplog):
    """SharedState is built at import time, before logging has handlers.

    Its own "backend selected" message is therefore emitted into the void, so
    the lifespan restates it. Without this an operator cannot tell from the
    logs whether rate limits are actually shared across workers.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with caplog.at_level(logging.INFO, logger="sentinelai"):
        with TestClient(app):
            pass

    assert any(
        "Shared state backend:" in r.getMessage() for r in caplog.records
    ), "startup did not report which shared-state backend is in use"


def test_startup_escalates_when_multi_worker_without_shared_state(monkeypatch, caplog):
    """Per-worker limits with >1 worker is an error-level condition, not info."""
    from fastapi.testclient import TestClient

    from app.core import shared_state as ss
    from app.main import app
    from app.core.config import settings as app_settings

    monkeypatch.setattr(type(app_settings), "worker_count", property(lambda self: 4))
    monkeypatch.setattr(ss.shared_state, "_redis", None, raising=False)

    with caplog.at_level(logging.INFO, logger="sentinelai"):
        with TestClient(app):
            pass

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("PER-WORKER" in r.getMessage() for r in errors), (
        "a multi-worker deployment without shared state must log an error"
    )
