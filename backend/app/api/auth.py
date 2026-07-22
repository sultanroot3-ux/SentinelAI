"""Auth endpoints: login + current user."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.utils import serialize_user
from app.core.security import create_access_token, get_current_user, verify_password
from app.db.database import get_db
from app.models.models import User
from app.schemas.schemas import LoginRequest, LoginResponse, UserOut
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        write_audit(db, "login_failed", f"Failed login attempt for '{payload.username}'")
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user)
    write_audit(db, "login", f"User '{user.username}' logged in", user=user)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=serialize_user(user),
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)
