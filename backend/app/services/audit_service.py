"""Helper for writing audit log rows."""
from sqlalchemy.orm import Session

from app.models.models import AuditLog, User


def write_audit(
    db: Session,
    action: str,
    detail: str | None = None,
    user: User | None = None,
) -> None:
    """Persist an audit entry. Commits immediately so entries survive later rollbacks."""
    entry = AuditLog(
        user_id=user.id if user is not None else None,
        username=user.username if user is not None else None,
        action=action,
        detail=detail,
    )
    db.add(entry)
    db.commit()
