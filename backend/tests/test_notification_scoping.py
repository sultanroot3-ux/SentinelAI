"""Role-scoped delivery of notifications.

The watchlist alert was already written so its *content* names no one — camera
and severity only — because /api/notifications was readable by every
authenticated role. That bounded the leak but did not remove it: a receptionist
could still watch the feed and learn that someone on a watchlist had been seen,
on which camera, and at what severity. Correlated with who walked past a lobby
at that minute, "a watchlisted person was detected" identifies a person.

So delivery is restricted too. Notifications carry an optional audience: NULL
means everyone (every existing notification type keeps its behaviour), and a
set of roles means only those roles ever see the row.

The audit log is deliberately NOT filtered here. It is the forensic record,
already gated to admin/security_officer at its own endpoint, and must stay
complete regardless of who can see the operator-facing alert.
"""
import pytest

from app.models.models import AuditLog, Notification, User, Watchlist, WatchlistEntry
from app.services import face_service, notification_service
from app.services.settings_service import set_settings

WATCHLIST_TITLE = "Watchlist match"
SECURITY_ROLES = ("admin", "security_officer")


@pytest.fixture()
def _clean(client, db_session):
    _purge(db_session)
    yield
    _purge(db_session)


def _purge(db):
    db.query(Notification).delete()
    db.query(AuditLog).filter(AuditLog.action == "watchlist_match").delete()
    db.query(WatchlistEntry).delete()
    db.query(Watchlist).delete()
    db.query(User).filter(User.email.like("%@scope.test")).delete(
        synchronize_session=False
    )
    db.commit()
    face_service.invalidate_watchlist_cache()


