"""Visitor registration + check-in / check-out."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.security import require_roles
from app.db.database import get_db
from app.models.models import AccessHistory, User, Visitor
from app.schemas.schemas import VisitorCreate, VisitorOut, VisitorUpdate
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/visitors", tags=["visitors"])

_VISITOR_ROLES = ("admin", "security_officer", "receptionist")


def _serialize(v: Visitor) -> VisitorOut:
    return VisitorOut(
        id=v.id,
        name=v.name,
        company=v.company,
        purpose=v.purpose,
        host_user_id=v.host_user_id,
        host_name=v.host.name if v.host else None,
        badge_number=v.badge_number,
        photo_url=v.photo_url,
        status=v.status,
        check_in=v.check_in,
        check_out=v.check_out,
        created_at=v.created_at,
    )


@router.get("", response_model=list[VisitorOut])
def list_visitors(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_VISITOR_ROLES)),
):
    q = db.query(Visitor).options(joinedload(Visitor.host))
    if status:
        q = q.filter(Visitor.status == status)
    return [_serialize(v) for v in q.order_by(Visitor.created_at.desc()).all()]


@router.post("", response_model=VisitorOut, status_code=201)
def create_visitor(
    payload: VisitorCreate,
    db: Session = Depends(get_db),
    staff: User = Depends(require_roles(*_VISITOR_ROLES)),
):
    if payload.host_user_id is not None and db.get(User, payload.host_user_id) is None:
        raise HTTPException(status_code=422, detail="Host user not found")
    visitor = Visitor(**payload.model_dump())
    db.add(visitor)
    db.commit()
    db.refresh(visitor)
    write_audit(db, "visitor_create", f"Registered visitor '{visitor.name}'", user=staff)
    return _serialize(visitor)


@router.put("/{visitor_id}", response_model=VisitorOut)
def update_visitor(
    visitor_id: int,
    payload: VisitorUpdate,
    db: Session = Depends(get_db),
    staff: User = Depends(require_roles(*_VISITOR_ROLES)),
):
    visitor = db.get(Visitor, visitor_id)
    if visitor is None:
        raise HTTPException(status_code=404, detail="Visitor not found")
    data = payload.model_dump(exclude_unset=True)
    if "host_user_id" in data and data["host_user_id"] is not None:
        if db.get(User, data["host_user_id"]) is None:
            raise HTTPException(status_code=422, detail="Host user not found")
    for field, value in data.items():
        setattr(visitor, field, value)
    db.commit()
    db.refresh(visitor)
    return _serialize(visitor)


@router.post("/{visitor_id}/check-in", response_model=VisitorOut)
def check_in(
    visitor_id: int,
    db: Session = Depends(get_db),
    staff: User = Depends(require_roles(*_VISITOR_ROLES)),
):
    visitor = db.get(Visitor, visitor_id)
    if visitor is None:
        raise HTTPException(status_code=404, detail="Visitor not found")
    if visitor.status == "checked_in":
        raise HTTPException(status_code=422, detail="Visitor already checked in")
    visitor.status = "checked_in"
    visitor.check_in = datetime.utcnow()
    db.add(AccessHistory(visitor_id=visitor.id, event="check_in",
                         detail=f"Visitor '{visitor.name}' checked in"))
    db.commit()
    db.refresh(visitor)
    write_audit(db, "visitor_check_in", f"Checked in visitor '{visitor.name}'", user=staff)
    return _serialize(visitor)


@router.post("/{visitor_id}/check-out", response_model=VisitorOut)
def check_out(
    visitor_id: int,
    db: Session = Depends(get_db),
    staff: User = Depends(require_roles(*_VISITOR_ROLES)),
):
    visitor = db.get(Visitor, visitor_id)
    if visitor is None:
        raise HTTPException(status_code=404, detail="Visitor not found")
    if visitor.status != "checked_in":
        raise HTTPException(status_code=422, detail="Visitor is not checked in")
    visitor.status = "checked_out"
    visitor.check_out = datetime.utcnow()
    db.add(AccessHistory(visitor_id=visitor.id, event="check_out",
                         detail=f"Visitor '{visitor.name}' checked out"))
    db.commit()
    db.refresh(visitor)
    write_audit(db, "visitor_check_out", f"Checked out visitor '{visitor.name}'", user=staff)
    return _serialize(visitor)
