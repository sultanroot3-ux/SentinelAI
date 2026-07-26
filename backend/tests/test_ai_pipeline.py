"""Real AI engine tests — insightface / ONNX Runtime, not the Haar fallback (B1).

These exercise the part of the system CI previously never ran: detection,
512-d ArcFace embedding, cosine matching, the threshold, the recognition
side effects, and liveness against genuine landmark data.

Fixtures are the face images bundled with insightface itself (see ai_utils),
so no biometric data lives in this repository.

Run with SENTINEL_REQUIRE_AI=1 to make a missing engine a failure instead of a
skip — that is what the dedicated CI job uses.
"""
import numpy as np
import pytest

from app.services import face_service
from app.services.settings_service import get_setting

from ai_utils import crop_faces_as_jpeg, not_a_face_jpeg, require_ai

# The configured production default; the separation assertions below prove it
# sits inside the gap between same-identity and different-identity scores.
DEFAULT_THRESHOLD = 0.45


@pytest.fixture(scope="module", autouse=True)
def _ai_required():
    """Gate the whole module and warm the model once."""
    require_ai()
    assert face_service.insightface_available(), (
        "insightface imported but face_service reports it unavailable"
    )
    face_service._get_insightface_app()  # load models once for the module


@pytest.fixture(scope="module")
def face_jpegs() -> list[bytes]:
    """Six distinct identities, one JPEG each, cropped from the sample photo."""
    return crop_faces_as_jpeg(min_faces=6)


@pytest.fixture(scope="module")
def embeddings(face_jpegs) -> np.ndarray:
    """(6, 512) matrix of embeddings, one per identity."""
    vecs = []
    for i, jpeg in enumerate(face_jpegs):
        emb = face_service.compute_embedding(jpeg)
        assert emb is not None, f"no embedding produced for face crop {i}"
        vecs.append(emb)
    return np.stack(vecs)


@pytest.fixture(autouse=True)
def _reset_pipeline_state():
    """Cooldowns and the embedding cache are process state — reset per test."""
    face_service.reset_cooldowns()
    face_service.invalidate_embedding_cache()
    yield
    face_service.reset_cooldowns()
    face_service.invalidate_embedding_cache()


# ---------------------------------------------------------------------------
# Engine + embedding properties
# ---------------------------------------------------------------------------
def test_engine_is_insightface_not_fallback():
    """The whole point of B1: prove the real engine, not Haar, is in play."""
    assert face_service.insightface_available() is True
    assert face_service._get_insightface_app() is not None


def test_embedding_shape_dtype_and_normalization(embeddings):
    assert embeddings.shape == (6, 512), "buffalo_l must yield 512-d embeddings"
    assert embeddings.dtype == np.float32
    norms = np.linalg.norm(embeddings, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-3)


def test_embedding_is_deterministic(face_jpegs):
    """Same bytes in, same vector out — no nondeterminism in the ONNX path."""
    a = face_service.compute_embedding(face_jpegs[0])
    b = face_service.compute_embedding(face_jpegs[0])
    assert a is not None and b is not None
    np.testing.assert_allclose(a, b, atol=1e-5)


def test_no_face_image_yields_no_embedding():
    assert face_service.compute_embedding(not_a_face_jpeg()) is None


def test_corrupt_bytes_yield_no_embedding():
    """Malformed upload must return None, never raise."""
    assert face_service.compute_embedding(b"this is not an image at all") is None
    assert face_service.decode_image(b"\xff\xd8\xff\xe0garbage") is None


def test_detects_all_faces_in_group_photo():
    import cv2

    from ai_utils import group_photo_path

    img = cv2.imread(str(group_photo_path()))
    faces = face_service._get_insightface_app().get(img)
    assert len(faces) >= 6
    for f in faces:
        assert f.det_score > 0.5
        assert f.normed_embedding.shape == (512,)


# ---------------------------------------------------------------------------
# Accuracy: identity discrimination and threshold placement
# ---------------------------------------------------------------------------
def test_same_identity_scores_far_above_threshold(face_jpegs, embeddings):
    """Re-encoding a face and re-embedding it must still match itself.

    This is the false-reject direction: JPEG round-trip + re-detection is the
    exact transformation an enrollment photo undergoes in production.
    """
    for i, jpeg in enumerate(face_jpegs):
        again = face_service.compute_embedding(jpeg)
        score = face_service.cosine_similarity(again, embeddings[i])
        assert score > 0.95, f"identity {i} failed to match itself (score {score:.4f})"


