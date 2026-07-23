"""Read-only RBAC catalogue: roles and their permissions."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.models import Permission, Role, User
from app.schemas.schemas import PermissionOut, RoleOut

router = APIRouter(prefix="/api/rbac", tags=["rbac"])


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return (
        db.query(Role)
        .options(joinedload(Role.permissions))
        .order_by(Role.name)
        .all()
    )


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(Permission).order_by(Permission.code).all()
