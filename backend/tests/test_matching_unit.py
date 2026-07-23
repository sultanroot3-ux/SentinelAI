"""Unit tests: vectorized embedding matching + cache invalidation.

Works without insightface: embeddings are plain float32 vectors.
"""
import numpy as np

from app.core.security import hash_password
from app.models.models import User
from app.services import face_service


def _make_user(db, username: str, embedding: np.ndarray) -> User:
    user = User(
        name=username.title(),
        email=f"{username}@example.com",
        username=username,
        password_hash=hash_password("irrelevant-1"),
        role="receptionist",
        face_registered=True,
        face_embedding=embedding.astype(np.float32).tobytes(),
    )
    db.add(user)
    db.commit()
    face_service.invalidate_embedding_cache()
    return user


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_match_above_threshold(client, db_session):
    target = _unit(np.arange(1, 513))
    user = _make_user(db_session, "matchme", target)
    found, score = face_service._match_embedding(target, db_session, threshold=0.45)
    assert found is not None and found.id == user.id
    assert score > 0.99


def test_no_match_below_threshold(client, db_session):
    _make_user(db_session, "somebody", _unit(np.arange(1, 513)))
    rng = np.random.default_rng(7)
    stranger = _unit(rng.normal(size=512))
    found, score = face_service._match_embedding(stranger, db_session, threshold=0.45)
    assert found is None
    assert score < 0.45


def test_cache_invalidation_on_delete(client, db_session):
    target = _unit(np.linspace(0.5, 2.0, 512))
    user = _make_user(db_session, "temporary", target)
    found, _ = face_service._match_embedding(target, db_session, threshold=0.45)
    assert found is not None

    db_session.delete(user)
    db_session.commit()
    face_service.invalidate_embedding_cache()

    found, _ = face_service._match_embedding(target, db_session, threshold=0.45)
    assert found is None or found.username != "temporary"


def test_dimension_mismatch_returns_no_match(client, db_session):
    _make_user(db_session, "dimuser", _unit(np.ones(512)))
    found, score = face_service._match_embedding(
        _unit(np.ones(128)), db_session, threshold=0.45
    )
    assert found is None
    assert score == -1.0


def test_cosine_similarity_bounds():
    a = _unit([1, 0, 0])
    assert abs(face_service.cosine_similarity(a, a) - 1.0) < 1e-6
    assert abs(face_service.cosine_similarity(a, _unit([0, 1, 0]))) < 1e-6
    assert face_service.cosine_similarity(a, np.zeros(3, dtype=np.float32)) == 0.0


def test_cross_worker_cache_revalidates_on_db_change(client, db_session=None):
    """Simulates a second worker: cache marked valid, another process enrolls
    (DB write + FaceEmbedding row) WITHOUT calling invalidate_embedding_cache.
    The version signature must trigger a rebuild on the next lookup."""
    from app.db.database import SessionLocal
    from app.models.models import FaceEmbedding

    db = SessionLocal()
    try:
        emb_a = _unit(np.r_[1.0, np.zeros(511)])
        user_a = _make_user(db, "worker_cache_a", emb_a)
        db.add(FaceEmbedding(user_id=user_a.id, embedding=emb_a.tobytes()))
        db.commit()

        # Worker 1 populates its cache
        match, score = face_service._match_embedding(emb_a, db, threshold=0.9)
        assert match is not None and match.id == user_a.id

        # "Worker 2" enrolls a new user — no local invalidate call (that call
        # happened in the other process). Only the DB changes.
        emb_b = _unit(np.r_[0.0, 1.0, np.zeros(510)])
        user_b = User(
            name="Worker Cache B",
            email="worker_cache_b@example.com",
            username="worker_cache_b",
            password_hash=hash_password("irrelevant-1"),
            role="receptionist",
            face_registered=True,
            face_embedding=emb_b.astype(np.float32).tobytes(),
        )
        db.add(user_b)
        db.flush()
        db.add(FaceEmbedding(user_id=user_b.id, embedding=emb_b.tobytes()))
        db.commit()

        # This worker's cache is still flagged valid — but the signature
        # changed, so the new user must be matched immediately.
        match_b, score_b = face_service._match_embedding(emb_b, db, threshold=0.9)
        assert match_b is not None and match_b.id == user_b.id, (
            "stale cross-worker cache: new enrollment not visible"
        )
    finally:
        db.close()
