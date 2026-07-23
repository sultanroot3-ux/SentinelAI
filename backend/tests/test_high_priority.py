"""Tests for the HIGH-priority production requirements (H1, H2).

H1 — biometric retention purge (respecting case/watchlist protection + audit)
H2 — short-lived stream tokens; access tokens rejected on the stream endpoint
"""
from datetime import datetime, timedelta

from app.db.database import SessionLocal
from app.models.models import AuditLog, Case, UnknownFace, Watchlist, WatchlistEntry
from app.services import retention_service
from app.services.settings_service import set_settings


# ---------------------------------------------------------------------------
# H1 — retention
# ---------------------------------------------------------------------------
class TestRetention:
    def _mk_unknown(self, db, days_old, upid):
        uf = UnknownFace(
            unknown_person_id=upid,
            camera="webcam",
            status="new",
            timestamp=datetime.utcnow() - timedelta(days=days_old),
        )
        db.add(uf)
        db.commit()
        db.refresh(uf)
        return uf

    def test_disabled_by_default(self, client):
        db = SessionLocal()
        try:
            set_settings(db, {"unknown_retention_days": 0})
            self._mk_unknown(db, 999, "UNK-RET-DISABLED")
            assert retention_service.purge_expired_unknowns(db) == 0
        finally:
            db.close()

    def test_purges_only_expired(self, client):
        db = SessionLocal()
        try:
            set_settings(db, {"unknown_retention_days": 30})
            old = self._mk_unknown(db, 60, "UNK-RET-OLD")
            fresh = self._mk_unknown(db, 5, "UNK-RET-FRESH")
            old_id, fresh_id = old.id, fresh.id

            purged = retention_service.purge_expired_unknowns(db)
            assert purged >= 1
            assert db.get(UnknownFace, old_id) is None       # expired -> gone
            assert db.get(UnknownFace, fresh_id) is not None  # within window
        finally:
            db.close()

    def test_case_linked_never_purged(self, client):
        db = SessionLocal()
        try:
            set_settings(db, {"unknown_retention_days": 1})
            uf = self._mk_unknown(db, 400, "UNK-RET-CASE")
            case = Case(case_number="RET-CASE-1", unknown_face_id=uf.id)
            db.add(case)
            db.commit()
            uf_id = uf.id

            retention_service.purge_expired_unknowns(db)
            assert db.get(UnknownFace, uf_id) is not None  # protected as evidence
        finally:
            db.close()

    def test_watchlisted_never_purged(self, client):
        db = SessionLocal()
        try:
            set_settings(db, {"unknown_retention_days": 1})
            uf = self._mk_unknown(db, 400, "UNK-RET-WL")
            wl = Watchlist(name="ret-test-wl", level="alert")
            db.add(wl)
            db.flush()
            db.add(WatchlistEntry(watchlist_id=wl.id, unknown_face_id=uf.id))
            db.commit()
            uf_id = uf.id

            retention_service.purge_expired_unknowns(db)
            assert db.get(UnknownFace, uf_id) is not None  # protected by watchlist
        finally:
            db.close()

    def test_purge_is_audited(self, client):
        db = SessionLocal()
        try:
            set_settings(db, {"unknown_retention_days": 10})
            self._mk_unknown(db, 90, "UNK-RET-AUDIT")
            before = db.query(AuditLog).filter(
                AuditLog.action == "retention_purge"
            ).count()
            retention_service.purge_expired_unknowns(db)
            after = db.query(AuditLog).filter(
                AuditLog.action == "retention_purge"
            ).count()
            assert after == before + 1
        finally:
            set_settings(db, {"unknown_retention_days": 0})
            db.close()

    def test_settings_validation(self, client, admin_headers):
        bad = client.put("/api/settings", headers=admin_headers,
                         json={"unknown_retention_days": -5})
        assert bad.status_code == 422
        ok = client.put("/api/settings", headers=admin_headers,
                        json={"unknown_retention_days": 30})
        assert ok.status_code == 200
        assert ok.json()["unknown_retention_days"] == 30
        # reset
        client.put("/api/settings", headers=admin_headers,
                   json={"unknown_retention_days": 0})


