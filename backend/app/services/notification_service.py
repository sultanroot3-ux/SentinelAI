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
from email.mime.text import MIMEText

import requests
from sqlalchemy.orm import Session

from app.models.models import Notification
from app.services.settings_service import get_all_settings

logger = logging.getLogger("sentinelai.notify")

# Overridable for tests (point at a local sink instead of the real API)
TELEGRAM_API_BASE = os.environ.get(
    "SENTINEL_TELEGRAM_API_BASE", "https://api.telegram.org"
)

_LEVEL_EMOJI = {"info": "ℹ️", "warning": "⚠️", "alert": "🚨"}


def create_notification(
    db: Session,
    title: str,
    message: str,
    level: str = "info",
) -> Notification:
    """Create an in-app notification and fan out to enabled external channels."""
    notification = Notification(title=title, message=message, level=level)
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
    except Exception:
        logger.exception("Email notification failed")


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
    except Exception:
        logger.exception("Telegram notification failed")


def _send_discord(cfg: dict, title: str, message: str, level: str) -> None:
    url = cfg.get("discord_webhook_url")
    if not url:
        logger.warning("Discord enabled but webhook URL not configured.")
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
    except Exception:
        logger.exception("Discord notification failed")
