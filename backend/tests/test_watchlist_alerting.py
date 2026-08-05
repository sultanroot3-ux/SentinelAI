"""Watchlist alerting in the LIVE recognition pipeline.

Before this suite existed, watchlists were storage-only: `Watchlist` /
`WatchlistEntry` had full CRUD and a UI, `investigation_service` surfaced hits
in on-demand reports, and `retention_service` exempted watchlisted records from
purge — but `face_service.process_image()`, the function every camera frame and
every /api/recognition/frame call goes through, never consulted them.

The operational consequence: a person on an "alert"-level watchlist could walk
past a camera and the system logged a routine recognition and stayed silent.

These tests pin the wiring, and equally importantly pin what must NOT happen:
the identity and the reason a person is watchlisted must never reach the
in-app notification feed, which every authenticated role can read.
"""
import pytest

from app.models.models import (
    AccessHistory,
    AuditLog,
    Camera,
    FaceEmbedding,
    Notification,
    RecognitionLog,
    UnknownFace,
    User,
    Watchlist,
    WatchlistEntry,
)
from app.services import face_service
from app.services.settings_service import set_settings

from ai_utils import crop_faces_as_jpeg, require_ai

pytestmark = pytest.mark.usefixtures("_watchlist_env")

WATCHLIST_TITLE = "Watchlist match"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _ai_required():
    require_ai()
    face_service._get_insightface_app()


@pytest.fixture()
def _watchlist_env(client, db_session):
    """Clean pipeline + watchlist state around every test.

    Depends on `client` so the app lifespan has created the schema — these
    tests drive the service layer directly rather than going through HTTP.
    """
    _register_cameras(db_session)
    _reset(db_session)
    yield
    _reset(db_session)


def _register_cameras(db):
    """The alert cooldown keys on the registered camera row, not the raw string."""
    for name in TEST_CAMERAS:
        if db.query(Camera).filter(Camera.name == name).first() is None:
            db.add(Camera(name=name, source="0", active=True))
    db.commit()


TEST_EMAIL_SUFFIX = "@wl.test"
TEST_CAMERAS = ("lobby", "garage", "roof")


def _reset(db):
    """Return the pipeline and the fixture rows to a known-empty state.

    Enrolled users MUST be removed between tests: every test enrolls from the
    same six fixture faces, so a user left behind by an earlier test is matched
    by a later one instead of that test's own user — which silently turns
    "alert fired" assertions into failures for the wrong reason.

    Deletions are scoped (test email suffix, test camera names, the
    watchlist_match audit action) so this fixture cannot disturb rows other
    test modules rely on.
    """
    face_service.reset_cooldowns()
    face_service.invalidate_embedding_cache()
    face_service.invalidate_watchlist_cache()

    db.query(WatchlistEntry).delete()
    db.query(Watchlist).delete()
    db.query(Notification).delete()
    db.query(AuditLog).filter(AuditLog.action == "watchlist_match").delete()

    user_ids = [
        u.id for u in db.query(User)
        .filter(User.email.like(f"%{TEST_EMAIL_SUFFIX}"))
        .all()
    ]
    unknown_ids = [
        u.id for u in db.query(UnknownFace)
        .filter(UnknownFace.camera.in_(TEST_CAMERAS))
        .all()
    ]
    # Bulk deletes bypass ORM cascades, so children go first explicitly.
    for model, column, ids in (
        (FaceEmbedding, FaceEmbedding.user_id, user_ids),
        (RecognitionLog, RecognitionLog.user_id, user_ids),
        (AccessHistory, AccessHistory.user_id, user_ids),
        (FaceEmbedding, FaceEmbedding.unknown_face_id, unknown_ids),
        (AccessHistory, AccessHistory.unknown_face_id, unknown_ids),
    ):
        if ids:
            db.query(model).filter(column.in_(ids)).delete(synchronize_session=False)
    if unknown_ids:
        db.query(UnknownFace).filter(UnknownFace.id.in_(unknown_ids)).delete(
            synchronize_session=False
        )
    if user_ids:
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.commit()
    face_service.invalidate_embedding_cache()


@pytest.fixture(scope="module")
def faces() -> list[bytes]:
    return crop_faces_as_jpeg(min_faces=6)


