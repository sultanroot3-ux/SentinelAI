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
import threading
import time
import uuid
from collections import deque
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (
    AccessHistory,
    FaceEmbedding,
    RecognitionLog,
    UnknownFace,
    User,
)
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
# Sync endpoints run on a threadpool, so lazy singletons and the embedding
# cache are touched concurrently. These locks make init + cache rebuild atomic.
_MODEL_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()


def cv2_available() -> bool:
    return cv2 is not None and np is not None


def insightface_available() -> bool:
    return _INSIGHTFACE_AVAILABLE and cv2_available()


def _get_insightface_app():
    """Lazily initialise the buffalo_l FaceAnalysis model (downloads ~300 MB once)."""
    global _INSIGHTFACE_APP
    if _INSIGHTFACE_APP is None:
        with _MODEL_LOCK:
            if _INSIGHTFACE_APP is None:  # double-checked: only one thread builds
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
# insightface landmark_2d_106 eye contours (verified empirically by rendering
# indexed landmarks on sample faces — see docs/TESTING.md §6):
_LEFT_EYE_IDX = list(range(33, 43))    # 33..42
_RIGHT_EYE_IDX = list(range(87, 97))   # 87..96


def _eye_openness(lmk, idx) -> float:
    """Eye openness ratio: vertical / horizontal extent of the eye contour.

    Index-order agnostic (uses bounding extents), so it is robust even if the
    exact upper/lower-lid point identities differ between model versions.
    """
    pts = lmk[idx]
    w = float(pts[:, 0].max() - pts[:, 0].min())
    h = float(pts[:, 1].max() - pts[:, 1].min())
    return h / w if w > 0 else 0.0


class LivenessMonitor:
    """Temporal liveness for live video streams — three independent signals.

    1. BLINK: eye-openness (per-frame, from the 106-point landmarks) dips
       below ~55%% of its rolling median and recovers. Photos never blink.
    2. NON-RIGID MOTION: normalized 5-point keypoint geometry variance.
       A photo/screen moves rigidly; a real face constantly deforms slightly.
    3. HEAD-POSE MICRO-MOTION: std of (pitch, yaw, roll) from the 3D landmark
       model. A mounted photo/screen is nearly static in pose space.

    Verdict: LIVE if a blink was observed, OR both motion signals exceed
    their thresholds. This defeats printed photos and static screen replays;
    it is best-effort (not certified PAD) against high-quality video replays.
    """

    BLINK_DROP = 0.55          # openness must dip below 55% of rolling median
    MOTION_THRESHOLD = 0.0035  # normalized kps std
    POSE_STD_THRESHOLD = 0.35  # degrees

    def __init__(self, window: int = 25, min_samples: int = 8):
        self.samples: deque = deque(maxlen=window)       # normalized kps
        self.pose_samples: deque = deque(maxlen=window)  # (pitch, yaw, roll)
        self.openness: deque = deque(maxlen=window * 2)  # avg eye openness
        self.min_samples = min_samples
        self.blinks = 0
        self._eye_closed = False

    def _update_blink(self, face) -> None:
        lmk = getattr(face, "landmark_2d_106", None)
        if lmk is None:
            return
        lmk = np.asarray(lmk, dtype=np.float32)
        openness = (_eye_openness(lmk, _LEFT_EYE_IDX)
                    + _eye_openness(lmk, _RIGHT_EYE_IDX)) / 2.0
        self.openness.append(openness)
        if len(self.openness) < 5:
            return
        median = float(np.median(self.openness))
        if median <= 0:
            return
        # Hysteresis: count a blink on the closed->open transition
        if openness < self.BLINK_DROP * median:
            self._eye_closed = True
        elif self._eye_closed:
            self._eye_closed = False
            self.blinks += 1

    def update(self, face) -> dict:
        """Feed one insightface detection; returns a liveness verdict dict."""
        box = face.bbox
        size = max(box[2] - box[0], box[3] - box[1])
        if size <= 0:
            return {"passed": False, "method": "blink+motion+pose", "note": "invalid box"}

        # Signal 1: blink
        self._update_blink(face)

        # Signal 2: non-rigid keypoint motion (translation/scale invariant)
        kps = np.asarray(face.kps, dtype=np.float32)
        norm = (kps - kps.mean(axis=0)) / float(size)
        self.samples.append(norm.flatten())

        # Signal 3: head-pose micro-motion
        pose = getattr(face, "pose", None)
        if pose is not None:
            self.pose_samples.append(np.asarray(pose, dtype=np.float32))

        if len(self.samples) < self.min_samples:
            return {
                "passed": None,
                "method": "blink+motion+pose",
                "note": "collecting frames",
                "blinks": self.blinks,
            }

        motion = float(np.stack(self.samples).std(axis=0).mean())
        pose_std = (
            float(np.stack(self.pose_samples).std(axis=0).mean())
            if len(self.pose_samples) >= self.min_samples
            else 0.0
        )
        passed = self.blinks >= 1 or (
            motion >= self.MOTION_THRESHOLD and pose_std >= self.POSE_STD_THRESHOLD
        )
        return {
            "passed": passed,
            "method": "blink+motion+pose",
            "blinks": self.blinks,
            "motion": round(motion, 5),
            "pose_std": round(pose_std, 3),
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


# In-memory embedding cache: one (N x 512) unit-normalized matrix, so matching
# a face against ALL registered users is a single vectorized dot product per
# frame instead of a per-user Python loop + full-table read.
#
# Multi-worker consistency: every lookup compares a cheap DB version signature
# (row count + max id of face_embeddings — both change on every enrollment,
# re-enrollment and cascade delete). A worker that did not handle the write
# sees the signature change on its next frame and rebuilds — no restart, no
# cross-process signalling. invalidate_embedding_cache() remains for same-
# worker immediacy.
_EMBED_CACHE: dict = {"valid": False, "ids": None, "matrix": None, "sig": None}


def invalidate_embedding_cache() -> None:
    """Call after any change to stored embeddings (photo upload, user delete)."""
    _EMBED_CACHE["valid"] = False


def _embedding_version_signature(db: Session):
    """Cheap cross-worker change signal for stored embeddings."""
    from sqlalchemy import func

    from app.models.models import FaceEmbedding

    return db.query(
        func.count(FaceEmbedding.id), func.max(FaceEmbedding.id)
    ).one()


def _get_embedding_matrix(db: Session):
    """Return (user_ids array, unit-normalized embedding matrix) or (None, None)."""
    sig = _embedding_version_signature(db)
    if not _EMBED_CACHE["valid"] or _EMBED_CACHE["sig"] != sig:
        # Lock the rebuild so concurrent threadpool requests can't observe a
        # half-updated cache (ids set before matrix, or vice versa).
        with _CACHE_LOCK:
            if not _EMBED_CACHE["valid"] or _EMBED_CACHE["sig"] != sig:
                users = (
                    db.query(User.id, User.face_embedding)
                    .filter(
                        User.face_registered.is_(True),
                        User.face_embedding.isnot(None),
                    )
                    .all()
                )
                ids, rows = [], []
                for uid, blob in users:
                    vec = np.frombuffer(blob, dtype=np.float32)
                    norm = float(np.linalg.norm(vec))
                    if vec.size == 0 or norm == 0:
                        continue
                    ids.append(uid)
                    rows.append(vec / norm)
                _EMBED_CACHE["ids"] = np.asarray(ids) if ids else None
                _EMBED_CACHE["matrix"] = np.stack(rows) if rows else None
                _EMBED_CACHE["sig"] = sig
                _EMBED_CACHE["valid"] = True
    return _EMBED_CACHE["ids"], _EMBED_CACHE["matrix"]


def _match_embedding(embedding, db: Session, threshold: float):
    """Compare an embedding against all registered users. Returns (user, score)."""
    ids, matrix = _get_embedding_matrix(db)
    if matrix is None or embedding.size != matrix.shape[1]:
        return None, -1.0
    emb_norm = float(np.linalg.norm(embedding))
    if emb_norm == 0:
        return None, -1.0
    scores = matrix @ (embedding / emb_norm)  # cosine vs every user at once
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])
    if best_score >= threshold:
        user = db.get(User, int(ids[best_idx]))
        if user is not None:
            return user, best_score
        invalidate_embedding_cache()  # cached id no longer exists
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
                    _record_unknown(db, img, box, camera, embedding=embedding)
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


