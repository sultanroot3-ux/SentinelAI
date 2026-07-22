"""Camera endpoints: MJPEG stream + status."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_user_from_token
from app.db.database import get_db
from app.models.models import User
from app.schemas.schemas import CameraStatus
from app.services import camera_service
from app.services.settings_service import get_setting

router = APIRouter(prefix="/api/camera", tags=["camera"])


@router.get("/stream")
def stream(
    token: str = Query(..., description="JWT access token (query param because <img> tags cannot send headers)"),
    analyze: bool = Query(False, description="Run live face recognition and draw overlays on the stream"),
    db: Session = Depends(get_db),
):
    # Browser <img src> cannot set Authorization headers, so auth via ?token=
    get_user_from_token(token, db)  # raises 401 if invalid

    source = str(get_setting(db, "camera_source", "0"))
    if not camera_service.camera_available(source):
        raise HTTPException(
            status_code=503,
            detail=f"Camera source '{source}' is unavailable.",
        )
    generator = (
        camera_service.analyzed_mjpeg_generator(source)
        if analyze
        else camera_service.mjpeg_generator(source)
    )
    return StreamingResponse(
        generator,
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/status", response_model=CameraStatus)
def status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    source = str(get_setting(db, "camera_source", "0"))
    return CameraStatus(available=camera_service.camera_available(source), source=source)
