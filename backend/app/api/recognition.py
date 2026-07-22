"""Recognition endpoint: analyze a single frame."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.utils import serialize_user
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.models import User
from app.schemas.schemas import RecognitionResponse
from app.services import face_service

router = APIRouter(prefix="/api/recognition", tags=["recognition"])


@router.post("/frame", response_model=RecognitionResponse, response_model_exclude_none=False)
def recognize_frame(
    file: UploadFile = File(...),
    camera: str = "webcam",
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not face_service.cv2_available():
        raise HTTPException(
            status_code=503,
            detail="Face pipeline unavailable: OpenCV (opencv-python) and/or numpy "
            "are not installed on the server.",
        )

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")

    img = face_service.decode_image(content)
    if img is None:
        raise HTTPException(status_code=422, detail="Could not decode image")

    raw_faces = face_service.process_frame(content, db, camera=camera)
    faces = []
    for f in raw_faces:
        match = f.get("match")
        faces.append(
            {
                "box": f["box"],
                "confidence": f["confidence"],
                "match": serialize_user(match) if match is not None else None,
                "score": f.get("score"),
                "liveness": f["liveness"],
            }
        )
    return {"faces": faces}