def test_different_identities_score_far_below_threshold(embeddings):
    """False-accept direction: no cross-identity pair may reach the threshold."""
    sim = embeddings @ embeddings.T
    off_diagonal = sim[~np.eye(len(sim), dtype=bool)]
    worst = float(off_diagonal.max())
    assert worst < DEFAULT_THRESHOLD, (
        f"two different people scored {worst:.4f}, at or above the "
        f"{DEFAULT_THRESHOLD} threshold — false accept"
    )
    # Empirically ~0.23 on this fixture set; 0.35 leaves headroom for model
    # updates while still failing loudly if discrimination genuinely degrades.
    assert worst < 0.35, f"cross-identity similarity degraded to {worst:.4f}"


def test_threshold_separation_margin(face_jpegs, embeddings):
    """The configured threshold must sit inside the gap, with margin on both sides."""
    genuine = [
        face_service.cosine_similarity(face_service.compute_embedding(j), embeddings[i])
        for i, j in enumerate(face_jpegs)
    ]
    sim = embeddings @ embeddings.T
    impostor = sim[~np.eye(len(sim), dtype=bool)]

    worst_genuine, worst_impostor = float(min(genuine)), float(impostor.max())
    assert worst_genuine > DEFAULT_THRESHOLD, "FRR > 0 at the configured threshold"
    assert worst_impostor < DEFAULT_THRESHOLD, "FAR > 0 at the configured threshold"
    assert worst_genuine - worst_impostor > 0.4, (
        f"separation collapsed: genuine floor {worst_genuine:.4f} vs "
        f"impostor ceiling {worst_impostor:.4f}"
    )


def test_configured_threshold_is_the_one_under_test(client, db_session):
    """Guard: if the shipped default moves, these assertions must be revisited."""
    assert float(get_setting(db_session, "recognition_threshold", 0.45)) == pytest.approx(
        DEFAULT_THRESHOLD
    )


# ---------------------------------------------------------------------------
# Matching against enrolled users (real embeddings through the real cache)
# ---------------------------------------------------------------------------
def _enroll(db, username: str, embedding: np.ndarray):
    from app.core.security import hash_password
    from app.models.models import User

    user = User(
        name=username.title(),
        email=f"{username}@ai-test.local",
        username=username,
        password_hash=hash_password("irrelevant-pass-1"),
        role="receptionist",
        face_registered=True,
        face_embedding=embedding.astype(np.float32).tobytes(),
    )
    db.add(user)
    db.commit()
    face_service.invalidate_embedding_cache()
    return user


def test_match_enrolled_identity(client, db_session, face_jpegs, embeddings):
    user = _enroll(db_session, "ai_match_target", embeddings[0])
    try:
        probe = face_service.compute_embedding(face_jpegs[0])
        found, score = face_service._match_embedding(
            probe, db_session, threshold=DEFAULT_THRESHOLD
        )
        assert found is not None and found.id == user.id
        assert score > 0.95
    finally:
        db_session.delete(user)
        db_session.commit()
        face_service.invalidate_embedding_cache()


def test_impostor_is_rejected(client, db_session, face_jpegs, embeddings):
    """A different real person must not match the enrolled one."""
    user = _enroll(db_session, "ai_impostor_target", embeddings[0])
    try:
        probe = face_service.compute_embedding(face_jpegs[3])
        found, score = face_service._match_embedding(
            probe, db_session, threshold=DEFAULT_THRESHOLD
        )
        assert found is None, "a different person matched an enrolled identity"
        assert score < DEFAULT_THRESHOLD
    finally:
        db_session.delete(user)
        db_session.commit()
        face_service.invalidate_embedding_cache()


def test_correct_identity_chosen_among_many(client, db_session, face_jpegs, embeddings):
    """With all six enrolled, each probe must select its own identity."""
    users = [
        _enroll(db_session, f"ai_multi_{i}", embeddings[i]) for i in range(len(embeddings))
    ]
    try:
        for i, jpeg in enumerate(face_jpegs):
            probe = face_service.compute_embedding(jpeg)
            found, score = face_service._match_embedding(
                probe, db_session, threshold=DEFAULT_THRESHOLD
            )
            assert found is not None, f"probe {i} matched nobody"
            assert found.id == users[i].id, (
                f"probe {i} matched {found.username} instead of {users[i].username}"
            )
    finally:
        for u in users:
            db_session.delete(u)
        db_session.commit()
        face_service.invalidate_embedding_cache()


