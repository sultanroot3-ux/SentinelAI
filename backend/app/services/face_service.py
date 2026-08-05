"""Face detection + recognition service (SentinelAI AI engine).

Degrades gracefully:
1. Preferred: insightface (buffalo_l) — detection + 512-d embeddings + recognition.
2. Fallback: OpenCV Haar cascade — detection only, no recognition.
3. If OpenCV itself is missing, callers should return HTTP 503.

Pipeline (see docs/API_CONTRACT.md):
frame -> detect faces -> liveness -> embed -> cosine match vs registered users
      -> match:   RecognitionLog (rate-limited per user)
      -> unknown: snapshot + UnknownFace row + alert notification (rate-limited)
      -> either:  watchlist check (rate-limited per person per camera) ->
                  audit entry + alert notification

The watchlist check runs on the insightface path only: the Haar fallback
produces no embeddings and therefore no identity, so there is nothing to match
a watchlist against.
"""
import logging
import threading
import uuid
from collections import deque

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import settings
from app.models.models import (
    AccessHistory,
    FaceEmbedding,
    RecognitionLog,
    UnknownFace,
    User,
    Watchlist,
    WatchlistEntry,
)
from app.services import notification_service
from app.services.settings_service import get_setting

logger = logging.getLogger("sentinelai.face")

# ---------------------------------------------------------------------------
# Optional dependency loading
# ---------------------------------------------------------------------------
# TODO(known, repo-wide — do not re-investigate): binding these names to None on
# ImportError makes every later use report as an error under pyright —
# reportOptionalMemberAccess on np.*/cv2.* ("frombuffer is not a known attribute
# of None") and reportPossiblyUnbound on FaceAnalysis. Around a dozen fire in
# this file alone; they are ALL false positives of this pattern, not real bugs.
# The guards cv2_available() / insightface_available() are what actually make
# these accesses safe, and every call path checks one of them first.
#
# Accepted as-is: no type checker runs in CI (.github/workflows/ci.yml), so
# nothing is gated on it. Silencing it properly means either per-line ignores
# throughout or restructuring the optional imports behind typed shims — a
# deliberate repo-wide cleanup, not something to fix in passing. If you came
# here because your editor lit up: this is expected, and it is not new.
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


# buffalo_l ships five models; we use three. Naming them explicitly rather than
# letting FaceAnalysis load whatever .onnx files it finds does two things:
#
#   - it keeps dev and production identical. The production image omits the two
#     unused models to save 145 MB, and a bare FaceAnalysis() adapts silently to
#     whatever is on disk — so a code path touching face.sex would work on a
#     developer machine with the full pack and fail only in production.
#   - it drops ~145 MB of RAM and the session-init cost for models nothing reads.
#
# Left out: landmark_3d_68 (1k3d68.onnx, 144 MB) and genderage (1.3 MB). Nothing
# in the codebase reads face.landmark_3d_68, face.sex or face.age. If that
# changes, add the module here *and* to KEEP_MODELS in docker/backend.Dockerfile.
INSIGHTFACE_MODULES = ["detection", "landmark_2d_106", "recognition"]


def _get_insightface_app():
    """Lazily initialise the buffalo_l FaceAnalysis model (downloads ~300 MB once)."""
    global _INSIGHTFACE_APP
    if _INSIGHTFACE_APP is None:
        with _MODEL_LOCK:
            if _INSIGHTFACE_APP is None:  # double-checked: only one thread builds
                app = FaceAnalysis(
                    name="buffalo_l", allowed_modules=INSIGHTFACE_MODULES
                )
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
# Watchlist alerting
# ---------------------------------------------------------------------------
# Watchlists used to be storage-only: full CRUD, a UI page, hits surfaced in
# on-demand investigation reports, and purge exemption in retention — but the
# live pipeline never consulted them, so a flagged person could walk past a
# camera and produce nothing but a routine recognition log.
#
# Two lookup paths, because the two entry kinds are not alike:
#   - employees: exact user_id membership, a dict hit.
#   - unknown persons: every sighting inserts a NEW unknown_faces row, so the
#     watchlisted row's id can never appear again. Re-identification has to go
#     through the embedding, the same cosine match used for employees.
#
# Alerts are keyed per (person, camera) rather than per person. The
# RecognitionLog cooldown is per user only, so a flagged person crossing from
# one camera to the next writes no second log — inheriting that key would make
# exactly the movement a watchlist exists to surface the thing it stays silent
# about.
_WATCHLIST_ALERT_COOLDOWN_SECONDS = 60.0

