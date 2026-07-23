"""Investigation service: AI face/scene analysis + investigation reports.

Data policy (enforced by construction):
- Identity fields (name, employee id, badge, department, ...) come ONLY from
  the local authorized database. Nothing is fetched from, or matched against,
  any external source.
- Every AI-derived value is an ESTIMATE from local models/heuristics and is
  labelled as such, with the method that produced it.
- Attributes with no local model installed are reported as unavailable
  rather than guessed (emotion, object detection, OCR when missing).
"""
import logging
import shutil
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (
    AccessHistory,
    Camera,
    FaceEmbedding,
    RecognitionLog,
    UnknownFace,
    User,
    Watchlist,
    WatchlistEntry,
)
from app.services import face_service
from app.services.rbac_service import get_camera_by_name

logger = logging.getLogger("sentinelai.investigation")

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

# Optional OCR: only used if BOTH pytesseract and the tesseract binary exist.
try:
    import pytesseract

    _OCR_AVAILABLE = shutil.which("tesseract") is not None
except ImportError:  # pragma: no cover
    pytesseract = None
    _OCR_AVAILABLE = False


# ---------------------------------------------------------------------------
# Face attribute estimation (all values are estimates)
# ---------------------------------------------------------------------------
def _crop(img, box, pad_ratio: float = 0.0):
    x, y, w, h = box
    pad = int(pad_ratio * max(w, h))
    y0, y1 = max(0, y - pad), min(img.shape[0], y + h + pad)
    x0, x1 = max(0, x - pad), min(img.shape[1], x + w + pad)
    crop = img[y0:y1, x0:x1]
    return crop if crop.size else img


def _blur_metrics(face_img) -> tuple[float, str]:
    """Laplacian variance: higher = sharper. Returns (score, label)."""
    gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
    score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if score >= 100:
        label = "sharp"
    elif score >= 40:
        label = "slightly blurred"
    else:
        label = "blurry"
    return round(score, 1), label


def _brightness_metrics(img) -> tuple[float, str]:
    mean = float(img.mean())
    if mean >= 170:
        label = "bright"
    elif mean >= 90:
        label = "normal"
    elif mean >= 45:
        label = "dim"
    else:
        label = "dark"
    return round(mean, 1), label


def _estimate_glasses(img, face) -> dict:
    """Low-confidence heuristic: edge density across the eye strip vs cheeks.

    Frames of glasses add strong edges around the eyes. This is a heuristic,
    not a trained classifier — confidence is reported accordingly.
    """
    try:
        kps = np.asarray(face.kps)  # [left_eye, right_eye, nose, mouth_l, mouth_r]
        eye_l, eye_r = kps[0], kps[1]
        eye_w = max(abs(eye_r[0] - eye_l[0]), 24)
        cx, cy = (eye_l + eye_r) / 2
        half_w, half_h = int(eye_w), max(int(eye_w * 0.35), 8)
        y0, y1 = max(0, int(cy - half_h)), min(img.shape[0], int(cy + half_h))
        x0, x1 = max(0, int(cx - half_w)), min(img.shape[1], int(cx + half_w))
        strip = img[y0:y1, x0:x1]
        if strip.size == 0:
            raise ValueError("empty eye strip")
        edges = cv2.Canny(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY), 80, 160)
        density = float((edges > 0).mean())
        return {
            "value": bool(density > 0.18),
            "method": "edge-density heuristic",
            "confidence": "low",
        }
    except Exception:
        return {"value": None, "method": "unavailable", "confidence": None}