# ---------------------------------------------------------------------------
# Pipeline side effects
# ---------------------------------------------------------------------------
def test_recognized_face_writes_recognition_log(client, db_session, face_jpegs, embeddings):
    from app.models.models import RecognitionLog

    user = _enroll(db_session, "ai_logs_target", embeddings[1])
    try:
        before = db_session.query(RecognitionLog).filter(
            RecognitionLog.user_id == user.id
        ).count()
        results = face_service.process_frame(face_jpegs[1], db_session, camera="webcam")
        assert results, "pipeline returned no faces for a real face image"
        assert any(r["match"] is not None and r["match"].id == user.id for r in results)
        after = db_session.query(RecognitionLog).filter(
            RecognitionLog.user_id == user.id
        ).count()
        assert after == before + 1
    finally:
        db_session.delete(user)
        db_session.commit()
        face_service.invalidate_embedding_cache()


def test_unrecognized_face_creates_unknown_record(client, db_session, face_jpegs):
    """An unenrolled real face must produce an UnknownFace with an embedding."""
    from app.models.models import UnknownFace

    before = db_session.query(UnknownFace).count()
    results = face_service.process_frame(face_jpegs[4], db_session, camera="webcam")
    assert results
    assert all(r["match"] is None for r in results)

    rows = db_session.query(UnknownFace).order_by(UnknownFace.id.desc()).all()
    assert len(rows) == before + 1
    newest = rows[0]
    assert newest.unknown_person_id and newest.unknown_person_id.startswith("UNK-")
    assert newest.embeddings, "unknown sighting stored without its embedding"
    stored = np.frombuffer(newest.embeddings[0].embedding, dtype=np.float32)
    assert stored.shape == (512,)


def test_recognition_log_cooldown_suppresses_duplicates(
    client, db_session, face_jpegs, embeddings
):
    from app.models.models import RecognitionLog

    user = _enroll(db_session, "ai_cooldown_target", embeddings[2])
    try:
        face_service.process_frame(face_jpegs[2], db_session, camera="webcam")
        first = db_session.query(RecognitionLog).filter(
            RecognitionLog.user_id == user.id
        ).count()
        for _ in range(3):
            face_service.process_frame(face_jpegs[2], db_session, camera="webcam")
        second = db_session.query(RecognitionLog).filter(
            RecognitionLog.user_id == user.id
        ).count()
        assert second == first, "cooldown failed — live camera would flood the DB"
    finally:
        db_session.delete(user)
        db_session.commit()
        face_service.invalidate_embedding_cache()


# ---------------------------------------------------------------------------
# Liveness against genuine landmark data
# ---------------------------------------------------------------------------
def test_liveness_rejects_static_real_face():
    """A real face held perfectly still (i.e. a photo of one) must not pass."""
    import cv2

    from ai_utils import group_photo_path

    img = cv2.imread(str(group_photo_path()))
    face = max(
        face_service._get_insightface_app().get(img),
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
    )
    monitor = face_service.LivenessMonitor()
    verdict = None
    for _ in range(30):
        verdict = monitor.update(face)  # identical frame = static presentation
    assert verdict["passed"] is False
    assert verdict["blinks"] == 0


def test_real_landmarks_drive_eye_openness():
    """The eye-contour indices must actually locate eyes on a real detection."""
    import cv2

    from ai_utils import group_photo_path

    img = cv2.imread(str(group_photo_path()))
    faces = face_service._get_insightface_app().get(img)
    checked = 0
    for face in faces:
        lmk = getattr(face, "landmark_2d_106", None)
        if lmk is None:
            continue
        lmk = np.asarray(lmk, dtype=np.float32)
        for idx in (face_service._LEFT_EYE_IDX, face_service._RIGHT_EYE_IDX):
            openness = face_service._eye_openness(lmk, idx)
            # Open eyes are wider than tall but not degenerate.
            assert 0.05 < openness < 1.0, f"implausible eye openness {openness:.3f}"
        checked += 1
    assert checked >= 4, "no 106-point landmarks available on real detections"
