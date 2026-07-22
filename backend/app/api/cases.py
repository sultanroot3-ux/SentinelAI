"""Investigation case endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.api.utils import serialize_case
from app.core.security import get_current_user, require_roles
from app.db.database import get_db
from app.models.models import Case, UnknownFace, User
from app.schemas.schemas import CaseCreate, CaseOut, CaseUpdate, PaginatedCases
from app.services.audit_service import write_audit
from app.services.notification_service import create_notification

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _next_case_number(db: Session) -> str:
    last = db.query(Case).order_by(Case.id.desc()).first()
    next_id = (last.id if last else 0) + 1
    return f"CASE-{next_id:04d}"


@router.get("", response_model=PaginatedCases)
def list_cases(
    status: str | None = Query(None, pattern="^(open|investigating|closed)$"),
    priority: str | None = Query(None, pattern="^(low|medium|high|critical)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Case).options(
        joinedload(Case.unknown_face), joinedload(Case.assignee)
    )
    if status:
        query = query.filter(Case.status == status)
    if priority:
        query = query.filter(Case.priority == priority)
    total = query.count()
    items = (
        query.order_by(Case.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedCases(items=[serialize_case(c) for c in items], total=total, page=page)


@router.post("", response_model=CaseOut, status_code=201)
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "security_officer")),
):
    unknown = db.get(UnknownFace, payload.unknown_face_id)
    if unknown is None:
        raise HTTPException(status_code=404, detail="Unknown face not found")

    if payload.assigned_to is not None and db.get(User, payload.assigned_to) is None:
        raise HTTPException(status_code=422, detail="Assigned user not found")

    case = Case(
        case_number=_next_case_number(db),
        unknown_face_id=unknown.id,
        priority=payload.priority,
        notes=payload.notes,
        assigned_to=payload.assigned_to,
        status="open",
    )
    db.add(case)
    db.flush()

    unknown.status = "case_opened"
    unknown.case_id = case.id
    db.commit()
    db.refresh(case)

    write_audit(
        db,
        "case_create",
        f"Opened case {case.case_number} for unknown face id={unknown.id}",
        user=current_user,
    )
    create_notification(
        db,
        title=f"Case {case.case_number} opened",
        message=f"An investigation case was opened for an unknown visitor (camera '{unknown.camera}').",
        level="warning",
    )
    return serialize_case(case)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return serialize_case(case)


@router.put("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: int,
    payload: CaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "security_officer")),
):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    data = payload.model_dump(exclude_unset=True)
    if "assigned_to" in data and data["assigned_to"] is not None:
        if db.get(User, data["assigned_to"]) is None:
            raise HTTPException(status_code=422, detail="Assigned user not found")
    for field, value in data.items():
        setattr(case, field, value)
    db.commit()
    db.refresh(case)

    write_audit(
        db,
        "case_update",
        f"Updated case {case.case_number}: {', '.join(sorted(data.keys())) or 'no fields'}",
        user=current_user,
    )
    return serialize_case(case)