def _enroll(db, jpeg: bytes, username: str) -> User:
    """Create a user with a real face embedding registered."""
    emb = face_service.compute_embedding(jpeg)
    assert emb is not None
    user = User(
        name=f"Test {username}",
        email=f"{username}@wl.test",
        username=username,
        password_hash="x",
        role="receptionist",
        face_registered=True,
        face_embedding=emb.tobytes(),
    )
    db.add(user)
    db.commit()
    db.add(FaceEmbedding(user_id=user.id, embedding=emb.tobytes()))
    db.commit()
    face_service.invalidate_embedding_cache()
    return user


def _watchlist(db, level="alert", active=True, name="Persons of Interest") -> Watchlist:
    wl = Watchlist(name=name, level=level, active=active, description="test")
    db.add(wl)
    db.commit()
    face_service.invalidate_watchlist_cache()
    return wl


def _add_entry(db, wl, *, user_id=None, unknown_face_id=None, reason="TEST-REASON") -> None:
    db.add(
        WatchlistEntry(
            watchlist_id=wl.id,
            user_id=user_id,
            unknown_face_id=unknown_face_id,
            reason=reason,
        )
    )
    db.commit()
    face_service.invalidate_watchlist_cache()


def _alerts(db) -> list[Notification]:
    return db.query(Notification).filter(Notification.title == WATCHLIST_TITLE).all()


def _decode(jpeg: bytes):
    return face_service.decode_image(jpeg)


# ---------------------------------------------------------------------------
# Core wiring — the regression this suite exists for
# ---------------------------------------------------------------------------
def test_watchlisted_employee_triggers_alert_on_live_recognition(db_session, faces):
    """A watchlisted employee seen by a camera must raise an alert."""
    user = _enroll(db_session, faces[0], "wl_employee")
    wl = _watchlist(db_session, level="alert")
    _add_entry(db_session, wl, user_id=user.id)

    results = face_service.process_image(_decode(faces[0]), db_session, camera="lobby")

    assert any(r["match"] is not None and r["match"].id == user.id for r in results), (
        "the test face should have matched the enrolled user"
    )
    alerts = _alerts(db_session)
    assert len(alerts) == 1, "a watchlisted employee must produce exactly one alert"
    assert alerts[0].level == "alert"


def test_non_watchlisted_employee_produces_no_alert(db_session, faces):
    user = _enroll(db_session, faces[1], "wl_clean")
    _watchlist(db_session)  # a list exists, but this user is not on it

    face_service.process_image(_decode(faces[1]), db_session, camera="lobby")

    assert _alerts(db_session) == []
    assert db_session.get(User, user.id) is not None


def test_inactive_watchlist_does_not_alert(db_session, faces):
    user = _enroll(db_session, faces[2], "wl_inactive")
    wl = _watchlist(db_session, active=False)
    _add_entry(db_session, wl, user_id=user.id)

    face_service.process_image(_decode(faces[2]), db_session, camera="lobby")

    assert _alerts(db_session) == [], "an archived watchlist must not fire"


def test_watchlist_level_propagates_to_notification(db_session, faces):
    user = _enroll(db_session, faces[3], "wl_warning")
    wl = _watchlist(db_session, level="warning")
    _add_entry(db_session, wl, user_id=user.id)

    face_service.process_image(_decode(faces[3]), db_session, camera="lobby")

    alerts = _alerts(db_session)
    assert len(alerts) == 1
    assert alerts[0].level == "warning", "severity must come from the watchlist"


# ---------------------------------------------------------------------------
# Edge case: empty watchlist must not perturb the normal flow
# ---------------------------------------------------------------------------
def test_empty_watchlist_leaves_recognition_flow_unchanged(db_session, faces):
    """No watchlists at all: recognition results must be byte-identical."""
    user = _enroll(db_session, faces[0], "wl_empty_flow")

    baseline = face_service.process_image(_decode(faces[0]), db_session, camera="lobby")
    face_service.reset_cooldowns()
    face_service.invalidate_watchlist_cache()
    after = face_service.process_image(_decode(faces[0]), db_session, camera="lobby")

    assert _alerts(db_session) == []
    assert len(baseline) == len(after) == 1
    assert baseline[0]["box"] == after[0]["box"]
    assert baseline[0]["score"] == after[0]["score"]
    assert baseline[0]["match"].id == after[0]["match"].id == user.id
    # The result dicts must not have grown a watchlist key — see the leakage test.
    assert set(baseline[0]) == set(after[0])