def _estimate_mask(img, face) -> dict:
    """Low-confidence heuristic: hue difference between forehead and mouth areas.

    A mask usually makes the lower face a different, more uniform colour than
    the upper face. Heuristic only — confidence reported accordingly.
    """
    try:
        kps = np.asarray(face.kps)
        eye_l, eye_r, nose = kps[0], kps[1], kps[2]
        mouth = (kps[3] + kps[4]) / 2
        eye_cy = (eye_l[1] + eye_r[1]) / 2
        s = max(int(abs(eye_r[0] - eye_l[0]) * 0.35), 6)

        def patch(cx, cy):
            x0, y0 = max(0, int(cx - s)), max(0, int(cy - s))
            return img[y0:y0 + 2 * s, x0:x0 + 2 * s]

        forehead = patch((eye_l[0] + eye_r[0]) / 2, eye_cy - (mouth[1] - eye_cy) * 0.6)
        lower = patch(mouth[0], (nose[1] + mouth[1]) / 2)
        if forehead.size == 0 or lower.size == 0:
            raise ValueError("empty patch")
        f_hsv = cv2.cvtColor(forehead, cv2.COLOR_BGR2HSV).reshape(-1, 3).mean(axis=0)
        l_hsv = cv2.cvtColor(lower, cv2.COLOR_BGR2HSV).reshape(-1, 3).mean(axis=0)
        hue_diff = float(min(abs(f_hsv[0] - l_hsv[0]), 180 - abs(f_hsv[0] - l_hsv[0])))
        sat_diff = float(abs(f_hsv[1] - l_hsv[1]))
        return {
            "value": bool(hue_diff > 22 or sat_diff > 70),
            "method": "color-difference heuristic",
            "confidence": "low",
        }
    except Exception:
        return {"value": None, "method": "unavailable", "confidence": None}


def analyze_face(img, face, box) -> dict:
    """Per-face AI estimates. Every value is an estimate from local models."""
    face_img = _crop(img, box, pad_ratio=0.1)
    blur_score, blur_label = _blur_metrics(face_img)
    brightness, brightness_label = _brightness_metrics(face_img)
    w, h = box[2], box[3]

    gender = getattr(face, "gender", None)  # insightface: 1 = male, 0 = female
    age = getattr(face, "age", None)
    pose = getattr(face, "pose", None)  # (pitch, yaw, roll)

    return {
        "note": "All values below are AI estimates from local models, not verified facts.",
        "face_quality": {
            "estimate": (
                "good"
                if blur_label == "sharp" and brightness_label in ("normal", "bright") and min(w, h) >= 80
                else "poor"
                if blur_label == "blurry" or brightness_label == "dark" or min(w, h) < 40
                else "fair"
            ),
            "face_size_px": [w, h],
            "detection_confidence": round(float(face.det_score), 4),
        },
        "blur": {"score": blur_score, "estimate": blur_label, "method": "laplacian-variance"},
        "brightness": {"value": brightness, "estimate": brightness_label},
        "age_estimate": int(age) if age is not None else None,
        "gender_estimate": (
            {1: "male", 0: "female"}.get(int(gender), None) if gender is not None else None
        ),
        "emotion_estimate": {
            "value": None,
            "method": "unavailable (no local emotion model installed)",
        },
        "head_pose_estimate": (
            {
                "pitch": round(float(pose[0]), 1),
                "yaw": round(float(pose[1]), 1),
                "roll": round(float(pose[2]), 1),
            }
            if pose is not None
            else None
        ),
        "mask_estimate": _estimate_mask(img, face),
        "glasses_estimate": _estimate_glasses(img, face),
    }


def analyze_scene(img, num_faces: int) -> dict:
    """Whole-frame estimates. Honest about what has no local model."""
    brightness, brightness_label = _brightness_metrics(img)
    h, w = img.shape[:2]

    ocr_text = None
    ocr_method = "unavailable (pytesseract/tesseract not installed)"
    if _OCR_AVAILABLE:
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            text = pytesseract.image_to_string(gray, timeout=5).strip()
            ocr_text = text or None
            ocr_method = "tesseract"
        except Exception:
            ocr_method = "tesseract (failed)"

    return {
        "note": "Scene values are AI estimates from local analysis only.",
        "resolution": [w, h],
        "brightness": {"value": brightness, "estimate": brightness_label},
        "description_estimate": (
            f"{brightness_label.capitalize()} scene, {w}x{h}, "
            f"{num_faces} face{'s' if num_faces != 1 else ''} detected."
        ),
        "object_detection": {
            "objects": None,
            "method": "unavailable (no local object-detection model installed)",
        },
        "ocr_text": {"value": ocr_text, "method": ocr_method},
    }


