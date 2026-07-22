"""In-app notification creation, plus stub hooks for external channels."""
from sqlalchemy.orm import Session

from app.models.models import Notification


def create_notification(
    db: Session,
    title: str,
    message: str,
    level: str = "info",
) -> Notification:
    """Create an in-app notification and fan out to external channels (stubs)."""
    notification = Notification(title=title, message=message, level=level)
    db.add(notification)
    db.commit()
    db.refresh(notification)

    # External channels — fire-and-forget stubs for now.
    _send_email_stub(title, message, level)
    _send_discord_stub(title, message, level)
    _send_telegram_stub(title, message, level)

    return notification


def _send_email_stub(title: str, message: str, level: str) -> None:
    # TODO(Module: notifications): send email via SMTP (smtplib) using settings
    # like smtp_host / smtp_user / smtp_password once configured in Settings.
    pass


def _send_discord_stub(title: str, message: str, level: str) -> None:
    # TODO(Module: notifications): POST to a Discord webhook URL stored in Settings.
    pass


def _send_telegram_stub(title: str, message: str, level: str) -> None:
    # TODO(Module: notifications): call the Telegram Bot API (sendMessage) with a
    # bot token + chat id stored in Settings.
    pass