def _camera_id_for(db: Session, camera: str) -> int | None:
    """Resolve a camera name to its Camera row id (None if not registered)."""
    from app.services.rbac_service import get_camera_by_name

    cam = get_camera_by_name(db, camera)
    return cam.id if cam else None


def _record_recognition(db: Session, user: User, camera: str, score: float) -> None:
    """Persist a RecognitionLog + AccessHistory, once per user per cooldown."""
    now = time.monotonic()
    last = _last_user_logged_at.get(user.id, 0.0)
    if now - last < _RECOG_LOG_COOLDOWN_SECONDS:
        return
    _last_user_logged_at[user.id] = now
    camera_id = _camera_id_for(db, camera)
    db.add(RecognitionLog(user_id=user.id, camera=camera, camera_id=camera_id,
                          score=round(score, 4)))
    db.add(AccessHistory(user_id=user.id, camera_id=camera_id, event="detected",
                         detail=f"Live recognition (score {score:.2f})"))
    db.commit()


def _record_unknown(db: Session, img, box, camera: str, embedding=None) -> None:
    """Persist an UnknownFace row (+ id, embedding, access history), rate-limited."""
    global _last_unknown_saved_at
    now = time.monotonic()
    if now - _last_unknown_saved_at < _UNKNOWN_COOLDOWN_SECONDS:
        return
    _last_unknown_saved_at = now

    snapshot_url = _save_unknown_snapshot(img, box)
    camera_id = _camera_id_for(db, camera)
    unknown = UnknownFace(snapshot_url=snapshot_url, camera=camera,
                          camera_id=camera_id, status="new")
    db.add(unknown)
    db.flush()
    unknown.unknown_person_id = f"UNK-{unknown.id:06d}"
    if embedding is not None:
        db.add(FaceEmbedding(unknown_face_id=unknown.id,
                             embedding=embedding.tobytes(), model="buffalo_l"))
    db.add(AccessHistory(unknown_face_id=unknown.id, camera_id=camera_id,
                         event="detected", detail="Live detection: unregistered person"))
    db.commit()

    if get_setting(db, "notify_on_unknown", True):
        notification_service.create_notification(
            db,
            title="Unknown person detected",
            message=f"An unrecognized face was detected on camera '{camera}'.",
            level="alert",
        )