# ---------------------------------------------------------------------------
# Watchlist / history lookups (authorized local DB only)
# ---------------------------------------------------------------------------
def _watchlist_hits(db: Session, user_id: int | None = None,
                    unknown_face_ids: list[int] | None = None) -> list[dict]:
    q = (
        db.query(WatchlistEntry, Watchlist)
        .join(Watchlist, WatchlistEntry.watchlist_id == Watchlist.id)
        .filter(Watchlist.active.is_(True))
    )
    if user_id is not None:
        q = q.filter(WatchlistEntry.user_id == user_id)
    elif unknown_face_ids:
        q = q.filter(WatchlistEntry.unknown_face_id.in_(unknown_face_ids))
    else:
        return []
    return [
        {
            "watchlist": wl.name,
            "level": wl.level,
            "reason": entry.reason,
            "added_at": entry.created_at.isoformat(),
        }
        for entry, wl in q.all()
    ]


def _employee_history(db: Session, user_id: int, limit: int = 10) -> list[dict]:
    logs = (
        db.query(RecognitionLog)
        .filter(RecognitionLog.user_id == user_id)
        .order_by(RecognitionLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "timestamp": log.timestamp.isoformat(),
            "camera": log.camera,
            "score": log.score,
        }
        for log in logs
    ]


def _similar_unknown_sightings(db: Session, embedding, threshold: float = 0.45,
                               limit: int = 200) -> list[tuple[int, float]]:
    """Match an embedding against stored unknown-face embeddings (local DB only)."""
    if np is None or embedding is None:
        return []
    rows = (
        db.query(FaceEmbedding.unknown_face_id, FaceEmbedding.embedding)
        .filter(FaceEmbedding.unknown_face_id.isnot(None))
        .order_by(FaceEmbedding.id.desc())
        .limit(limit)
        .all()
    )
    hits: list[tuple[int, float]] = []
    for uf_id, blob in rows:
        vec = np.frombuffer(blob, dtype=np.float32)
        if vec.size != embedding.size:
            continue
        score = face_service.cosine_similarity(embedding, vec)
        if score >= threshold:
            hits.append((uf_id, round(score, 4)))
    hits.sort(key=lambda t: -t[1])
    return hits


# ---------------------------------------------------------------------------
# Snapshot persistence for investigations
# ---------------------------------------------------------------------------
def _save_snapshot(img) -> str | None:
    try:
        filename = (
            f"investigation_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            f"_{uuid.uuid4().hex[:8]}.jpg"
        )
        path = settings.UNKNOWN_FACES_DIR / filename
        cv2.imwrite(str(path), img)
        return f"/static/unknown_faces/{filename}"
    except Exception:
        logger.exception("Failed to save investigation snapshot")
        return None


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------
def _employee_report(db: Session, user: User, score: float, camera: Camera | None,
                     camera_name: str, snapshot_url: str | None) -> dict:
    """Investigation report for a matched employee — DB fields only."""
    last_seen_log = (
        db.query(RecognitionLog)
        .filter(RecognitionLog.user_id == user.id)
        .order_by(RecognitionLog.timestamp.desc())
        .first()
    )
    location = camera.location if camera else None
    return {
        "person_type": "employee",
        "full_name": user.name,
        "employee_id": user.employee_id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,  # only if present in the local DB
        "department": user.department.name if user.department else None,
        "job_title": user.job_title,
        "office_building": user.office_building,
        "badge_number": user.badge_number,
        "access_level": user.access_level,
        "status": user.status,
        "photo_url": user.photo_url,
        "camera_name": camera.name if camera else camera_name,
        "camera_location": (
            {
                "name": location.name,
                "building": location.building,
                "floor": location.floor,
                "room": location.room,
            }
            if location
            else None
        ),
        "detection_time": datetime.utcnow().isoformat(),
        "last_seen": last_seen_log.timestamp.isoformat() if last_seen_log else None,
        "recognition_confidence": round(score, 4),
        "recognition_history": _employee_history(db, user.id),
        "snapshot_url": snapshot_url,
        "watchlist_hits": _watchlist_hits(db, user_id=user.id),
    }


