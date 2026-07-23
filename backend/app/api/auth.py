"""Auth endpoints: login (rate-limited), refresh, logout, change-password, me."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.utils import serialize_user
from app.core import rate_limit
from app.core.net import client_ip
from app.core.security import (
    consume_refresh_token,
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    revoke_all_refresh_tokens,
    verify_password,
)
from app.db.database import get_db
from app.models.models import User
from app.schemas.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    UserOut,
)
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    allowed, retry_after = rate_limit.check_allowed(payload.username, ip)
    if not allowed:
        response.headers["Retry-After"] = str(retry_after)
        write_audit(
            db, "login_rate_limited", f"Rate-limited login for '{payload.username}' from {ip}"
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        rate_limit.record_failure(payload.username, ip)
        write_audit(db, "login_failed", f"Failed login attempt for '{payload.username}'")
        raise HTTPException(status_code=401, detail="Invalid username or password")

    rate_limit.record_success(payload.username, ip)
    write_audit(db, "login", f"User '{user.username}' logged in", user=user)
    return LoginResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user, db),
        token_type="bearer",
        user=serialize_user(user),
    )


@router.post("/refresh", response_model=LoginResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a refresh token for a new token pair (single-use rotation)."""
    user = consume_refresh_token(payload.refresh_token, db)
    return LoginResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user, db),
        token_type="bearer",
        user=serialize_user(user),
    )


@router.post("/logout")
def logout(
    payload: RefreshRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke the presented refresh token (and audit the logout)."""
    try:
        consume_refresh_token(payload.refresh_token, db)
    except HTTPException:
        pass  # already revoked/expired — logout is idempotent
    write_audit(db, "logout", f"User '{current_user.username}' logged out", user=current_user)
    return {"detail": "Logged out"}


@router.post("/change-password", response_model=UserOut)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=422, detail="New password must be different")

    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    db.commit()
    # Invalidate every existing session for this account
    revoke_all_refresh_tokens(current_user.id, db)
    write_audit(
        db, "password_change", f"User '{current_user.username}' changed password",
        user=current_user,
    )
    return serialize_user(current_user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)
