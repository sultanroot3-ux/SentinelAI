"""Notifications: in-app rows + external channels (Email / Telegram / Discord).

Channel configuration lives in the Settings table (editable from the
dashboard Settings page):

  email_enabled, smtp_host, smtp_port, smtp_user, smtp_password,
  smtp_from, smtp_to, smtp_tls
  telegram_enabled, telegram_bot_token, telegram_chat_id
  discord_enabled, discord_webhook_url

External sends run on a daemon thread so the recognition pipeline is never
blocked by a slow SMTP server or webhook. Failures are logged, never raised.
"""
import logging
import os
import smtplib
import threading
from collections.abc import Iterable
from email.mime.text import MIMEText

import requests
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.redaction import redact_endpoint, scrub
from app.models.models import Notification
from app.services.settings_service import get_all_settings

logger = logging.getLogger("sentinelai.notify")

# Overridable for tests (point at a local sink instead of the real API)
TELEGRAM_API_BASE = os.environ.get(
    "SENTINEL_TELEGRAM_API_BASE", "https://api.telegram.org"
)

_LEVEL_EMOJI = {"info": "ℹ️", "warning": "⚠️", "alert": "🚨"}

# Hosts Discord serves webhooks from. The webhook URL is admin-configurable and
# fetched by the server, so it is only safe if it cannot be aimed at an
# arbitrary host — see _send_discord.
_DISCORD_WEBHOOK_HOSTS = frozenset(
    {"discord.com", "www.discord.com", "discordapp.com", "www.discordapp.com",
     "ptb.discord.com", "canary.discord.com"}
)


