"""Department CRUD endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.db.database import get_db
from app.models.models import Department, User
from app.schemas.schemas import DepartmentCreate, DepartmentOut, DepartmentUpdate

router = APIRouter(prefix="/api/departments", tags=["departments"])


def _serialize(dept: Department, user_count: int) -> DepartmentOut:
    return DepartmentOut(
        id=dept.id,
        name=dept.name,
        description=dept.description,
        user_count=user_count,
    )


@router.get("", response_model=list[DepartmentOut])
def list_departments(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    counts = dict(
        db.query(User.department_id, func.count(User.id))
        .filter(User.department_id.isnot(None))
        .group_by(User.department_id)
        .all()
    )
    departments = db.query(Department).order_by(Department.id).all()
    return [_serialize(d, counts.get(d.id, 0)) for d in departments]


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    if db.query(Department).filter(Department.name == payload.name).first():
        raise HTTPException(status_code=422, detail="Department name already exists")
    dept = Department(name=payload.name, description=payload.description)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return _serialize(dept, 0)


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(
    department_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    count = db.query(func.count(User.id)).filter(User.department_id == dept.id).scalar() or 0
    return _serialize(dept, count)


@router.put("/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != dept.name:
        if db.query(Department).filter(Department.name == data["name"]).first():
            raise HTTPException(status_code=422, detail="Department name already exists")
    for field, value in data.items():
        setattr(dept, field, value)
    db.commit()
    db.refresh(dept)
    count = db.query(func.count(User.id)).filter(User.department_id == dept.id).scalar() or 0
    return _serialize(dept, count)


@router.delete("/{department_id}")
def delete_department(
    department_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    # Detach users instead of deleting them
    db.query(User).filter(User.department_id == dept.id).update({User.department_id: None})
    db.delete(dept)
    db.commit()
    return {"detail": "Department deleted"}
