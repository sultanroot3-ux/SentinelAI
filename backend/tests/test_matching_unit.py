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
