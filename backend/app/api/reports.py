"""Visitor reports: CSV download or JSON."""
import csv
import io
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.api.utils import serialize_log
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.models import RecognitionLog, User

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _period_start(period: str) -> datetime:
    # Timestamps are stored in UTC, so the report window must be UTC too
    # (date.today() is local time and drifts near midnight).
    today = datetime.combine(datetime.utcnow().date(), time.min)
    if period == "daily":
        return today
    if period == "weekly":
        return today - timedelta(days=6)
    # monthly
    return today - timedelta(days=29)


@router.get("/visitors")
def visitors_report(
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    format: str = Query("csv", pattern="^(csv|json)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    start = _period_start(period)
    logs = (
        db.query(RecognitionLog)
        .options(joinedload(RecognitionLog.user))
        .filter(RecognitionLog.timestamp >= start)
        .order_by(RecognitionLog.timestamp.desc())
        .all()
    )

    if format == "json":
        return {
            "period": period,
            "date_from": start.isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "total": len(logs),
            "items": [serialize_log(l).model_dump(mode="json") for l in logs],
        }

    def csv_rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["id", "user_id", "user_name", "camera", "score", "snapshot_url", "timestamp"]
        )
        yield buffer.getvalue()
        for log in logs:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow(
                [
                    log.id,
                    log.user_id if log.user_id is not None else "",
                    log.user.name if log.user else "",
                    log.camera,
                    log.score if log.score is not None else "",
                    log.snapshot_url or "",
                    log.timestamp.isoformat(),
                ]
            )
            yield buffer.getvalue()

    filename = f"visitors_{period}_{date.today().isoformat()}.csv"
    return StreamingResponse(
        csv_rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