# Structural edits (add/remove an entry, archive a list) change the signature
# and rebuild immediately, which is what a cross-worker write looks like. An
# in-place field edit — flipping a level from warning to alert — changes no
# count, so a TTL bounds that staleness too.
#
# 30s, not a few seconds: this refresh re-reads every watchlist entry, and the
# only thing it can discover is a changed label or reason on a list whose
# membership is unchanged. Same-worker edits are already instant (the API calls
# invalidate_watchlist_cache), and membership changes are caught by the
# signature regardless of the TTL. Paying that scan every few seconds bought
# nothing and cost ~30 ms per tick on a 1000-entry watchlist.
_WATCHLIST_CACHE_TTL_SECONDS = 30.0

# Measured: 1k watchlisted unknowns = 2.9 MB resident, 10k = 28 MB (20 MB of
# float32 embeddings + 8 MB of Python metadata), per worker. 10k is where that
# starts being worth an operator's attention on a small container.
_WATCHLIST_SIZE_WARN_THRESHOLD = 10_000

_WATCHLIST_CACHE: dict = {
    "valid": False,
    "sig": None,
    "built_at": 0.0,
    "users": {},           # user_id -> hit metadata
    "unknown_ids": None,   # np.ndarray of unknown_face_id, row-aligned to the matrix
    "unknown_matrix": None,  # (N, 512) unit-normalized
    "unknown_id_set": None,  # frozenset backing the matrix; guards its reuse
    "unknown_meta": {},    # unknown_face_id -> hit metadata
}
_WATCHLIST_LOCK = threading.Lock()


def invalidate_watchlist_cache() -> None:
    """Call after any watchlist/entry write for same-worker immediacy."""
    _WATCHLIST_CACHE["valid"] = False


def _watchlist_signature(db: Session):
    """Cheap cross-worker change signal for watchlist membership."""
    from sqlalchemy import func, select

    active_lists = (
        select(func.count(Watchlist.id))
        .where(Watchlist.active.is_(True))
        .scalar_subquery()
    )
    return db.query(
        func.count(WatchlistEntry.id), func.max(WatchlistEntry.id), active_lists
    ).one()


def _get_watchlist_state(db: Session) -> dict:
    """Cached membership of every ACTIVE watchlist.

    Returns the cache dict itself; callers must treat it as read-only.
    """
    import time

    sig = _watchlist_signature(db)
    fresh = (time.time() - _WATCHLIST_CACHE["built_at"]) < _WATCHLIST_CACHE_TTL_SECONDS
    if _WATCHLIST_CACHE["valid"] and _WATCHLIST_CACHE["sig"] == sig and fresh:
        return _WATCHLIST_CACHE

    with _WATCHLIST_LOCK:
        fresh = (time.time() - _WATCHLIST_CACHE["built_at"]) < _WATCHLIST_CACHE_TTL_SECONDS
        if _WATCHLIST_CACHE["valid"] and _WATCHLIST_CACHE["sig"] == sig and fresh:
            return _WATCHLIST_CACHE

        rows = (
            db.query(WatchlistEntry, Watchlist)
            .join(Watchlist, WatchlistEntry.watchlist_id == Watchlist.id)
            .filter(Watchlist.active.is_(True))
            .all()
        )
        users: dict[int, dict] = {}
        unknown_meta: dict[int, dict] = {}
        for entry, wl in rows:
            meta = {
                "watchlist": wl.name,
                "level": wl.level,
                "reason": entry.reason,
                "entry_id": entry.id,
            }
            # First match wins if a person is on several lists; ordering by id
            # keeps that deterministic rather than dependent on row order.
            if entry.user_id is not None:
                if entry.user_id not in users or meta["entry_id"] < users[entry.user_id]["entry_id"]:
                    users[entry.user_id] = meta
            elif entry.unknown_face_id is not None:
                prev = unknown_meta.get(entry.unknown_face_id)
                if prev is None or meta["entry_id"] < prev["entry_id"]:
                    unknown_meta[entry.unknown_face_id] = meta

        # The embedding matrix is by far the expensive part of a rebuild (it
        # reads and normalizes 512 float32s per watchlisted unknown), and it
        # depends only on WHICH ids are listed. The TTL exists to catch in-place
        # edits — a level or reason change — which cannot alter that set. So
        # reuse the matrix whenever the id set is unchanged: without this, a
        # watchlist of ~1000 unknowns re-read every embedding every 5 seconds
        # and stalled an analyzed stream for ~350 ms each time.
        id_set = frozenset(unknown_meta)
        if id_set == _WATCHLIST_CACHE.get("unknown_id_set") and (
            _WATCHLIST_CACHE["unknown_matrix"] is not None or not id_set
        ):
            pass  # matrix + ids still valid
        else:
            ids, vectors = [], []
            if unknown_meta:
                # Joined rather than filtered with .in_(ids): a bind parameter
                # per watchlisted id blows the driver's parameter ceiling
                # (SQLite 32766, PostgreSQL 65535) and raises. The raise is
                # caught upstream, so the failure mode was watchlist alerting
                # silently switching off for the whole deployment once the list
                # grew past the limit — the worst possible way for a security
                # control to fail. The join has no such ceiling.
                embeddings = (
                    db.query(
                        FaceEmbedding.id,
                        FaceEmbedding.unknown_face_id,
                        FaceEmbedding.embedding,
                    )
                    .join(
                        WatchlistEntry,
                        WatchlistEntry.unknown_face_id == FaceEmbedding.unknown_face_id,
                    )
                    .join(Watchlist, Watchlist.id == WatchlistEntry.watchlist_id)
                    .filter(Watchlist.active.is_(True))
                    .all()
                )
                # A person on two active lists joins twice. Deduped on the row
                # id in Python rather than SQL DISTINCT, which would have to
                # compare the LargeBinary embedding column — cheap on SQLite,
                # unpredictable on PostgreSQL.
                seen: set[int] = set()
                for emb_id, uid, blob in embeddings:
                    if emb_id in seen:
                        continue
                    seen.add(emb_id)
                    vec = np.frombuffer(blob, dtype=np.float32)
                    norm = float(np.linalg.norm(vec))
                    if vec.size == 0 or norm == 0:
                        continue
                    ids.append(uid)
                    vectors.append(vec / norm)
            _WATCHLIST_CACHE["unknown_ids"] = np.asarray(ids) if ids else None
            _WATCHLIST_CACHE["unknown_matrix"] = np.stack(vectors) if vectors else None
            _WATCHLIST_CACHE["unknown_id_set"] = id_set
            # Resident per worker: 2 KB of embedding per watchlisted unknown,
            # plus ~800 B of metadata. Warn rather than cap — silently dropping
            # entries would mean silently not alerting on them, which is the one
            # outcome this feature exists to prevent. An operator who sees this
            # can prune the list or raise the container memory limit.
            if len(ids) > _WATCHLIST_SIZE_WARN_THRESHOLD:
                logger.warning(
                    "Watchlist re-identification set is large: %d embeddings "
                    "(~%.0f MB resident per worker). Matching stays correct; "
                    "consider pruning resolved entries.",
                    len(ids), len(ids) * 2848 / 1e6,
                )

        _WATCHLIST_CACHE["users"] = users
        _WATCHLIST_CACHE["unknown_meta"] = unknown_meta
        _WATCHLIST_CACHE["sig"] = sig
        _WATCHLIST_CACHE["built_at"] = time.time()
        _WATCHLIST_CACHE["valid"] = True
    return _WATCHLIST_CACHE


