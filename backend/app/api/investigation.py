"""Investigation endpoints.

POST /api/investigation/analyze     — full AI investigation of an uploaded frame
GET  /api/investigation/employee/{id} — investigation report for an employee
GET  /api/investigation/unknown/{id}  — investigation report for an unknown person

Identity data comes exclusively from the local database; AI attributes are
labelled estimates (see investigation_service docstring).
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.utils import read_upload_capped
from app.core.media import sign_media_path
from app.core.security import require_roles
from app.db.database import get_db
from app.models.models import UnknownFace, User
from app.schemas.schemas import InvestigationResponse
from app.services import face_service, investigation_service
from app.services.audit_service import write_audit
from app.services.rbac_service import get_camera_by_name

router = APIRouter(prefix="/api/investigation", tags=["investigation"])

_INVESTIGATOR_ROLES = ("admin", "security_officer")


def _sign_report_media(report: dict) -> dict:
    """Convert stored media paths in a report to short-lived signed URLs."""
    for face in report.get("faces", []):
        for key in ("snapshot_url", "photo_url"):
            if face.get(key):
                face[key] = sign_media_path(face[key])
        for sighting in face.get("similar_prior_sightings", []) or []:
            if sighting.get("snapshot_url"):
                sighting["snapshot_url"] = sign_media_path(sighting["snapshot_url"])
    return report


@router.post("/analyze", response_model=InvestigationResponse)
def analyze(
    file: UploadFile = File(...),
    camera: str = Query("webcam", max_length=80),
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles(*_INVESTIGATOR_ROLES)),
):
    if not face_service.insightface_available():
        raise HTTPException(
            status_code=503, detail="Face analysis engine (insightface) unavailable."
        )
    content = read_upload_capped(file)

    report = investigation_service.investigate_frame(content, db, camera_name=camera)
    if report.get("error") == "invalid image":
        raise HTTPException(status_code=422, detail="Could not decode image")

    write_audit(
        db,
        "investigation_analyze",
        f"Analyzed frame from camera '{camera}': {len(report['faces'])} face(s)",
        user=officer,
    )
    return _sign_report_media(report)


@router.get("/employee/{user_id}", response_model=InvestigationResponse)
def employee_report(
    user_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles(*_INVESTIGATOR_ROLES)),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    camera = get_camera_by_name(db, "webcam")
    report = investigation_service._employee_report(
        db, user, score=1.0, camera=camera, camera_name="webcam", snapshot_url=None
    )
    # A DB-profile lookup is not a camera detection: remove detection-only fields
    report.pop("detection_time", None)
    report.pop("recognition_confidence", None)
    write_audit(db, "investigation_employee",
                f"Viewed investigation report for user id={user_id}", user=officer)
    return _sign_report_media({"faces": [report], "scene": None})


@router.get("/unknown/{unknown_id}", response_model=InvestigationResponse)
def unknown_report(
    unknown_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles(*_INVESTIGATOR_ROLES)),
):
    unknown = db.get(UnknownFace, unknown_id)
    if unknown is None:
        raise HTTPException(status_code=404, detail="Unknown person not found")

    # Link to similar prior sightings via its stored embedding (local DB only)
    similar = []
    if unknown.embeddings:
        import numpy as np

        vec = np.frombuffer(unknown.embeddings[0].embedding, dtype=np.float32)
        similar = investigation_service._similar_unknown_sightings(db, vec)

    report = investigation_service._unknown_report(
        db, unknown, unknown.camera_ref, unknown.camera, unknown.snapshot_url, similar
    )
    write_audit(db, "investigation_unknown",
                f"Viewed investigation report for unknown id={unknown_id}", user=officer)
    return _sign_report_media({"faces": [report], "scene": None})
