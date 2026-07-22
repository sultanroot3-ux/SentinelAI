"""Typed access to the key/value Settings table."""
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import Setting

DEFAULT_SETTINGS: dict[str, Any] = {
    "recognition_threshold": 0.45,
    "liveness_enabled": False,
    "camera_source": "0",
    "notify_on_unknown": True,
    # Email (SMTP)
    "email_enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_to": "",
    "smtp_tls": True,
    # Telegram
    "telegram_enabled": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    # Discord
    "discord_enabled": False,
    "discord_webhook_url": "",
}

# Values masked in API responses; a masked value sent back in an update is
# ignored so the stored secret is not clobbered by the UI round-trip.
SECRET_KEYS = {"smtp_password", "telegram_bot_token", "discord_webhook_url"}
SECRET_MASK = "********"


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    try:
        return json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return row.value


def get_all_settings(db: Session) -> dict[str, Any]:
    result = dict(DEFAULT_SETTINGS)
    for row in db.query(Setting).all():
        try:
            result[row.key] = json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            result[row.key] = row.value
    return result


def set_settings(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        if value is None:
            continue
        row = db.get(Setting, key)
        encoded = json.dumps(value)
        if row is None:
            db.add(Setting(key=key, value=encoded))
        else:
            row.value = encoded
    db.commit()
    return get_all_settings(db)


def seed_default_settings(db: Session) -> None:
    """Insert defaults for any missing keys (idempotent)."""
    for key, value in DEFAULT_SETTINGS.items():
        if db.get(Setting, key) is None:
            db.add(Setting(key=key, value=json.dumps(value)))
    db.commit()
