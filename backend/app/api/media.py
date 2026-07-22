"""Authenticated, signed-URL access to protected biometric media.

Replaces the old public /static mounts. A valid short-lived signature
(see app.core.media) is required — user photos and unknown-visitor snapshots
are never anonymously accessible.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.media import category_dir, verify_media_signature

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{category}/{filename}")
def get_media(category: str, filename: str, exp: int = Query(...), sig: str = Query(...)):
    if not verify_media_signature(category, filename, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired media URL")

    # Defense in depth: only ever serve a plain basename from the category dir,
    # so a crafted filename cannot escape via path traversal.
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=403, detail="Invalid filename")

    path = Path(category_dir(category)) / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(path))
