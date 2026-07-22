"""Face detection + recognition service (SentinelAI AI engine).

Degrades gracefully:
1. Preferred: insightface (buffalo_l) — detection + 512-d embeddings + recognition.
2. Fallback: OpenCV Haar cascade — detection only, no recognition.
3. If OpenCV itself is missing, callers should return HTTP 503.

Pipeline (see docs/API_CONTRACT.md):
frame -> detect faces -> liveness -> embed -> cosine match vs registered users
      -> match:   RecognitionLog (rate-limited per user)
      -> unknown: snapshot + UnknownFace row + alert notification (rate-limited)
"""
import logging
import time
import uuid
from collections import deque
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import RecognitionLog, UnknownFace, User
from app.services import notification_service
from app.services.settings_service import get_setting

logger = logging.getLogger("sentinelai.face")

# ---------------------------------------------------------------------------
# Optional dependency loading
# ---------------------------------------------------------------------------
try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

_INSIGHTFACE_APP = None
_INSIGHTFACE_AVAILABLE = False
try:
    import insightface  # noqa: F401
    from insightface.app import FaceAnalysis

    _INSIGHTFACE_AVAILABLE = True
except ImportError:
    logger.info(
        "insightface not installed - falling back to OpenCV Haar cascade "
        "(detection only, no recognition)."
    )

_HAAR_CASCADE = None


def cv2_available() -> bool:
    return cv2 is not None and np is not None


def insightface_available() -> bool:
    return _INSIGHTFACE_AVAILABLE and cv2_available()


def _get_insightface_app():
    """Lazily initialise the buffalo_l FaceAnalysis model (downloads ~300 MB once)."""
    global _INSIGHTFACE_APP
    if _INSIGHTFACE_APP is None:
        app = FaceAnalysis(name="buffalo_l")
        app.prepare(ctx_id=-1, det_size=(640, 640))  # CPU
        _INSIGHTFACE_APP = app
    return _INSIGHTFACE_APP


def _get_haar_cascade():
    global _HAAR_CASCADE
    if _HAAR_CASCADE is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _HAAR_CASCADE = cv2.CascadeClassifier(cascade_path)
    return _HAAR_CASCADE


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------
class LivenessMonitor:
    """Temporal liveness check for live video streams (anti-photo heuristic).

    Tracks the 5-point facial keypoints (eyes, nose, mouth corners) of the
    dominant face over a sliding window, normalized by face size. A printed
    photo or phone screen moves (mostly) rigidly, so its normalized keypoint
    geometry stays nearly constant, while a real face continuously deforms a
    little (blinks, expression micro-movement).

    This is a lightweight heuristic, not certified anti-spoofing — Module 6
    will extend it with blink detection / depth cues.
    """

    def __init__(self, window: int = 25, min_samples: int = 8,
                 rigidity_threshold: float = 0.0035):
        self.samples: deque = deque(maxlen=window)
        self.min_samples = min_samples
        self.rigidity_threshold = rigidity_threshold

    def update(self, face) -> dict:
        """Feed one insightface detection; returns a liveness verdict dict."""
        box = face.bbox
        size = max(box[2] - box[0], box[3] - box[1])
        if size <= 0:
            return {"passed": False, "method": "motion", "note": "invalid box"}
        # Normalize keypoints: translation- and scale-invariant geometry
        kps = np.asarray(face.kps, dtype=np.float32)
        norm = (kps - kps.mean(axis=0)) / float(size)
        self.samples.append(norm.flatten())
        if len(self.samples) < self.min_samples:
            return {"passed": None, "method": "motion", "note": "collecting frames"}
        motion = float(np.stack(self.samples).std(axis=0).mean())
        return {
            "passed": motion >= self.rigidity_threshold,
            "method": "motion",
            "score": round(motion, 5),
        }


def check_liveness(image, box) -> dict:
    """Single-frame API calls have no temporal context: report method honestly.

    Real temporal liveness runs in the analyzed camera stream (LivenessMonitor).
    """
    return {"passed": True, "method": "single-frame"}


# ---------------------------------------------------------------------------
# Image decoding / embeddings
# ---------------------------------------------------------------------------
def decode_image(image_bytes: bytes):
    """Decode raw bytes to a BGR image, or None if invalid."""
    if not cv2_available():
        return None
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def compute_embedding(image_bytes: bytes):
    """Return a normalized 512-d embedding for the largest face, or None."""
    if not insightface_available():
        return None
    img = decode_image(image_bytes)
    if img is None:
        return None
    faces = _get_insightface_app().get(img)
    if not faces:
        return None
    # Largest face by bounding-box area
    face = max(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
    )
    return face.normed_embedding.astype(np.float32)