def test_empty_watchlist_costs_no_query_per_face(db_session, faces):
    """With no watchlist rows the cached state must short-circuit."""
    _enroll(db_session, faces[1], "wl_empty_cost")
    face_service.process_image(_decode(faces[1]), db_session, camera="lobby")

    state = face_service._get_watchlist_state(db_session)
    assert state["users"] == {}
    assert state["unknown_matrix"] is None


# ---------------------------------------------------------------------------
# Edge case: DB failure must degrade, never crash the pipeline
# ---------------------------------------------------------------------------
def test_watchlist_db_failure_does_not_break_recognition(db_session, faces, monkeypatch, caplog):
    """A broken watchlist query must not take recognition down with it."""
    user = _enroll(db_session, faces[2], "wl_dbfail")

    def _boom(db):
        raise RuntimeError("watchlist table is on fire")

    monkeypatch.setattr(face_service, "_get_watchlist_state", _boom)

    results = face_service.process_image(_decode(faces[2]), db_session, camera="lobby")

    assert len(results) == 1, "recognition must still return its faces"
    assert results[0]["match"] is not None and results[0]["match"].id == user.id
    assert _alerts(db_session) == []


def test_watchlist_db_failure_is_logged(db_session, faces, monkeypatch, caplog):
    _enroll(db_session, faces[3], "wl_dbfail_log")

    def _boom(db):
        raise RuntimeError("watchlist table is on fire")

    monkeypatch.setattr(face_service, "_get_watchlist_state", _boom)

    with caplog.at_level("ERROR", logger="sentinelai.face"):
        face_service.process_image(_decode(faces[3]), db_session, camera="lobby")

    assert any("watchlist" in r.message.lower() for r in caplog.records), (
        "a swallowed watchlist failure must still be logged"
    )


# ---------------------------------------------------------------------------
# Edge case: cooldown across cameras
# ---------------------------------------------------------------------------
def test_repeat_sighting_same_camera_is_cooled_down(db_session, faces):
    user = _enroll(db_session, faces[0], "wl_cooldown_same")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)

    img = _decode(faces[0])
    face_service.process_image(img, db_session, camera="lobby")
    face_service.process_image(img, db_session, camera="lobby")
    face_service.process_image(img, db_session, camera="lobby")

    assert len(_alerts(db_session)) == 1, "same person + same camera must alert once"


def test_different_cameras_each_alert(db_session, faces):
    """Movement between cameras is security-relevant: each camera alerts.

    The recognition-log cooldown is keyed per user only, so a second camera's
    sighting writes no RecognitionLog. The watchlist cooldown must NOT inherit
    that key, or tracking a flagged person across a building would go silent.
    """
    user = _enroll(db_session, faces[1], "wl_cooldown_multi")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)

    img = _decode(faces[1])
    face_service.process_image(img, db_session, camera="lobby")
    face_service.process_image(img, db_session, camera="garage")
    face_service.process_image(img, db_session, camera="roof")

    alerts = _alerts(db_session)
    assert len(alerts) == 3, "each distinct camera must raise its own alert"
    cameras = {a.message for a in alerts}
    assert len(cameras) == 3, "each alert must name its own camera"


def test_watchlist_cooldown_is_independent_of_recognition_log_cooldown(db_session, faces):
    """A flagged person must alert even when the RecognitionLog is cooled down."""
    from app.models.models import RecognitionLog

    user = _enroll(db_session, faces[2], "wl_indep")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)

    img = _decode(faces[2])
    face_service.process_image(img, db_session, camera="lobby")
    logs_after_first = db_session.query(RecognitionLog).filter(
        RecognitionLog.user_id == user.id
    ).count()

    face_service.process_image(img, db_session, camera="garage")
    logs_after_second = db_session.query(RecognitionLog).filter(
        RecognitionLog.user_id == user.id
    ).count()

    assert logs_after_second == logs_after_first, (
        "precondition: the recognition-log cooldown suppresses the 2nd log"
    )
    assert len(_alerts(db_session)) == 2, (
        "the watchlist alert must fire anyway — it has its own cooldown key"
    )


# ---------------------------------------------------------------------------
# Edge case: recognition threshold must gate the alert
# ---------------------------------------------------------------------------
def test_below_threshold_face_does_not_alert_as_that_employee(db_session, faces):
    """A different person must not trigger a watchlisted employee's alert."""
    user = _enroll(db_session, faces[0], "wl_threshold")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)

    # A different identity from the same group photo
    results = face_service.process_image(_decode(faces[4]), db_session, camera="lobby")

    assert all(
        r["match"] is None or r["match"].id != user.id for r in results
    ), "precondition: face 4 must not match the user enrolled from face 0"
    assert _alerts(db_session) == [], (
        "a sub-threshold face must never raise the watchlisted user's alert"
    )


def test_raising_threshold_above_self_match_suppresses_alert(db_session, faces):
    """The alert is gated by the CONFIGURED threshold, not a hardcoded one.

    The threshold is 1.01, not 0.999: these tests enroll and then re-present the
    identical image, so the embedding is bit-identical and cosine similarity is
    exactly 1.0. Anything <= 1.0 still matches and would make this test pass for
    the wrong reason.
    """
    user = _enroll(db_session, faces[1], "wl_threshold_hi")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)
    set_settings(db_session, {"recognition_threshold": 1.01})

    try:
        results = face_service.process_image(_decode(faces[1]), db_session, camera="lobby")
        assert all(r["match"] is None for r in results)
        assert _alerts(db_session) == []
    finally:
        set_settings(db_session, {"recognition_threshold": 0.45})


# ---------------------------------------------------------------------------
# Unknown persons of interest: embedding re-identification
# ---------------------------------------------------------------------------
def test_watchlisted_unknown_person_is_reidentified(db_session, faces):
    """A watchlisted unknown face must alert when that person reappears.

    Each sighting creates a NEW unknown_faces row, so an exact-id lookup can
    never match a later sighting — re-identification has to go through the
    embedding.
    """
    emb = face_service.compute_embedding(faces[5])
    assert emb is not None
    unknown = UnknownFace(camera="lobby", status="new")
    db_session.add(unknown)
    db_session.flush()
    unknown.unknown_person_id = f"UNK-{unknown.id:06d}"
    db_session.add(FaceEmbedding(unknown_face_id=unknown.id, embedding=emb.tobytes()))
    db_session.commit()

    wl = _watchlist(db_session, level="alert")
    _add_entry(db_session, wl, unknown_face_id=unknown.id)

    face_service.process_image(_decode(faces[5]), db_session, camera="lobby")

    assert len(_alerts(db_session)) == 1, (
        "a returning watchlisted unknown person must be re-identified and alert"
    )


def test_unwatchlisted_unknown_person_does_not_alert(db_session, faces):
    emb = face_service.compute_embedding(faces[4])
    assert emb is not None
    unknown = UnknownFace(camera="lobby", status="new")
    db_session.add(unknown)
    db_session.flush()
    db_session.add(FaceEmbedding(unknown_face_id=unknown.id, embedding=emb.tobytes()))
    db_session.commit()
    _watchlist(db_session)  # empty list

    face_service.process_image(_decode(faces[4]), db_session, camera="lobby")

    assert _alerts(db_session) == []


def test_different_unknown_person_does_not_match_watchlisted_one(db_session, faces):
    """Re-identification must respect the threshold, not alert on any face."""
    emb = face_service.compute_embedding(faces[5])
    assert emb is not None
    unknown = UnknownFace(camera="lobby", status="new")
    db_session.add(unknown)
    db_session.flush()
    db_session.add(FaceEmbedding(unknown_face_id=unknown.id, embedding=emb.tobytes()))
    db_session.commit()
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, unknown_face_id=unknown.id)

    # A different identity entirely
    face_service.process_image(_decode(faces[2]), db_session, camera="lobby")

    assert _alerts(db_session) == [], (
        "a different person must not trip the watchlisted unknown's alert"
    )


