"""Unknown visitor endpoints."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.utils import serialize_unknown
from app.core.config import settings
from app.core.security import get_current_user, require_roles
from app.db.database import get_db
from app.services.audit_service import write_audit
from app.models.models import UnknownFace, User
from app.schemas.schemas import PaginatedUnknown, UnknownFaceOut, UnknownFaceUpdate

router = APIRouter(prefix="/api/unknown", tags=["unknown"])

PAGE_SIZE = 20


@router.get("", response_model=PaginatedUnknown)
def list_unknown(
    status: str | None = Query(None, pattern="^(new|reviewed|case_opened)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(UnknownFace)
    if status:
        query = query.filter(UnknownFace.status == status)
    total = query.count()
    items = (
        query.order_by(UnknownFace.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedUnknown(
        items=[serialize_unknown(u) for u in items],
        total=total,
        page=page,
    )


@router.put("/{unknown_id}", response_model=UnknownFaceOut)
def update_unknown(
    unknown_id: int,
    payload: UnknownFaceUpdate,
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles("admin", "security_officer")),
):
    unknown = db.get(UnknownFace, unknown_id)
    if unknown is None:
        raise HTTPException(status_code=404, detail="Unknown face not found")
    unknown.status = payload.status
    db.commit()
    db.refresh(unknown)
    write_audit(
        db, "unknown_update",
        f"Unknown {unknown.unknown_person_id or unknown_id} status -> {payload.status}",
        user=officer,
    )
    return serialize_unknown(unknown)


@router.delete("/{unknown_id}")
def delete_unknown(
    unknown_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles("admin", "security_officer")),
):
    unknown = db.get(UnknownFace, unknown_id)
    if unknown is None:
        raise HTTPException(status_code=404, detail="Unknown face not found")

    # Best-effort removal of the snapshot file
    if unknown.snapshot_url:
        filename = Path(unknown.snapshot_url).name
        snapshot_path = settings.UNKNOWN_FACES_DIR / filename
        try:
            snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass

    label = unknown.unknown_person_id or f"id={unknown_id}"
    db.delete(unknown)
    db.commit()
    # Deleting biometric evidence must be accountable (compliance).
    write_audit(db, "unknown_delete",
                f"Deleted unknown-face record {label} (snapshot + embedding removed)",
                user=officer)
    return {"detail": "Unknown face deleted"}
