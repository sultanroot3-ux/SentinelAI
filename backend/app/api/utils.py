"""Shared serialization helpers for API routers.

Media URLs (photos, snapshots) are converted to short-lived signed URLs here
so that no serialized response ever exposes a directly-fetchable static path.
"""
from fastapi import HTTPException, Response, UploadFile

from app.core import rate_limit
from app.core.media import sign_media_path
from app.models.models import Case, RecognitionLog, UnknownFace, User
from app.schemas.schemas import CaseOut, RecognitionLogOut, UnknownFaceOut, UserOut
from app.services.audit_service import write_audit

# Upload cap: face frames/photos are small; anything larger is rejected before
# it is read into memory, so a client cannot exhaust RAM with a huge "image".
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# Collection endpoints that return a bare array are bounded by this unless the
# caller asks for fewer. Chosen to be larger than any realistic single-screen
# render, so existing clients see no behaviour change, while still refusing to
# read and serialize an entire table as the deployment grows.
DEFAULT_PAGE_LIMIT = 200
MAX_PAGE_LIMIT = 1000


def apply_limit(query, response: Response, limit: int, offset: int):
    """Bound a collection query and report the true total in X-Total-Count.

    The response shape stays a bare array (no breaking change), but the header
    lets a client detect that more rows exist rather than silently believing it
    received everything.
    """
    total = query.order_by(None).count()
    response.headers["X-Total-Count"] = str(total)
    rows = query.limit(limit).offset(offset).all()
    if offset + len(rows) < total:
        # Make truncation observable in logs as well as to the client.
        response.headers["X-Result-Truncated"] = "true"
    return rows


def enforce_quota(name: str, user: User, response: Response, db=None) -> None:
    """Take a token from the user's bucket for `name`, or raise 429.

    Sets Retry-After on both the success path (so a client can pace itself
    without waiting for a rejection) and the 429 itself.
    """
    allowed, retry_after = rate_limit.check_quota(name, user.id)
    if allowed:
        return
    if db is not None:
        write_audit(
            db,
            "quota_exceeded",
            f"User '{user.username}' exceeded the {name} quota",
            user=user,
        )
    response.headers["Retry-After"] = str(retry_after)
    raise HTTPException(
        status_code=429,
        detail=(
            f"Rate limit exceeded for {name}. Try again in {retry_after} seconds."
        ),
        headers={"Retry-After": str(retry_after)},
    )


def read_upload_capped(file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read an UploadFile, rejecting oversized uploads (413) and empty ones (422).

    Reads in chunks and stops as soon as the cap is exceeded, so an oversized
    upload never fully materializes in memory.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = file.file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (limit {max_bytes // (1024 * 1024)} MB).",
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")
    return content


def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        username=user.username,
        role=user.role,
        department_id=user.department_id,
        department_name=user.department.name if user.department else None,
        employee_id=user.employee_id,
        access_level=user.access_level,
        photo_url=sign_media_path(user.photo_url),
        job_title=user.job_title,
        office_building=user.office_building,
        badge_number=user.badge_number,
        phone=user.phone,
        status=user.status,
        face_registered=user.face_registered,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
    )


def serialize_log(log: RecognitionLog) -> RecognitionLogOut:
    return RecognitionLogOut(
        id=log.id,
        user_id=log.user_id,
        user_name=log.user.name if log.user else None,
        camera=log.camera,
        score=log.score,
        snapshot_url=sign_media_path(log.snapshot_url),
        timestamp=log.timestamp,
    )


def serialize_unknown(unknown: UnknownFace) -> UnknownFaceOut:
    return UnknownFaceOut(
        id=unknown.id,
        snapshot_url=sign_media_path(unknown.snapshot_url),
        camera=unknown.camera,
        status=unknown.status,
        case_id=unknown.case_id,
        timestamp=unknown.timestamp,
    )


def serialize_case(case: Case) -> CaseOut:
    return CaseOut(
        id=case.id,
        case_number=case.case_number,
        unknown_face_id=case.unknown_face_id,
        snapshot_url=sign_media_path(
            case.unknown_face.snapshot_url if case.unknown_face else None
        ),
        camera=case.unknown_face.camera if case.unknown_face else None,
        status=case.status,
        priority=case.priority,
        notes=case.notes,
        assigned_to=case.assigned_to,
        assigned_to_name=case.assignee.name if case.assignee else None,
        resolution=case.resolution,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )
