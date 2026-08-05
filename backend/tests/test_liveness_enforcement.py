"""Liveness enforcement in the recognition pipeline.

Two defects this suite pins, which together meant anti-spoofing did nothing:

1. `liveness_enabled` defaulted to False, so enforcement was off unless an
   admin found and flipped it.
2. `check_liveness()` — the single-frame path used by /api/recognition/frame
   and by every non-dominant face in a stream — returned `{"passed": True}`
   unconditionally. Enforcement therefore passed anything that went through it
   even when switched on.

You cannot establish liveness from one static image without a dedicated
presentation-attack-detection model. The honest verdict for a single frame is
"unknown", and with enforcement on, unknown must not be treated as proven —
otherwise holding a photo to the camera is a recognized identity, and now also
a watchlist alert.
"""
import pytest

from app.models.models import (
    FaceEmbedding,
    Notification,
    RecognitionLog,
    UnknownFace,
    User,
    Watchlist,
    WatchlistEntry,
)
from app.services import face_service
from app.services.settings_service import DEFAULT_SETTINGS, set_settings

from ai_utils import crop_faces_as_jpeg, require_ai

pytestmark = pytest.mark.usefixtures("_liveness_env")

TEST_EMAIL_SUFFIX = "@live.test"


@pytest.fixture(scope="module", autouse=True)
def _ai_required():
    require_ai()
    face_service._get_insightface_app()


@pytest.fixture()
def _liveness_env(client, db_session):
    _reset(db_session)
    set_settings(db_session, {"liveness_enabled": True})
    yield
    _reset(db_session)
    set_settings(db_session, {"liveness_enabled": True})


def _reset(db):
    face_service.reset_cooldowns()
    face_service.invalidate_embedding_cache()
    face_service.invalidate_watchlist_cache()
    db.query(WatchlistEntry).delete()
    db.query(Watchlist).delete()
    db.query(Notification).delete()
    ids = [u.id for u in db.query(User).filter(User.email.like(f"%{TEST_EMAIL_SUFFIX}")).all()]
    unknown_ids = [u.id for u in db.query(UnknownFace).filter(UnknownFace.camera == "live-cam").all()]
    for model, col, vals in (
        (FaceEmbedding, FaceEmbedding.user_id, ids),
        (RecognitionLog, RecognitionLog.user_id, ids),
        (FaceEmbedding, FaceEmbedding.unknown_face_id, unknown_ids),
    ):
        if vals:
            db.query(model).filter(col.in_(vals)).delete(synchronize_session=False)
    if unknown_ids:
        db.query(UnknownFace).filter(UnknownFace.id.in_(unknown_ids)).delete(
            synchronize_session=False)
    if ids:
        db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    face_service.invalidate_embedding_cache()


@pytest.fixture(scope="module")
def faces() -> list[bytes]:
    return crop_faces_as_jpeg(min_faces=6)


def _enroll(db, jpeg, username) -> User:
    emb = face_service.compute_embedding(jpeg)
    assert emb is not None
    u = User(name=f"L {username}", email=f"{username}{TEST_EMAIL_SUFFIX}",
             username=username, password_hash="x", role="receptionist",
             face_registered=True, face_embedding=emb.tobytes())
    db.add(u)
    db.commit()
    db.add(FaceEmbedding(user_id=u.id, embedding=emb.tobytes()))
    db.commit()
    face_service.invalidate_embedding_cache()
    return u


def _decode(jpeg):
    return face_service.decode_image(jpeg)


class _VerifiedMonitor:
    """Stands in for a LivenessMonitor that HAS observed a live face."""

    def update(self, face) -> dict:
        return {"passed": True, "method": "blink+motion+pose", "blinks": 2}


# ---------------------------------------------------------------------------
# Defaults and the single-frame verdict
# ---------------------------------------------------------------------------
def test_liveness_is_enabled_by_default():
    assert DEFAULT_SETTINGS["liveness_enabled"] is True, (
        "anti-spoofing that ships off stays off"
    )


def test_single_frame_check_does_not_claim_liveness():
    """One static image cannot prove liveness, so it must not report passed."""
    verdict = face_service.check_liveness(None, [0, 0, 10, 10])
    assert verdict["passed"] is not True, (
        "a single frame reported liveness it cannot possibly have established"
    )
    assert verdict["passed"] is None, "unproven should be None (unknown), not False"
    assert "single-frame" in verdict["method"]


# ---------------------------------------------------------------------------
# A static image must not be recognized when enforcement is on
# ---------------------------------------------------------------------------
def test_static_image_is_not_recognized_when_liveness_enabled(db_session, faces):
    user = _enroll(db_session, faces[0], "live_recog")

    results = face_service.process_image(_decode(faces[0]), db_session, camera="live-cam")

    assert results, "the face should still be DETECTED"
    assert all(r["match"] is None for r in results), (
        "a static image was accepted as a live identity"
    )
    assert any("spoof" in (r.get("note") or "").lower() for r in results)
    assert db_session.query(RecognitionLog).filter(
        RecognitionLog.user_id == user.id).count() == 0


def test_static_image_creates_no_unknown_record_when_liveness_enabled(db_session, faces):
    """A suspected spoof must not be filed as a genuine unknown sighting."""
    before = db_session.query(UnknownFace).filter(UnknownFace.camera == "live-cam").count()

    face_service.process_image(_decode(faces[3]), db_session, camera="live-cam")

    after = db_session.query(UnknownFace).filter(UnknownFace.camera == "live-cam").count()
    assert after == before


def test_static_image_cannot_trigger_watchlist_alert_when_liveness_enabled(db_session, faces):
    """The headline case: a photo of a watchlisted person must not alert."""
    user = _enroll(db_session, faces[1], "live_watch")
    wl = Watchlist(name="Liveness POI", level="alert", active=True)
    db_session.add(wl)
    db_session.commit()
    db_session.add(WatchlistEntry(watchlist_id=wl.id, user_id=user.id, reason="test"))
    db_session.commit()
    face_service.invalidate_watchlist_cache()

    face_service.process_image(_decode(faces[1]), db_session, camera="live-cam")

    alerts = db_session.query(Notification).filter(
        Notification.title == "Watchlist match").all()
    assert alerts == [], (
        "holding a photo to the camera raised a watchlist alert"
    )


def test_static_unknown_face_cannot_trigger_watchlist_reid_when_liveness_enabled(
    db_session, faces
):
    """Same guarantee on the unknown re-identification path."""
    emb = face_service.compute_embedding(faces[5])
    assert emb is not None
    uf = UnknownFace(camera="live-cam", status="new")
    db_session.add(uf)
    db_session.flush()
    db_session.add(FaceEmbedding(unknown_face_id=uf.id, embedding=emb.tobytes()))
    wl = Watchlist(name="Liveness Unknown POI", level="alert", active=True)
    db_session.add(wl)
    db_session.commit()
    db_session.add(WatchlistEntry(watchlist_id=wl.id, unknown_face_id=uf.id, reason="t"))
    db_session.commit()
    face_service.invalidate_watchlist_cache()

    face_service.process_image(_decode(faces[5]), db_session, camera="live-cam")

    assert db_session.query(Notification).filter(
        Notification.title == "Watchlist match").all() == []


# ---------------------------------------------------------------------------
# Enforcement must not break the paths that CAN establish liveness
# ---------------------------------------------------------------------------
def test_temporally_verified_face_is_recognized_when_liveness_enabled(db_session, faces):
    """A face a monitor has verified must still be recognized and alert."""
    user = _enroll(db_session, faces[2], "live_ok")
    wl = Watchlist(name="Verified POI", level="alert", active=True)
    db_session.add(wl)
    db_session.commit()
    db_session.add(WatchlistEntry(watchlist_id=wl.id, user_id=user.id, reason="t"))
    db_session.commit()
    face_service.invalidate_watchlist_cache()

    results = face_service.process_image(
        _decode(faces[2]), db_session, camera="live-cam",
        liveness_monitor=_VerifiedMonitor(),
    )

    assert any(r["match"] is not None and r["match"].id == user.id for r in results), (
        "enforcement blocked a face that liveness had actually verified"
    )
    assert db_session.query(Notification).filter(
        Notification.title == "Watchlist match").count() == 1


def test_recognition_still_works_when_liveness_disabled(db_session, faces):
    """Turning enforcement off must restore the previous behaviour exactly."""
    user = _enroll(db_session, faces[4], "live_off")
    set_settings(db_session, {"liveness_enabled": False})
    try:
        results = face_service.process_image(
            _decode(faces[4]), db_session, camera="live-cam")
        assert any(r["match"] is not None and r["match"].id == user.id for r in results)
        assert db_session.query(RecognitionLog).filter(
            RecognitionLog.user_id == user.id).count() == 1
    finally:
        set_settings(db_session, {"liveness_enabled": True})


def test_collecting_frames_is_not_treated_as_verified(db_session, faces):
    """A monitor still warming up reports None; that must not pass as live."""
    user = _enroll(db_session, faces[0], "live_warmup")

    class _Warming:
        def update(self, face):
            return {"passed": None, "method": "blink+motion+pose",
                    "note": "collecting frames"}

    results = face_service.process_image(
        _decode(faces[0]), db_session, camera="live-cam",
        liveness_monitor=_Warming(),
    )
    assert all(r["match"] is None for r in results), (
        "a warming-up monitor was treated as proof of liveness"
    )
    assert db_session.query(RecognitionLog).filter(
        RecognitionLog.user_id == user.id).count() == 0
