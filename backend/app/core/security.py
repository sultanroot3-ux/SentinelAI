"""Password hashing, JWT creation/validation and auth dependencies.

Token model:
- ACCESS tokens: short-lived (default 30 min), sent as `Authorization: Bearer`.
- REFRESH tokens: long-lived (default 7 days), single-use — each refresh
  rotates the token; the jti of every issued refresh token is stored in the
  refresh_tokens table so it can be revoked (logout, password change).
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.models import RefreshToken, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# auto_error=False so we can return a clean 401 {detail} ourselves
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(user: User, db: Session) -> str:
    """Issue a refresh token and record its jti for rotation/revocation."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    jti = uuid.uuid4().hex
    db.add(
        RefreshToken(
            jti=jti, user_id=user.id, expires_at=expire.replace(tzinfo=None)
        )
    )
    db.commit()
    payload = {"sub": str(user.id), "jti": jti, "type": "refresh", "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def consume_refresh_token(token: str, db: Session) -> User:
    """Validate + revoke (rotate) a refresh token; returns its user.

    Raises 401 if the token is invalid, expired, of the wrong type, unknown,
    or already used/revoked.
    """
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    row = (
        db.query(RefreshToken).filter(RefreshToken.jti == payload.get("jti")).first()
    )
    if row is None or row.revoked:
        raise HTTPException(status_code=401, detail="Refresh token revoked or unknown")
    if row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Refresh token expired")
    row.revoked = True  # single-use: rotation happens by issuing a new one
    db.commit()
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def revoke_all_refresh_tokens(user_id: int, db: Session) -> int:
    """Revoke every live refresh token for a user (logout-all / password change)."""
    count = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .update({"revoked": True})
    )
    db.commit()
    return count


def decode_token(token: str) -> dict:
    """Decode a JWT, raising 401 on any failure."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def get_user_from_token(token: str, db: Session) -> User:
    payload = decode_token(token)
    # Refresh tokens must never work as access tokens
    if payload.get("type") == "refresh":
        raise HTTPException(status_code=401, detail="Refresh token cannot be used for access")
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return get_user_from_token(credentials.credentials, db)


def require_roles(*roles: str):
    """Dependency factory enforcing that the current user has one of the roles."""

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return current_user

    return checker
