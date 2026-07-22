"""Short-lived signed URLs for protected biometric media.

User photos and unknown-visitor snapshots are sensitive and must never be
served from a public static mount. Instead the API returns signed URLs of the
form:

    /api/media/{category}/{filename}?exp=<unix_ts>&sig=<hmac>

The HMAC (SECRET_KEY) covers category + filename + expiry, so the signature is
an unforgeable, time-limited capability to read exactly one file. `<img>` tags
can use these URLs directly (no Authorization header needed), and they stop
working once they expire — an leaked URL is only useful for a few minutes.
"""
import hashlib
import hmac
import time
from pathlib import PurePosixPath

from app.core.config import settings

# Categories map to on-disk directories; nothing else may be served.
CATEGORIES = {
    "uploads": "UPLOADS_DIR",
    "unknown_faces": "UNKNOWN_FACES_DIR",
}

# How long a signed media URL stays valid. Long enough for a dashboard to
# render, short enough that a leaked URL expires quickly.
MEDIA_URL_TTL_SECONDS = 15 * 60


def _sign(category: str, filename: str, exp: int) -> str:
    msg = f"{category}/{filename}/{exp}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def sign_media_path(stored_url: str | None, ttl: int = MEDIA_URL_TTL_SECONDS) -> str | None:
    """Convert a stored '/static/<category>/<file>' value into a signed URL.

    Returns None for falsy input, or the input unchanged if it is not a
    recognized static media path (defensive — should not normally happen).
    """
    if not stored_url:
        return None
    parts = PurePosixPath(stored_url).parts
    # Expect ('/', 'static', '<category>', '<filename>')
    if len(parts) < 4 or parts[1] != "static" or parts[2] not in CATEGORIES:
        return stored_url
    category, filename = parts[2], parts[3]
    exp = int(time.time()) + ttl
    sig = _sign(category, filename, exp)
    return f"/api/media/{category}/{filename}?exp={exp}&sig={sig}"


def verify_media_signature(category: str, filename: str, exp: int, sig: str) -> bool:
    """Constant-time validation of a signed media URL."""
    if category not in CATEGORIES:
        return False
    if exp < int(time.time()):
        return False
    expected = _sign(category, filename, exp)
    return hmac.compare_digest(expected, sig)


def category_dir(category: str):
    return getattr(settings, CATEGORIES[category])
