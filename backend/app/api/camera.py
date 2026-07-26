"""Camera endpoints: MJPEG stream + status + stream-token issuance."""
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.utils import enforce_quota
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

logger = logging.getLogger("sentinelai.camera")

router = APIRouter(prefix="/api/camera", tags=["camera"])

# Each live MJPEG stream occupies a worker thread for as long as the client
# keeps the connection open, and the analyzed variant additionally runs
# inference on every Nth frame. Without a cap, opening streams is a one-request
# way to exhaust the threadpool (B3). This counter is deliberately per-process:
# the resource being protected — this process's threadpool — is per-process.
MAX_CONCURRENT_STREAMS = 4
_active_streams = 0
_stream_lock = threading.Lock()


def _acquire_stream_slot() -> bool:
    global _active_streams
    with _stream_lock:
        if _active_streams >= MAX_CONCURRENT_STREAMS:
            return False
        _active_streams += 1
        return True


def _release_stream_slot() -> None:
    global _active_streams
    with _stream_lock:
        _active_streams = max(0, _active_streams - 1)


def active_stream_count() -> int:
    with _stream_lock:
        return _active_streams


@router.post("/stream-token", response_model=StreamTokenResponse)
def issue_stream_token(
    response: Response,
    user: User = Depends(get_current_user),
):
    """Short-lived single-purpose token for the MJPEG <img> URL.

    Access tokens are deliberately rejected by /stream: URLs end up in
    web-server logs, and a logged stream token expires within a minute and
    cannot call any API endpoint.
    """
    enforce_quota("stream_token", user, response)
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
    if not _acquire_stream_slot():
        logger.warning(
            "Stream refused: %d concurrent streams already active (max %d)",
            active_stream_count(), MAX_CONCURRENT_STREAMS,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"Too many concurrent camera streams (limit {MAX_CONCURRENT_STREAMS}). "
                "Close an existing stream and retry."
            ),
            headers={"Retry-After": "5"},
        )

    inner = (
        camera_service.analyzed_mjpeg_generator(source)
        if analyze
        else camera_service.mjpeg_generator(source)
    )

    def guarded():
        """Release the slot however the stream ends (client close, error, EOF)."""
        try:
            yield from inner
        finally:
            _release_stream_slot()

    return StreamingResponse(
        guarded(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/status", response_model=CameraStatus)
def status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    source = str(get_setting(db, "camera_source", "0"))
    return CameraStatus(available=camera_service.camera_available(source), source=source)
