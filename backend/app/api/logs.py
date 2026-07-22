"""Visitor (recognition) log listing with filters + pagination."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.api.utils import serialize_log
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.models import RecognitionLog, User
from app.schemas.schemas import PaginatedLogs

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _parse_date(value: str, field: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise HTTPException(
        status_code=422,
        detail=f"Invalid {field} '{value}'. Expected YYYY-MM-DD or ISO datetime.",
    )


@router.get("", response_model=PaginatedLogs)
def list_logs(
    date_from: str | None = None,
    date_to: str | None = None,
    user_id: int | None = None,
    camera: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(RecognitionLog).options(joinedload(RecognitionLog.user))

    if date_from:
        query = query.filter(RecognitionLog.timestamp >= _parse_date(date_from, "date_from"))
    if date_to:
        dt = _parse_date(date_to, "date_to")
        # A bare date means "through the end of that day"
        if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
            dt = dt + timedelta(days=1)
        query = query.filter(RecognitionLog.timestamp < dt)
    if user_id is not None:
        query = query.filter(RecognitionLog.user_id == user_id)
    if camera:
        query = query.filter(RecognitionLog.camera == camera)

    total = query.count()
    items = (
        query.order_by(RecognitionLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedLogs(items=[serialize_log(l) for l in items], total=total, page=page)
