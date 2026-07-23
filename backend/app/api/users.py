"""User management endpoints."""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.utils import serialize_user
from app.core.config import settings
from app.core.security import get_current_user, hash_password, require_roles
from app.db.database import get_db
from app.models.models import FaceEmbedding, User
from app.schemas.schemas import UserCreate, UserOut, UserUpdate
from app.services import face_service
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/users", tags=["users"])

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@router.get("", response_model=list[UserOut])
def list_users(
    search: str | None = None,
    department_id: int | None = None,
    role: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(User).options(joinedload(User.department))
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                User.name.ilike(like),
                User.email.ilike(like),
                User.username.ilike(like),
                User.employee_id.ilike(like),
            )
        )
    if department_id is not None:
        query = query.filter(User.department_id == department_id)
    if role:
        query = query.filter(User.role == role)
    return [serialize_user(u) for u in query.order_by(User.id).all()]


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=422, detail="Username already exists")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=422, detail="Email already exists")

    user = User(
        name=payload.name,
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        department_id=payload.department_id,
        employee_id=payload.employee_id,
        access_level=payload.access_level,
        job_title=payload.job_title,
        office_building=payload.office_building,
        badge_number=payload.badge_number,
        phone=payload.phone,
        status=payload.status or "active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    write_audit(db, "user_create", f"Created user '{user.username}' (id={user.id})", user=admin)
    return serialize_user(user)


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return serialize_user(user)


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)
    if "username" in data and data["username"] != user.username:
        if db.query(User).filter(User.username == data["username"]).first():
            raise HTTPException(status_code=422, detail="Username already exists")
    if "email" in data and data["email"] != user.email:
        if db.query(User).filter(User.email == data["email"]).first():
            raise HTTPException(status_code=422, detail="Email already exists")
    if "password" in data:
        password = data.pop("password")
        if password:
            user.password_hash = hash_password(password)
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    write_audit(db, "user_update", f"Updated user '{user.username}' (id={user.id})", user=admin)
    return serialize_user(user)


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=422, detail="You cannot delete your own account")

    username = user.username
    db.delete(user)
    db.commit()
    face_service.invalidate_embedding_cache()
    write_audit(db, "user_delete", f"Deleted user '{username}' (id={user_id})", user=admin)
    return {"detail": "User deleted"}


@router.post("/{user_id}/photo", response_model=UserOut)
def upload_photo(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin", "security_officer")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    ext = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported image type '{ext}'. Allowed: {sorted(ALLOWED_IMAGE_EXTENSIONS)}",
        )

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")

    filename = f"user_{user.id}_{uuid.uuid4().hex[:8]}{ext}"
    dest = settings.UPLOADS_DIR / filename
    dest.write_bytes(content)
    user.photo_url = f"/static/uploads/{filename}"

    # Compute + store face embedding when insightface is available.
    if face_service.insightface_available():
        embedding = face_service.compute_embedding(content)
        if embedding is None:
            db.commit()
            db.refresh(user)
            raise HTTPException(
                status_code=422,
                detail="No face detected in the uploaded photo. Photo saved but face not registered.",
            )
        user.face_embedding = embedding.tobytes()
        user.face_registered = True
        # Also record in the face_embeddings table (supports multiple
        # enrollment photos per employee for the investigation system).
        db.add(FaceEmbedding(user_id=user.id, embedding=embedding.tobytes(),
                             model="buffalo_l"))
        note = "face embedding registered"
    else:
        # Photo stored; recognition needs insightface installed.
        user.face_registered = False
        note = "photo stored, embedding skipped (insightface not installed)"

    db.commit()
    db.refresh(user)
    face_service.invalidate_embedding_cache()
    write_audit(
        db,
        "user_photo_upload",
        f"Photo uploaded for user '{user.username}' (id={user.id}): {note}",
        user=admin,
    )
    return serialize_user(user)