# ---------------------------------------------------------------------------
# Information leakage
# ---------------------------------------------------------------------------
def test_notification_does_not_leak_identity_or_reason(db_session, faces):
    """/api/notifications is readable by EVERY authenticated role.

    The in-app alert may say a watchlist matched and on which camera; it must
    not name the person or repeat why they are listed.
    """
    user = _enroll(db_session, faces[0], "wl_leak")
    wl = _watchlist(db_session, name="Terminated Staff")
    _add_entry(db_session, wl, user_id=user.id, reason="SECRET-REASON-XYZ")

    face_service.process_image(_decode(faces[0]), db_session, camera="lobby")

    alerts = _alerts(db_session)
    assert len(alerts) == 1
    blob = f"{alerts[0].title} {alerts[0].message}".lower()
    for secret in (user.name.lower(), user.username.lower(), "secret-reason-xyz",
                   "terminated staff"):
        assert secret not in blob, f"notification leaked {secret!r}: {blob!r}"
    assert "lobby" in blob, "the alert must still tell an operator which camera"


def test_full_detail_is_recorded_in_the_audit_log(db_session, faces):
    """The role-gated audit log is where identity and reason belong."""
    user = _enroll(db_session, faces[1], "wl_audit")
    wl = _watchlist(db_session, name="Terminated Staff")
    _add_entry(db_session, wl, user_id=user.id, reason="SECRET-REASON-XYZ")

    face_service.process_image(_decode(faces[1]), db_session, camera="lobby")

    entries = db_session.query(AuditLog).filter(
        AuditLog.action == "watchlist_match"
    ).all()
    assert len(entries) == 1, "a watchlist match must be audited"
    detail = entries[0].detail or ""
    assert user.username in detail
    assert "Terminated Staff" in detail
    assert "SECRET-REASON-XYZ" in detail


def test_recognition_result_dicts_carry_no_watchlist_data(db_session, faces):
    """process_image() results feed the API response and the video overlay."""
    user = _enroll(db_session, faces[2], "wl_nores")
    wl = _watchlist(db_session, name="Terminated Staff")
    _add_entry(db_session, wl, user_id=user.id, reason="SECRET-REASON-XYZ")

    results = face_service.process_image(_decode(faces[2]), db_session, camera="lobby")

    assert results
    for r in results:
        keys = set(r)
        assert "watchlist" not in keys and "watchlist_hits" not in keys
        blob = repr({k: v for k, v in r.items() if k != "match"}).lower()
        assert "secret-reason-xyz" not in blob
        assert "terminated staff" not in blob


# ---------------------------------------------------------------------------
# Operator control
# ---------------------------------------------------------------------------
def test_notify_on_watchlist_setting_disables_alerts(db_session, faces):
    user = _enroll(db_session, faces[3], "wl_setting")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)
    set_settings(db_session, {"notify_on_watchlist": False})

    try:
        face_service.process_image(_decode(faces[3]), db_session, camera="lobby")
        assert _alerts(db_session) == []
    finally:
        set_settings(db_session, {"notify_on_watchlist": True})


def test_audit_entry_written_even_when_notifications_disabled(db_session, faces):
    """Turning off the noisy channel must not turn off the forensic record."""
    user = _enroll(db_session, faces[4], "wl_setting_audit")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)
    set_settings(db_session, {"notify_on_watchlist": False})

    try:
        face_service.process_image(_decode(faces[4]), db_session, camera="lobby")
        entries = db_session.query(AuditLog).filter(
            AuditLog.action == "watchlist_match"
        ).all()
        assert len(entries) == 1
    finally:
        set_settings(db_session, {"notify_on_watchlist": True})


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------
def test_new_watchlist_entry_takes_effect_without_restart(db_session, faces):
    """A worker that did not handle the write must still see the new entry."""
    user = _enroll(db_session, faces[5], "wl_cache")
    face_service.process_image(_decode(faces[5]), db_session, camera="lobby")
    assert _alerts(db_session) == []

    wl = _watchlist(db_session)
    db_session.add(WatchlistEntry(watchlist_id=wl.id, user_id=user.id, reason="added late"))
    db_session.commit()
    # Deliberately NOT calling invalidate_watchlist_cache(): another worker
    # would not have. The DB signature must drive the rebuild.
    face_service.reset_cooldowns()

    face_service.process_image(_decode(faces[5]), db_session, camera="lobby")
    assert len(_alerts(db_session)) == 1, (
        "the watchlist cache must notice a cross-worker write via its signature"
    )