# ---------------------------------------------------------------------------
# H2 — stream tokens
# ---------------------------------------------------------------------------
class TestStreamTokens:
    def test_issue_requires_auth(self, client):
        assert client.post("/api/camera/stream-token").status_code == 401

    def test_issue_returns_short_lived_token(self, client, admin_headers):
        resp = client.post("/api/camera/stream-token", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["expires_in"] <= 60
        assert body["stream_token"]

    def test_access_token_rejected_on_stream(self, client, admin_token):
        # The API access token must NOT authenticate the stream (it would end
        # up in web-server logs as a reusable credential).
        resp = client.get(f"/api/camera/stream?token={admin_token}")
        assert resp.status_code == 401

    def test_stream_token_rejected_on_api(self, client, admin_headers):
        stream_token = client.post(
            "/api/camera/stream-token", headers=admin_headers
        ).json()["stream_token"]
        # A stream token must NOT grant API access.
        resp = client.get(
            "/api/users", headers={"Authorization": f"Bearer {stream_token}"}
        )
        assert resp.status_code == 401

    def test_stream_token_accepted_on_stream(self, client, admin_headers):
        import app.services.camera_service as cam_svc

        stream_token = client.post(
            "/api/camera/stream-token", headers=admin_headers
        ).json()["stream_token"]
        # Auth passes; camera hardware is absent in CI so a 503 (not 401) proves
        # the token was accepted and we reached the camera-availability check.
        orig = cam_svc.camera_available
        cam_svc.camera_available = lambda source="0": False
        try:
            resp = client.get(f"/api/camera/stream?token={stream_token}")
            assert resp.status_code == 503
        finally:
            cam_svc.camera_available = orig

    def test_expired_stream_token_rejected(self, client):
        import time

        from app.core import security
        from app.db.database import SessionLocal
        from app.models.models import User

        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").first()
            orig = security.STREAM_TOKEN_EXPIRE_SECONDS
            security.STREAM_TOKEN_EXPIRE_SECONDS = 1
            token = security.create_stream_token(admin)
            security.STREAM_TOKEN_EXPIRE_SECONDS = orig
        finally:
            db.close()
        time.sleep(2)
        resp = client.get(f"/api/camera/stream?token={token}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Final-audit fixes (v1.0.4)
# ---------------------------------------------------------------------------
class TestAuditReviewFixes:
    def test_oversized_upload_rejected(self, client, admin_headers):
        # 11 MB payload exceeds the 10 MB cap -> 413, not an OOM/500
        big = b"\xff" * (11 * 1024 * 1024)
        resp = client.post(
            "/api/recognition/frame",
            headers=admin_headers,
            files={"file": ("big.jpg", big, "image/jpeg")},
        )
        assert resp.status_code == 413

    def test_login_runs_verify_for_unknown_user(self, client):
        # Unknown username still returns the generic 401 (timing-equalized path)
        resp = client.post(
            "/api/auth/login",
            json={"username": "no-such-user-xyz", "password": "whatever12"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"

    def test_unknown_delete_is_audited(self, client, admin_headers):
        from app.db.database import SessionLocal
        from app.models.models import AuditLog, UnknownFace

        db = SessionLocal()
        try:
            uf = UnknownFace(unknown_person_id="UNK-AUDIT-DEL", camera="webcam", status="new")
            db.add(uf)
            db.commit()
            uf_id = uf.id
        finally:
            db.close()
        resp = client.delete(f"/api/unknown/{uf_id}", headers=admin_headers)
        assert resp.status_code == 200
        db = SessionLocal()
        try:
            assert db.query(AuditLog).filter(
                AuditLog.action == "unknown_delete"
            ).count() >= 1
        finally:
            db.close()

    def test_over_length_field_rejected_as_422(self, client, admin_headers):
        # Schema max_length turns a would-be Postgres DataError (500) into 422
        resp = client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "name": "x" * 300,
                "email": "toolong@example.com",
                "username": "toolonguser",
                "password": "valid-pass-123",
            },
        )
        assert resp.status_code == 422
