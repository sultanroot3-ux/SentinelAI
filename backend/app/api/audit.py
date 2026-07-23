"""Read-only audit trail listing (viewer for the existing audit_logs table)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.database import get_db
from app.models.models import AuditLog, User
from app.schemas.schemas import AuditLogOut, PaginatedAudit

router = APIRouter(prefix="/api/audit", tags=["audit"])

# Matches the seeded RBAC catalogue: audit.view -> admin, security_officer
_AUDIT_ROLES = ("admin", "security_officer")


@router.get("", response_model=PaginatedAudit)
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    action: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_AUDIT_ROLES)),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(AuditLog.detail.ilike(like), AuditLog.username.ilike(like)))
    total = q.count()
    rows = (
        q.order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedAudit(
        items=[AuditLogOut.model_validate(r) for r in rows], total=total, page=page
    )


@router.get("/actions", response_model=list[str])
def list_actions(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_AUDIT_ROLES)),
):
    """Distinct action names, for the viewer's filter dropdown."""
    return [a for (a,) in db.query(AuditLog.action).distinct().order_by(AuditLog.action)]