# ---------------------------------------------------------------------------
# Alert amplification via the client-supplied camera name
# ---------------------------------------------------------------------------
def test_unregistered_camera_names_share_one_cooldown_bucket(db_session, faces):
    """`camera` is a client-supplied query param on /api/recognition/frame.

    If the cooldown keyed on that raw string, any authenticated account could
    mint a fresh bucket per request and fan out unlimited email/Telegram/Discord
    alerts within the recognition quota (60 frames/min). Unregistered names must
    therefore collapse into a single bucket.
    """
    user = _enroll(db_session, faces[0], "wl_amplify")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)

    img = _decode(faces[0])
    for i in range(25):
        face_service.process_image(img, db_session, camera=f"spoofed-{i}")

    assert len(_alerts(db_session)) == 1, (
        "unregistered camera names must not each open a new cooldown window"
    )


def test_unregistered_camera_name_is_not_echoed_into_the_alert(db_session, faces):
    """The client-supplied string must not land in notification/email bodies."""
    user = _enroll(db_session, faces[1], "wl_echo")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)

    face_service.process_image(
        db=db_session, img=_decode(faces[1]), camera="<script>evil</script>"
    )

    alerts = _alerts(db_session)
    assert len(alerts) == 1
    assert "evil" not in alerts[0].message, "raw client input echoed into the alert"
    assert "unregistered" in alerts[0].message.lower()


def test_registered_camera_name_comes_from_the_database(db_session, faces):
    user = _enroll(db_session, faces[2], "wl_regcam")
    wl = _watchlist(db_session)
    _add_entry(db_session, wl, user_id=user.id)

    face_service.process_image(_decode(faces[2]), db_session, camera="lobby")

    alerts = _alerts(db_session)
    assert len(alerts) == 1
    assert "lobby" in alerts[0].message


# ---------------------------------------------------------------------------
# Driver parameter ceiling
# ---------------------------------------------------------------------------
def test_large_watchlist_does_not_hit_the_driver_parameter_ceiling(db_session, faces):
    """The embedding load must not bind one parameter per watchlisted id.

    SQLite caps bind parameters at 32766 and PostgreSQL at 65535. Loading the
    re-identification set with `.in_(ids)` blew that ceiling once a watchlist
    grew large enough — and because check_watchlist() swallows exceptions so a
    watchlist fault cannot stop recognition, the failure mode was watchlist
    alerting silently switching off across the whole deployment. Silent is the
    one way a security control must not fail.

    Reproduced by lowering SQLite's own limit rather than inserting 30k rows,
    so the regression is pinned in a second instead of a minute.
    """
    import sqlite3

    raw = getattr(
        db_session.connection().connection, "driver_connection",
        db_session.connection().connection,
    )
    if not isinstance(raw, sqlite3.Connection):
        pytest.skip("parameter-ceiling reproduction is SQLite-specific")

    emb = face_service.compute_embedding(faces[5])
    assert emb is not None
    wl = _watchlist(db_session, level="alert")
    for _ in range(30):
        uf = UnknownFace(camera="lobby", status="new")
        db_session.add(uf)
        db_session.flush()
        db_session.add(FaceEmbedding(unknown_face_id=uf.id, embedding=emb.tobytes()))
        db_session.add(
            WatchlistEntry(watchlist_id=wl.id, unknown_face_id=uf.id, reason="bulk")
        )
    db_session.commit()
    face_service.invalidate_watchlist_cache()

    old = raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 20)
    try:
        # 30 watchlisted ids against a 20-parameter ceiling: an .in_() load
        # raises here, a join does not.
        state = face_service._get_watchlist_state(db_session)
        assert state["unknown_matrix"] is not None, (
            "the re-identification set failed to load within the parameter limit"
        )
        assert state["unknown_matrix"].shape[0] == 30
        face_service.process_image(_decode(faces[5]), db_session, camera="lobby")
    finally:
        raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, old)

    assert len(_alerts(db_session)) == 1, (
        "a watchlisted person must still alert on a watchlist larger than the "
        "driver's bind-parameter ceiling"
    )
