"""Shared serialization helpers for API routers.

Media URLs (photos, snapshots) are converted to short-lived signed URLs here
so that no serialized response ever exposes a directly-fetchable static path.
"""
from app.core.media import sign_media_path
from app.models.models import Case, RecognitionLog, UnknownFace, User
from app.schemas.schemas import CaseOut, RecognitionLogOut, UnknownFaceOut, UserOut


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