def _raise_watchlist_alert(db: Session, kind: str, ident: int, meta: dict,
                           camera: str, subject: str) -> None:
    """Audit + notify a watchlist match, once per person per camera per window.

    Identity, watchlist name and reason go to the audit log, which is role-gated
    (admin / security_officer). The in-app notification says only that a
    watchlisted person was seen and on which camera: /api/notifications is
    readable by EVERY authenticated role, so naming the person there would hand
    a receptionist the contents of the watchlist.
    """
    from app.core.shared_state import shared_state
    from app.services.audit_service import write_audit
    from app.services.rbac_service import get_camera_by_name

    # `camera` reaches process_image() straight from a client-supplied query
    # parameter (/api/recognition/frame?camera=...). Keying the cooldown on that
    # raw string would let any authenticated account mint a fresh bucket per
    # request — 60 frames/min through the recognition quota, each one a new
    # alert fanned out to email, Telegram and Discord. Resolve it against the
    # registered cameras instead: unregistered names all collapse into one
    # bucket, so the cooldown holds no matter what the client sends. The label
    # in the alert text comes from the database for the same reason.
    cam = get_camera_by_name(db, camera)
    cam_key = cam.id if cam is not None else "unregistered"
    cam_label = cam.name if cam is not None else "an unregistered source"

    if not shared_state.cooldown_acquire(
        f"cooldown:watchlist:{kind}:{ident}:{cam_key}",
        _WATCHLIST_ALERT_COOLDOWN_SECONDS,
    ):
        return

    level = meta.get("level") or "warning"
    write_audit(
        db,
        action="watchlist_match",
        detail=(
            f"{subject} matched watchlist '{meta.get('watchlist')}' "
            f"(level={level}) on camera '{cam_label}'. Reason: {meta.get('reason')}"
        ),
    )
    # The audit row is the forensic record and is written unconditionally; the
    # notification is the operator-facing channel and is the part that can be
    # muted.
    if get_setting(db, "notify_on_watchlist", True):
        notification_service.create_notification(
            db,
            title="Watchlist match",
            message=f"A watchlisted person was detected on camera '{cam_label}'.",
            level=level,
        )


