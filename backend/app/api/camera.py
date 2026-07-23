"""Camera endpoints: MJPEG stream + status + stream-token issuance."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import (
    STREAM_TOKEN_EXPIRE_SECONDS,
    create_stream_token,
    get_current_user,
    get_user_from_stream_token,
)
from app.db.database import get_db
from app.models.models import User
from app.schemas.schemas import CameraStatus, StreamTokenResponse
from app.services import camera_service
from app.services.settings_service import get_setting

router = APIRouter(prefix="/api/camera", tags=["camera"])


@router.post("/stream-token", response_model=StreamTokenResponse)
def issue_stream_token(user: User = Depends(get_current_user)):
    """Short-lived single-purpose token for the MJPEG <img> URL.

    Access tokens are deliberately rejected by /stream: URLs end up in
    web-server logs, and a logged stream token expires within a minute and
    cannot call any API endpoint.
    """
    return StreamTokenResponse(
        stream_token=create_stream_token(user),
        expires_in=STREAM_TOKEN_EXPIRE_SECONDS,
    )


@router.get("/stream")
def stream(
    token: str = Query(..., description="Short-lived stream token from POST /api/camera/stream-token (query param because <img> tags cannot send headers)"),
    analyze: bool = Query(False, description="Run live face recognition and draw overlays on the stream"),
    db: Session = Depends(get_db),
):
    # Browser <img src> cannot set Authorization headers; auth via a
    # single-purpose short-lived token (never an access token — see above).
    get_user_from_stream_token(token, db)  # raises 401 if invalid

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
