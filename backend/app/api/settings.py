"""Settings endpoints: key/value map get + partial update."""
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.db.database import get_db
from app.models.models import User
from app.services.audit_service import write_audit
from app.services.settings_service import (
    DEFAULT_SETTINGS,
    SECRET_KEYS,
    SECRET_MASK,
    get_all_settings,
    set_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

KNOWN_KEYS = set(DEFAULT_SETTINGS)

_BOOL_KEYS = (
    "liveness_enabled",
    "notify_on_unknown",
    "email_enabled",
    "smtp_tls",
    "telegram_enabled",
    "discord_enabled",
)
_STR_KEYS = (
    "camera_source",
    "smtp_host",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "smtp_to",
    "telegram_bot_token",
    "telegram_chat_id",
    "discord_webhook_url",
)


def _validate(values: dict[str, Any]) -> None:
    if "recognition_threshold" in values:
        v = values["recognition_threshold"]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0.0 <= float(v) <= 1.0):
            raise HTTPException(
                status_code=422,
                detail="recognition_threshold must be a number between 0 and 1",
            )
        values["recognition_threshold"] = float(v)
    if "unknown_retention_days" in values:
        v = values["unknown_retention_days"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 3650:
            raise HTTPException(
                status_code=422,
                detail="unknown_retention_days must be an integer between 0 and 3650",
            )
    if "smtp_port" in values:
        try:
            values["smtp_port"] = int(values["smtp_port"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="smtp_port must be an integer")
    for key in _BOOL_KEYS:
        if key in values and not isinstance(values[key], bool):
            raise HTTPException(status_code=422, detail=f"{key} must be a boolean")
    for key in _STR_KEYS:
        if key in values:
            values[key] = str(values[key])


def _mask_secrets(settings_map: dict[str, Any]) -> dict[str, Any]:
    """Never return stored secrets to the browser — mask non-empty ones."""
    return {
        k: (SECRET_MASK if k in SECRET_KEYS and v else v)
        for k, v in settings_map.items()
    }


@router.get("")
def get_settings_map(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _mask_secrets(get_all_settings(db))


@router.put("")
def update_settings_map(
    values: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
) -> dict[str, Any]:
    unknown = set(values) - KNOWN_KEYS
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown setting keys: {', '.join(sorted(unknown))}",
        )
    # A masked secret coming back from the UI means "unchanged" — drop it
    # so the stored value is not overwritten with the mask literal.
    values = {
        k: v
        for k, v in values.items()
        if not (k in SECRET_KEYS and v == SECRET_MASK)
    }
    _validate(values)
    result = set_settings(db, values)
    write_audit(
        db,
        "settings_update",
        f"Updated settings: {', '.join(sorted(values.keys())) or 'none'}",
        user=admin,
    )
    return _mask_secrets(result)
