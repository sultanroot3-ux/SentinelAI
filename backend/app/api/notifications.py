"""Notification endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.models import Notification, User
from app.schemas.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Notification)
    if unread_only:
        query = query.filter(Notification.read.is_(False))
    items = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [NotificationOut.model_validate(n) for n in items]


@router.put("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    updated = (
        db.query(Notification)
        .filter(Notification.read.is_(False))
        .update({Notification.read: True})
    )
    db.commit()
    return {"detail": f"{updated} notifications marked as read"}


@router.put("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read = True
    db.commit()
    db.refresh(notification)
    return NotificationOut.model_validate(notification)
