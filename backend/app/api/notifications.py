"""Notification endpoints.

Every query here is scoped by the caller's role. A notification may carry an
audience (see Notification.audience_roles); rows outside the caller's audience
must be invisible on all three endpoints, not just the listing — a read-all
that clears alerts you cannot see, or a mark-read that returns 200 for one,
leaks the row's existence just as effectively as showing it.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.models import Notification, User
from app.schemas.schemas import NotificationOut
from app.services.notification_service import audience_filter

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(audience_filter(current_user.role))
    if unread_only:
        query = query.filter(Notification.read.is_(False))
    items = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [NotificationOut.model_validate(n) for n in items]


@router.put("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updated = (
        db.query(Notification)
        .filter(Notification.read.is_(False))
        .filter(audience_filter(current_user.role))
        .update({Notification.read: True}, synchronize_session=False)
    )
    db.commit()
    return {"detail": f"{updated} notifications marked as read"}


@router.put("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id)
        .filter(audience_filter(current_user.role))
        .first()
    )
    # 404 rather than 403 for a row outside the audience: distinguishing
    # "exists but forbidden" from "does not exist" would confirm that a
    # watchlist alert had been raised, which is the thing being withheld.
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read = True
    db.commit()
    db.refresh(notification)
    return NotificationOut.model_validate(notification)