def cosine_similarity(a, b) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _match_embedding(embedding, db: Session, threshold: float):
    """Compare an embedding against all registered users. Returns (user, score)."""
    best_user, best_score = None, -1.0
    users = (
        db.query(User)
        .filter(User.face_registered.is_(True), User.face_embedding.isnot(None))
        .all()
    )
    for user in users:
        stored = np.frombuffer(user.face_embedding, dtype=np.float32)
        if stored.size == 0 or embedding.size != stored.size:
            continue
        score = cosine_similarity(embedding, stored)
        if score > best_score:
            best_user, best_score = user, score
    if best_user is not None and best_score >= threshold:
        return best_user, best_score
    return None, best_score


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------
def _save_unknown_snapshot(img, box) -> str | None:
    """Crop + save an unknown face snapshot, returning its public URL."""
    try:
        x, y, w, h = box
        pad = int(0.25 * max(w, h))
        y0, y1 = max(0, y - pad), min(img.shape[0], y + h + pad)
        x0, x1 = max(0, x - pad), min(img.shape[1], x + w + pad)
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            crop = img
        filename = f"unknown_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
        path = settings.UNKNOWN_FACES_DIR / filename
        cv2.imwrite(str(path), crop)
        return f"/static/unknown_faces/{filename}"
    except Exception:
        logger.exception("Failed to save unknown-face snapshot")
        return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
# Rate limits so a live camera doesn't flood the database:
#  - one UnknownFace row per cooldown window
#  - one RecognitionLog per user per cooldown window
_last_unknown_saved_at: float = 0.0
_UNKNOWN_COOLDOWN_SECONDS = 10.0
_last_user_logged_at: dict[int, float] = {}
_RECOG_LOG_COOLDOWN_SECONDS = 30.0


def process_frame(image_bytes: bytes, db: Session, camera: str = "webcam",
                  liveness_monitor: "LivenessMonitor | None" = None) -> list[dict]:
    """Detect + recognize faces in an encoded frame (JPEG/PNG bytes)."""
    img = decode_image(image_bytes)
    if img is None:
        return []
    return process_image(img, db, camera=camera, liveness_monitor=liveness_monitor)


def process_image(img, db: Session, camera: str = "webcam",
                  liveness_monitor: "LivenessMonitor | None" = None) -> list[dict]:
    """Detect + recognize faces in a decoded BGR image.

    Returns a list of face dicts:
    {box, confidence, match: User|None, score, liveness, note?}
    Side effects: RecognitionLog rows for matches, UnknownFace rows (+ optional
    alert notification) for unrecognized faces — both rate-limited.
    """
    threshold = float(get_setting(db, "recognition_threshold", 0.45))
    liveness_enabled = bool(get_setting(db, "liveness_enabled", False))
    results: list[dict] = []

    if insightface_available():
        faces = _get_insightface_app().get(img)
        # The liveness monitor tracks the dominant (largest) face only
        dominant = max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
            default=None,
        )
        for face in faces:
            x1, y1, x2, y2 = [int(v) for v in face.bbox]
            box = [x1, y1, x2 - x1, y2 - y1]
            confidence = float(face.det_score)
            embedding = face.normed_embedding.astype(np.float32)
            user, score = _match_embedding(embedding, db, threshold)

            if liveness_monitor is not None and face is dominant:
                liveness = liveness_monitor.update(face)
            else:
                liveness = check_liveness(img, box)

            # With liveness enforcement on, a face that failed the temporal
            # check is treated as a potential spoof: report it, log nothing.
            spoof = liveness_enabled and liveness.get("passed") is False

            if user is not None and not spoof:
                _record_recognition(db, user, camera, score)
                results.append(
                    {
                        "box": box,
                        "confidence": confidence,
                        "match": user,
                        "score": round(score, 4),
                        "liveness": liveness,
                    }
                )
            else:
                if not spoof:
                    _record_unknown(db, img, box, camera)
                results.append(
                    {
                        "box": box,
                        "confidence": confidence,
                        "match": user if spoof else None,
                        "score": round(score, 4) if score > -1.0 else None,
                        "liveness": liveness,
                        **({"note": "Liveness check failed - possible spoof."} if spoof else {}),
                    }
                )
        return results

    # ---- Haar cascade fallback: detection only ----
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    detections = _get_haar_cascade().detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
    )
    for (x, y, w, h) in detections:
        box = [int(x), int(y), int(w), int(h)]
        liveness = check_liveness(img, box)
        _record_unknown(db, img, box, camera)
        results.append(
            {
                "box": box,
                "confidence": 0.5,  # Haar gives no calibrated confidence
                "match": None,
                "score": None,
                "liveness": liveness,
                "note": "Recognition unavailable: insightface not installed "
                "(Haar cascade detection only).",
            }
        )
    return results


def _record_recognition(db: Session, user: User, camera: str, score: float) -> None:
    """Persist a RecognitionLog, at most once per user per cooldown window."""
    now = time.monotonic()
    last = _last_user_logged_at.get(user.id, 0.0)
    if now - last < _RECOG_LOG_COOLDOWN_SECONDS:
        return
    _last_user_logged_at[user.id] = now
    db.add(RecognitionLog(user_id=user.id, camera=camera, score=round(score, 4)))
    db.commit()


def _record_unknown(db: Session, img, box, camera: str) -> None:
    """Persist an UnknownFace row + alert notification, rate-limited."""
    global _last_unknown_saved_at
    now = time.monotonic()
    if now - _last_unknown_saved_at < _UNKNOWN_COOLDOWN_SECONDS:
        return
    _last_unknown_saved_at = now

    snapshot_url = _save_unknown_snapshot(img, box)
    unknown = UnknownFace(snapshot_url=snapshot_url, camera=camera, status="new")
    db.add(unknown)
    db.commit()

    if get_setting(db, "notify_on_unknown", True):
        notification_service.create_notification(
            db,
            title="Unknown person detected",
            message=f"An unrecognized face was detected on camera '{camera}'.",
            level="alert",
        )
