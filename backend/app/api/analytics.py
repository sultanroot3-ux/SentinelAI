"""Analytics endpoints (SQL aggregations)."""
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.models import Case, RecognitionLog, UnknownFace, User
from app.schemas.schemas import (
    AnalyticsSummary,
    CameraPoint,
    DailyPoint,
    PeakHourPoint,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _today_start() -> datetime:
    # Timestamps are stored in UTC — use the UTC date, not the local one
    return datetime.combine(datetime.utcnow().date(), time.min)


@router.get("/summary", response_model=AnalyticsSummary)
def summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    today = _today_start()

    total_users = db.query(func.count(User.id)).scalar() or 0
    today_visitors = (
        db.query(func.count(RecognitionLog.id))
        .filter(RecognitionLog.timestamp >= today)
        .scalar()
        or 0
    )
    today_unknown = (
        db.query(func.count(UnknownFace.id))
        .filter(UnknownFace.timestamp >= today)
        .scalar()
        or 0
    )
    open_cases = (
        db.query(func.count(Case.id))
        .filter(Case.status.in_(["open", "investigating"]))
        .scalar()
        or 0
    )

    # Accuracy proxy: recognized detections / all detections (recognized + unknown)
    total_recognized = db.query(func.count(RecognitionLog.id)).scalar() or 0
    total_unknown = db.query(func.count(UnknownFace.id)).scalar() or 0
    denominator = total_recognized + total_unknown
    recognition_accuracy = (
        round(total_recognized / denominator * 100, 2) if denominator else 0.0
    )

    return AnalyticsSummary(
        total_users=total_users,
        today_visitors=today_visitors,
        today_unknown=today_unknown,
        open_cases=open_cases,
        recognition_accuracy=recognition_accuracy,
    )


@router.get("/daily", response_model=list[DailyPoint])
def daily(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    start = _today_start() - timedelta(days=days - 1)

    def _date_key(k) -> str:
        # func.date() returns date objects on PostgreSQL but strings on SQLite
        return k.isoformat() if hasattr(k, "isoformat") else str(k)

    recognized_rows = {
        _date_key(k): v
        for k, v in db.query(
            func.date(RecognitionLog.timestamp),
            func.count(RecognitionLog.id),
        )
        .filter(RecognitionLog.timestamp >= start)
        .group_by(func.date(RecognitionLog.timestamp))
        .all()
    }
    unknown_rows = {
        _date_key(k): v
        for k, v in db.query(
            func.date(UnknownFace.timestamp),
            func.count(UnknownFace.id),
        )
        .filter(UnknownFace.timestamp >= start)
        .group_by(func.date(UnknownFace.timestamp))
        .all()
    }

    points: list[DailyPoint] = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        key = day.isoformat()
        points.append(
            DailyPoint(
                date=key,
                recognized=int(recognized_rows.get(key, 0)),
                unknown=int(unknown_rows.get(key, 0)),
            )
        )
    return points


@router.get("/peak-hours", response_model=list[PeakHourPoint])
def peak_hours(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # extract('hour', ...) is portable: SQLAlchemy compiles it to strftime on
    # SQLite and EXTRACT on PostgreSQL (strftime does not exist there).
    hour_expr = extract("hour", RecognitionLog.timestamp)
    rows = {
        int(k): v
        for k, v in db.query(hour_expr, func.count(RecognitionLog.id))
        .group_by(hour_expr)
        .all()
    }
    return [PeakHourPoint(hour=h, count=int(rows.get(h, 0))) for h in range(24)]


@router.get("/cameras", response_model=list[CameraPoint])
def cameras(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (
        db.query(RecognitionLog.camera, func.count(RecognitionLog.id))
        .group_by(RecognitionLog.camera)
        .order_by(func.count(RecognitionLog.id).desc())
        .all()
    )
    return [CameraPoint(camera=camera, count=int(count)) for camera, count in rows]