def _unknown_report(db: Session, unknown: UnknownFace, camera: Camera | None,
                    camera_name: str, snapshot_url: str | None,
                    similar: list[tuple[int, float]]) -> dict:
    location = camera.location if camera else None
    prior = [uf_id for uf_id, _ in similar if uf_id != unknown.id]
    prior_rows = (
        db.query(UnknownFace).filter(UnknownFace.id.in_(prior)).all() if prior else []
    )
    return {
        "person_type": "unknown",
        "unknown_person_id": unknown.unknown_person_id,
        "camera_name": camera.name if camera else camera_name,
        "camera_location": (
            {
                "name": location.name,
                "building": location.building,
                "floor": location.floor,
                "room": location.room,
            }
            if location
            else None
        ),
        "detection_time": unknown.timestamp.isoformat(),
        "snapshot_url": snapshot_url or unknown.snapshot_url,
        "similar_prior_sightings": [
            {
                "unknown_person_id": row.unknown_person_id,
                "timestamp": row.timestamp.isoformat(),
                "camera": row.camera,
                "snapshot_url": row.snapshot_url,
                "similarity": next((s for uid, s in similar if uid == row.id), None),
            }
            for row in prior_rows
        ],
        "watchlist_hits": _watchlist_hits(
            db, unknown_face_ids=[unknown.id] + prior
        ),
    }


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------
def investigate_frame(image_bytes: bytes, db: Session,
                      camera_name: str = "webcam") -> dict:
    """Full investigation of one frame.

    Detect -> liveness -> embed -> match against the local DB only.
    Matched employees get a profile report; unmatched faces are registered as
    unknown persons (snapshot + embedding + camera + timestamp) and linked to
    similar prior sightings by embedding similarity.
    """
    if not face_service.insightface_available():
        return {"error": "insightface not available", "faces": [], "scene": None}

    img = face_service.decode_image(image_bytes)
    if img is None:
        return {"error": "invalid image", "faces": [], "scene": None}

    from app.services.settings_service import get_setting

    threshold = float(get_setting(db, "recognition_threshold", 0.45))
    camera = get_camera_by_name(db, camera_name)
    faces = face_service._get_insightface_app().get(img)
    snapshot_url = _save_snapshot(img) if faces else None

    reports: list[dict] = []
    for face in faces:
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        box = [x1, y1, x2 - x1, y2 - y1]
        embedding = face.normed_embedding.astype(np.float32)
        liveness = face_service.check_liveness(img, box)
        user, score = face_service._match_embedding(embedding, db, threshold)
        ai_analysis = analyze_face(img, face, box)

        if user is not None:
            db.add(
                RecognitionLog(
                    user_id=user.id,
                    camera=camera_name,
                    camera_id=camera.id if camera else None,
                    score=round(score, 4),
                    snapshot_url=snapshot_url,
                )
            )
            db.add(
                AccessHistory(
                    user_id=user.id,
                    camera_id=camera.id if camera else None,
                    event="detected",
                    detail=f"Investigation match (score {score:.2f})",
                )
            )
            db.commit()
            report = _employee_report(db, user, score, camera, camera_name, snapshot_url)
        else:
            crop_url = face_service._save_unknown_snapshot(img, box)
            unknown = UnknownFace(
                snapshot_url=crop_url,
                camera=camera_name,
                camera_id=camera.id if camera else None,
                status="new",
            )
            db.add(unknown)
            db.flush()
            unknown.unknown_person_id = f"UNK-{unknown.id:06d}"
            db.add(
                FaceEmbedding(
                    unknown_face_id=unknown.id,
                    embedding=embedding.tobytes(),
                    model="buffalo_l",
                )
            )
            db.add(
                AccessHistory(
                    unknown_face_id=unknown.id,
                    camera_id=camera.id if camera else None,
                    event="detected",
                    detail="Investigation: unregistered person",
                )
            )
            db.commit()
            similar = _similar_unknown_sightings(db, embedding, threshold)
            report = _unknown_report(db, unknown, camera, camera_name, crop_url, similar)

        report.update(
            {
                "box": box,
                "liveness": liveness,
                "best_match_score": round(score, 4) if score > -1.0 else None,
                "ai_analysis": ai_analysis,
            }
        )
        reports.append(report)

    return {
        "faces": reports,
        "scene": analyze_scene(img, len(faces)),
        "camera": camera_name,
        "analyzed_at": datetime.utcnow().isoformat(),
        "data_policy": (
            "Identity data is sourced exclusively from the authorized local "
            "database. AI attributes are estimates and are labelled as such."
        ),
    }