def _titles(client, headers, **params):
    resp = client.get("/api/notifications", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return [n["title"] for n in resp.json()]


def _make_watchlist_alert(db):
    return notification_service.create_notification(
        db,
        title=WATCHLIST_TITLE,
        message="A watchlisted person was detected on camera 'lobby'.",
        level="alert",
        audience_roles=SECURITY_ROLES,
    )


# ---------------------------------------------------------------------------
# Delivery restriction
# ---------------------------------------------------------------------------
def test_receptionist_does_not_receive_watchlist_notifications(
    _clean, client, db_session, receptionist_headers
):
    _make_watchlist_alert(db_session)

    assert WATCHLIST_TITLE not in _titles(client, receptionist_headers)


def test_security_officer_receives_watchlist_notifications(
    _clean, client, db_session, officer_headers
):
    _make_watchlist_alert(db_session)

    assert WATCHLIST_TITLE in _titles(client, officer_headers)


def test_admin_receives_watchlist_notifications(
    _clean, client, db_session, admin_headers
):
    _make_watchlist_alert(db_session)

    assert WATCHLIST_TITLE in _titles(client, admin_headers)


def test_unscoped_notifications_stay_visible_to_everyone(
    _clean, client, db_session, receptionist_headers
):
    """Every pre-existing notification type must be unaffected."""
    notification_service.create_notification(
        db_session,
        title="Unknown person detected",
        message="An unrecognized face was detected on camera 'lobby'.",
        level="alert",
    )

    assert "Unknown person detected" in _titles(client, receptionist_headers)


def test_restriction_holds_for_the_unread_only_filter(
    _clean, client, db_session, receptionist_headers
):
    """A filter must not become a way around the audience check."""
    _make_watchlist_alert(db_session)

    assert WATCHLIST_TITLE not in _titles(client, receptionist_headers, unread_only=True)


# ---------------------------------------------------------------------------
# The mark-read endpoints must not become an oracle
# ---------------------------------------------------------------------------
def test_receptionist_cannot_mark_a_restricted_notification_read(
    _clean, client, db_session, receptionist_headers
):
    """404, not 403: confirming the row exists is itself the disclosure."""
    n = _make_watchlist_alert(db_session)

    resp = client.put(f"/api/notifications/{n.id}/read", headers=receptionist_headers)

    assert resp.status_code == 404
    db_session.expire_all()
    assert db_session.get(Notification, n.id).read is False


def test_security_officer_can_mark_a_watchlist_notification_read(
    _clean, client, db_session, officer_headers
):
    n = _make_watchlist_alert(db_session)

    resp = client.put(f"/api/notifications/{n.id}/read", headers=officer_headers)

    assert resp.status_code == 200
    db_session.expire_all()
    assert db_session.get(Notification, n.id).read is True


def test_read_all_by_a_receptionist_leaves_restricted_alerts_unread(
    _clean, client, db_session, receptionist_headers
):
    """Otherwise a receptionist silently clears alerts they cannot see."""
    n = _make_watchlist_alert(db_session)
    visible = notification_service.create_notification(
        db_session, title="Unknown person detected", message="m", level="alert"
    )

    resp = client.put("/api/notifications/read-all", headers=receptionist_headers)

    assert resp.status_code == 200
    db_session.expire_all()
    assert db_session.get(Notification, n.id).read is False, (
        "a restricted alert was cleared by someone who cannot see it"
    )
    assert db_session.get(Notification, visible.id).read is True


# ---------------------------------------------------------------------------
# The audit log must stay complete
# ---------------------------------------------------------------------------
def test_audit_log_is_never_filtered_by_audience(
    _clean, client, db_session, admin_headers, faces_available
):
    """Scoping delivery must not touch the forensic record."""
    from app.services.audit_service import write_audit

    write_audit(db_session, action="watchlist_match", detail="full detail retained")

    rows = db_session.query(AuditLog).filter(
        AuditLog.action == "watchlist_match").all()
    assert len(rows) == 1
    assert rows[0].detail == "full detail retained"

    resp = client.get(
        "/api/audit", headers=admin_headers, params={"action": "watchlist_match"}
    )
    assert resp.status_code == 200
    body = resp.json()  # PaginatedAudit: {items, total, page}
    assert body["total"] == 1
    assert any(r["detail"] == "full detail retained" for r in body["items"])


def test_audit_row_has_no_audience_concept(_clean, db_session):
    """AuditLog must not grow an audience column — it is not deliverable."""
    assert not hasattr(AuditLog, "audience_roles"), (
        "the forensic record must never be scoped"
    )


# ---------------------------------------------------------------------------
# End to end through the pipeline
# ---------------------------------------------------------------------------
def test_pipeline_watchlist_alert_is_scoped_but_audited(
    _clean, client, db_session, receptionist_headers, officer_headers, faces_available
):
    """The real path: a watchlist hit alerts security only, and is audited."""
    from app.models.models import Camera, FaceEmbedding

    set_settings(db_session, {"liveness_enabled": False})
    try:
        jpeg = faces_available[0]
        emb = face_service.compute_embedding(jpeg)
        assert emb is not None
        user = User(
            name="Scope Target", email="scope_target@scope.test",
            username="scope_target", password_hash="x", role="receptionist",
            face_registered=True, face_embedding=emb.tobytes(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.add(FaceEmbedding(user_id=user.id, embedding=emb.tobytes()))
        if db_session.query(Camera).filter(Camera.name == "scope-cam").first() is None:
            db_session.add(Camera(name="scope-cam", source="0", active=True))
        wl = Watchlist(name="Scope POI", level="alert", active=True)
        db_session.add(wl)
        db_session.commit()
        db_session.add(
            WatchlistEntry(watchlist_id=wl.id, user_id=user.id, reason="SCOPE-REASON")
        )
        db_session.commit()
        face_service.invalidate_embedding_cache()
        face_service.invalidate_watchlist_cache()
        face_service.reset_cooldowns()

        face_service.process_image(
            face_service.decode_image(jpeg), db_session, camera="scope-cam"
        )

        assert WATCHLIST_TITLE not in _titles(client, receptionist_headers)
        assert WATCHLIST_TITLE in _titles(client, officer_headers)

        audit = db_session.query(AuditLog).filter(
            AuditLog.action == "watchlist_match").all()
        assert len(audit) == 1, "the match must be audited exactly once"
        assert "SCOPE-REASON" in (audit[0].detail or ""), (
            "the audit record must keep the full detail"
        )
    finally:
        set_settings(db_session, {"liveness_enabled": True})


@pytest.fixture(scope="module")
def faces_available():
    from ai_utils import crop_faces_as_jpeg, require_ai

    require_ai()
    return crop_faces_as_jpeg(min_faces=6)