def check_watchlist(db: Session, camera: str, user: User | None = None,
                    embedding=None, threshold: float | None = None,
                    state: dict | None = None) -> None:
    """Raise watchlist alerts for a recognized user and/or an unknown face.

    `threshold` governs the unknown-person re-identification only; the employee
    path needs none, because _match_embedding() already applied it in resolving
    `user`. Both therefore fire at exactly the configured recognition_threshold
    — deliberately the same value, since "is this the same face?" is the same
    question in both cases and a watchlist that triggered at a different
    similarity than recognition would be confusing to reason about. Defaults to
    the setting rather than a literal so the two cannot drift apart.

    `state` lets a caller reuse one membership snapshot across every face in a
    frame; process_image() does exactly that, so the signature query costs one
    round trip per frame instead of one per face. Omit it and the state is
    fetched (and cached) here.

    Never raises: a watchlist problem must not take the recognition pipeline
    down with it. A failure here means a missed alert, which is bad; a failure
    that propagates means the camera stops recognizing anyone at all, which is
    worse.
    """
    try:
        state = _get_watchlist_state(db) if state is None else state
        if user is not None:
            meta = state["users"].get(user.id)
            if meta is not None:
                _raise_watchlist_alert(
                    db, "user", user.id, meta, camera,
                    subject=f"Employee '{user.username}' (id={user.id})",
                )
            return

        matrix = state["unknown_matrix"]
        if embedding is None or matrix is None:
            return
        if embedding.size != matrix.shape[1]:
            return
        if threshold is None:
            threshold = float(get_setting(db, "recognition_threshold", 0.45))
        norm = float(np.linalg.norm(embedding))
        if norm == 0:
            return
        scores = matrix @ (embedding / norm)
        best_idx = int(np.argmax(scores))
        if float(scores[best_idx]) < threshold:
            return
        unknown_id = int(state["unknown_ids"][best_idx])
        meta = state["unknown_meta"].get(unknown_id)
        if meta is not None:
            _raise_watchlist_alert(
                db, "unknown", unknown_id, meta, camera,
                subject=f"Unknown person (unknown_face_id={unknown_id})",
            )
    except Exception:
        # Deliberately broad: see the docstring. Logged so a silently missing
        # alert is still discoverable.
        logger.exception("Watchlist check failed for camera %r", camera)


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
        filename = f"unknown_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
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
#  - one UnknownFace row per camera per cooldown window
#  - one RecognitionLog per user per cooldown window
#
# These live in shared_state, not module globals (B4). As per-process dicts the
# cooldowns fired once per window *per worker*, so the shipped 2-worker
# production config produced up to double the intended rows and alerts. The
# unknown-face cooldown is also keyed per camera: a global key meant a second
# camera's first sighting was silently swallowed by the first camera's.
_UNKNOWN_COOLDOWN_SECONDS = 10.0
_RECOG_LOG_COOLDOWN_SECONDS = 30.0


def reset_cooldowns() -> None:
    """Test helper: clear recognition/unknown cooldown state."""
    from app.core.shared_state import shared_state

    shared_state.reset_all()


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

    # One membership snapshot for the whole frame — see check_watchlist().
    # Guarded here too: a failure must leave the pipeline running with alerts
    # disabled for this frame, not abort the frame.
    try:
        watchlist_state = _get_watchlist_state(db)
    except Exception:
        logger.exception("Watchlist state unavailable for camera %r", camera)
        watchlist_state = None

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
                # Outside _record_recognition on purpose: that call is behind a
                # per-user 30s cooldown, and a watchlist hit must not be
                # suppressed by an unrelated logging window.
                if watchlist_state is not None:
                    check_watchlist(db, camera, user=user, state=watchlist_state)
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
                    # Same reasoning as the employee branch: _record_unknown is
                    # behind a per-camera 10s cooldown, and a watchlisted person
                    # of interest reappearing must not be swallowed by it.
                    if watchlist_state is not None:
                        check_watchlist(db, camera, embedding=embedding,
                                        threshold=threshold, state=watchlist_state)
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
    from app.core.shared_state import shared_state

    # Atomic across workers: exactly one caller wins the window.
    if not shared_state.cooldown_acquire(
        f"cooldown:recognition:{user.id}", _RECOG_LOG_COOLDOWN_SECONDS
    ):
        return
    camera_id = _camera_id_for(db, camera)
    db.add(RecognitionLog(user_id=user.id, camera=camera, camera_id=camera_id,
                          score=round(score, 4)))
    db.add(AccessHistory(user_id=user.id, camera_id=camera_id, event="detected",
                         detail=f"Live recognition (score {score:.2f})"))
    db.commit()


def _record_unknown(db: Session, img, box, camera: str, embedding=None) -> None:
    """Persist an UnknownFace row (+ id, embedding, access history), rate-limited."""
    from app.core.shared_state import shared_state

    if not shared_state.cooldown_acquire(
        f"cooldown:unknown:{camera}", _UNKNOWN_COOLDOWN_SECONDS
    ):
        return

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
