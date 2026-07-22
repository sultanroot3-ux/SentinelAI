"""Settings endpoints: key/value map get + partial update."""
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.db.database import get_db
from app.models.models import User
from app.services.audit_service import write_audit
from app.services.settings_service import get_all_settings, set_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

KNOWN_KEYS = {
    "recognition_threshold",
    "liveness_enabled",
    "camera_source",
    "notify_on_unknown",
}


def _validate(values: dict[str, Any]) -> None:
    if "recognition_threshold" in values:
        v = values["recognition_threshold"]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0.0 <= float(v) <= 1.0):
            raise HTTPException(
                status_code=422,
                detail="recognition_threshold must be a number between 0 and 1",
            )
        values["recognition_threshold"] = float(v)
    for key in ("liveness_enabled", "notify_on_unknown"):
        if key in values and not isinstance(values[key], bool):
            raise HTTPException(status_code=422, detail=f"{key} must be a boolean")
    if "camera_source" in values:
        values["camera_source"] = str(values["camera_source"])


@router.get("")
def get_settings_map(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    return get_all_settings(db)


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
    _validate(values)
    result = set_settings(db, values)
    write_audit(
        db,
        "settings_update",
        f"Updated settings: {', '.join(sorted(values.keys())) or 'none'}",
        user=admin,
    )
    return result
