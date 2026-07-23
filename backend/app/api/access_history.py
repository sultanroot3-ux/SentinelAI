"""Access-history listing (detections, entries/exits, visitor check-ins)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.core.security import require_roles
from app.db.database import get_db
from app.models.models import AccessHistory, User
from app.schemas.schemas import AccessHistoryOut, PaginatedAccessHistory

router = APIRouter(prefix="/api/access-history", tags=["access-history"])

_VIEWER_ROLES = ("admin", "security_officer", "receptionist")


def _serialize(row: AccessHistory) -> AccessHistoryOut:
    return AccessHistoryOut(
        id=row.id,
        user_id=row.user_id,
        user_name=row.user.name if row.user else None,
        visitor_id=row.visitor_id,
        visitor_name=row.visitor.name if row.visitor else None,
        unknown_face_id=row.unknown_face_id,
        camera_id=row.camera_id,
        camera_name=row.camera_ref.name if row.camera_ref else None,
        event=row.event,
        detail=row.detail,
        timestamp=row.timestamp,
    )


@router.get("", response_model=PaginatedAccessHistory)
def list_access_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user_id: int | None = None,
    visitor_id: int | None = None,
    unknown_face_id: int | None = None,
    event: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_VIEWER_ROLES)),
):
    q = db.query(AccessHistory).options(
        joinedload(AccessHistory.user),
        joinedload(AccessHistory.visitor),
        joinedload(AccessHistory.camera_ref),
    )
    if user_id is not None:
        q = q.filter(AccessHistory.user_id == user_id)
    if visitor_id is not None:
        q = q.filter(AccessHistory.visitor_id == visitor_id)
    if unknown_face_id is not None:
        q = q.filter(AccessHistory.unknown_face_id == unknown_face_id)
    if event:
        q = q.filter(AccessHistory.event == event)
    total = q.count()
    rows = (
        q.order_by(AccessHistory.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedAccessHistory(
        items=[_serialize(r) for r in rows], total=total, page=page
    )