def is_valid_discord_webhook(url: str) -> bool:
    """True only for an https Discord webhook URL on a known Discord host."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    # Reject embedded credentials/ports that could be used to smuggle a target.
    if parsed.username or parsed.password or parsed.port:
        return False
    if (parsed.hostname or "").lower() not in _DISCORD_WEBHOOK_HOSTS:
        return False
    return parsed.path.startswith("/api/webhooks/")


# Roles that may see security-sensitive alerts. Matches the audit endpoint's
# gate (app/api/audit.py _AUDIT_ROLES) so "who can see a watchlist match" has
# one answer rather than two that can drift.
SECURITY_AUDIENCE: tuple[str, ...] = ("admin", "security_officer")


def encode_audience(roles: "Iterable[str] | None") -> str | None:
    """Encode an audience as the comma-wrapped form the filter expects.

    None (or empty) stays None, meaning "everyone" — the behaviour every
    notification type had before audiences existed.
    """
    if not roles:
        return None
    unique = sorted({r.strip() for r in roles if r and r.strip()})
    if not unique:
        return None
    return "," + ",".join(unique) + ","


def audience_filter(role: str):
    """SQLAlchemy predicate: notifications this role is allowed to see.

    Unrestricted rows (NULL) plus rows whose audience contains this exact role.
    The wrapping commas make the LIKE an exact-token match, so a role name that
    is a prefix of another cannot slip through.
    """
    return or_(
        Notification.audience_roles.is_(None),
        Notification.audience_roles.like(f"%,{role},%"),
    )


def create_notification(
    db: Session,
    title: str,
    message: str,
    level: str = "info",
    audience_roles: "Iterable[str] | None" = None,
) -> Notification:
    """Create an in-app notification and fan out to enabled external channels.

    `audience_roles` restricts who may see the in-app row. It does NOT restrict
    the external fan-out: email/Telegram/Discord destinations are configured
    once by an admin and are not per-user, so scoping them is not meaningful
    here — the operator chooses those recipients when they configure a channel.
    """
    notification = Notification(
        title=title,
        message=message,
        level=level,
        audience_roles=encode_audience(audience_roles),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    # Snapshot channel config NOW (sessions are not thread-safe), then send
    # from a daemon thread so the caller never waits on the network.
    cfg = get_all_settings(db)
    threading.Thread(
        target=_fan_out, args=(cfg, title, message, level), daemon=True
    ).start()

    return notification


def _fan_out(cfg: dict, title: str, message: str, level: str) -> None:
    if cfg.get("email_enabled"):
        _send_email(cfg, title, message, level)
    if cfg.get("telegram_enabled"):
        _send_telegram(cfg, title, message, level)
    if cfg.get("discord_enabled"):
        _send_discord(cfg, title, message, level)


# ---------------------------------------------------------------------------
# Channels — each swallows and logs its own failures
# ---------------------------------------------------------------------------
def _send_email(cfg: dict, title: str, message: str, level: str) -> None:
    host = cfg.get("smtp_host")
    to = cfg.get("smtp_to")
    if not host or not to:
        logger.warning("Email enabled but smtp_host/smtp_to not configured.")
        return
    try:
        port = int(cfg.get("smtp_port") or 587)
        sender = cfg.get("smtp_from") or cfg.get("smtp_user") or "sentinelai@localhost"
        msg = MIMEText(f"{message}\n\n— SentinelAI ({level})", "plain", "utf-8")
        msg["Subject"] = f"[SentinelAI {level.upper()}] {title}"
        msg["From"] = sender
        msg["To"] = to

        with smtplib.SMTP(host, port, timeout=10) as smtp:
            if cfg.get("smtp_tls", True):
                try:
                    smtp.starttls()
                except smtplib.SMTPNotSupportedError:
                    logger.info("SMTP server does not support STARTTLS; sending plain.")
            user, password = cfg.get("smtp_user"), cfg.get("smtp_password")
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(sender, [a.strip() for a in to.split(",")], msg.as_string())
        logger.info("Email notification sent to %s", to)
    except Exception as exc:
        # SMTP errors quote the server's response, which can echo parts of the
        # AUTH exchange. Scrubbing the password is cheap insurance.
        logger.error(
            "Email notification failed (%s): %s",
            host,
            scrub(exc, cfg.get("smtp_password")),
        )


def _send_telegram(cfg: dict, title: str, message: str, level: str) -> None:
    token = cfg.get("telegram_bot_token")
    chat_id = cfg.get("telegram_chat_id")
    if not token or not chat_id:
        logger.warning("Telegram enabled but bot token/chat id not configured.")
        return
    try:
        emoji = _LEVEL_EMOJI.get(level, "")
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"{emoji} {title}\n{message}"},
            timeout=5,
        )
        resp.raise_for_status()
        logger.info("Telegram notification sent (chat %s)", chat_id)
    except Exception as exc:
        # Not logger.exception: requests embeds the full request URL in its
        # error text, and the Telegram bot token lives in that URL's path. The
        # traceback is dropped deliberately in favour of a scrubbed message.
        logger.error(
            "Telegram notification failed (%s): %s",
            redact_endpoint(TELEGRAM_API_BASE),
            scrub(exc, token),
        )


def _send_discord(cfg: dict, title: str, message: str, level: str) -> None:
    url = cfg.get("discord_webhook_url")
    if not url:
        logger.warning("Discord enabled but webhook URL not configured.")
        return
    if not is_valid_discord_webhook(url):
        # An admin-settable, server-fetched URL is a server-side request forgery
        # primitive: pointed at 169.254.169.254 or an internal service it turns
        # the backend into a proxy for the private network. Restricting it to
        # Discord's own hosts removes the primitive entirely.
        # The rejected value is still a credential — it is typically a webhook
        # for *some* service, just not Discord's. Log where it pointed, not the
        # secret path that authenticates against it.
        logger.error(
            "Refusing to send Discord notification: %s is not a Discord webhook URL",
            redact_endpoint(url),
        )
        return
    try:
        color = {"info": 0x0BA5C9, "warning": 0xD97706, "alert": 0xDC2626}.get(level, 0x64748B)
        resp = requests.post(
            url,
            json={
                "embeds": [
                    {
                        "title": f"{_LEVEL_EMOJI.get(level, '')} {title}",
                        "description": message,
                        "color": color,
                        "footer": {"text": f"SentinelAI · {level}"},
                    }
                ]
            },
            timeout=5,
        )
        resp.raise_for_status()
        logger.info("Discord notification sent")
    except Exception as exc:
        # Same hazard as Telegram: the whole webhook URL is the credential and
        # requests echoes it in the error text.
        logger.error(
            "Discord notification failed (%s): %s",
            redact_endpoint(url),
            scrub(exc, url),
        )
