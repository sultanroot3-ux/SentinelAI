"""Tests for the Enterprise Investigation System.

Covers: RBAC catalogue, cameras + locations, watchlists, visitors +
check-in/out, access history, and the investigation endpoints' contract
(auth, validation, DB-only data policy). Heavy model inference is not
exercised here — the analyze endpoint is tested up to image validation.
"""


# ---------------------------------------------------------------------------
# RBAC catalogue
# ---------------------------------------------------------------------------
class TestRBACCatalogue:
    def test_roles_seeded_with_permissions(self, client, admin_headers):
        resp = client.get("/api/rbac/roles", headers=admin_headers)
        assert resp.status_code == 200
        roles = {r["name"]: r for r in resp.json()}
        assert {"admin", "security_officer", "receptionist", "it"} <= set(roles)
        admin_codes = {p["code"] for p in roles["admin"]["permissions"]}
        assert "investigation.run" in admin_codes
        assert "watchlists.manage" in admin_codes
        # receptionist must NOT hold investigation rights
        rec_codes = {p["code"] for p in roles["receptionist"]["permissions"]}
        assert "investigation.run" not in rec_codes

    def test_permissions_listed(self, client, admin_headers):
        resp = client.get("/api/rbac/permissions", headers=admin_headers)
        assert resp.status_code == 200
        codes = {p["code"] for p in resp.json()}
        assert "cameras.manage" in codes

    def test_requires_auth(self, client):
        assert client.get("/api/rbac/roles").status_code == 401


# ---------------------------------------------------------------------------
# Cameras + locations
# ---------------------------------------------------------------------------
class TestCameras:
    def test_default_webcam_seeded(self, client, admin_headers):
        resp = client.get("/api/cameras", headers=admin_headers)
        assert resp.status_code == 200
        cams = {c["name"]: c for c in resp.json()}
        assert "webcam" in cams
        assert cams["webcam"]["location"]["name"] == "Main Office"

    def test_create_location_and_camera(self, client, admin_headers):
        loc = client.post(
            "/api/cameras/locations",
            headers=admin_headers,
            json={"name": "Loading Dock", "building": "HQ", "floor": "G", "room": "Dock 2"},
        )
        assert loc.status_code == 201
        cam = client.post(
            "/api/cameras",
            headers=admin_headers,
            json={"name": "dock-cam", "source": "rtsp://example.local/dock",
                  "location_id": loc.json()["id"]},
        )
        assert cam.status_code == 201
        assert cam.json()["location"]["name"] == "Loading Dock"

    def test_duplicate_camera_rejected(self, client, admin_headers):
        resp = client.post(
            "/api/cameras", headers=admin_headers, json={"name": "webcam"}
        )
        assert resp.status_code == 422

    def test_receptionist_cannot_manage(self, client, receptionist_headers):
        resp = client.post(
            "/api/cameras", headers=receptionist_headers, json={"name": "x-cam"}
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------
class TestWatchlists:
    def test_create_and_add_employee_entry(self, client, admin_headers):
        wl = client.post(
            "/api/watchlists",
            headers=admin_headers,
            json={"name": "VIP escort required", "level": "warning"},
        )
        assert wl.status_code == 201
        entry = client.post(
            f"/api/watchlists/{wl.json()['id']}/entries",
            headers=admin_headers,
            json={"user_id": 1, "reason": "Escort policy"},
        )
        assert entry.status_code == 201
        assert entry.json()["user_id"] == 1

        listing = client.get("/api/watchlists", headers=admin_headers)
        names = [w["name"] for w in listing.json()]
        assert "VIP escort required" in names

    def test_entry_requires_exactly_one_subject(self, client, admin_headers):
        wl = client.post(
            "/api/watchlists", headers=admin_headers, json={"name": "test-xor"}
        )
        wl_id = wl.json()["id"]
        both = client.post(
            f"/api/watchlists/{wl_id}/entries",
            headers=admin_headers,
            json={"user_id": 1, "unknown_face_id": 1},
        )
        neither = client.post(
            f"/api/watchlists/{wl_id}/entries", headers=admin_headers, json={}
        )
        assert both.status_code == 422
        assert neither.status_code == 422

    def test_receptionist_denied(self, client, receptionist_headers):
        resp = client.get("/api/watchlists", headers=receptionist_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Visitors
# ---------------------------------------------------------------------------
class TestVisitors:
    def test_full_visit_lifecycle(self, client, admin_headers):
        created = client.post(
            "/api/visitors",
            headers=admin_headers,
            json={"name": "Jordan Vendor", "company": "Acme", "host_user_id": 1},
        )
        assert created.status_code == 201
        vid = created.json()["id"]
        assert created.json()["status"] == "expected"

        checked_in = client.post(
            f"/api/visitors/{vid}/check-in", headers=admin_headers
        )
        assert checked_in.status_code == 200
        assert checked_in.json()["status"] == "checked_in"
        assert checked_in.json()["check_in"] is not None

        # double check-in rejected
        again = client.post(f"/api/visitors/{vid}/check-in", headers=admin_headers)
        assert again.status_code == 422

        checked_out = client.post(
            f"/api/visitors/{vid}/check-out", headers=admin_headers
        )
        assert checked_out.status_code == 200
        assert checked_out.json()["status"] == "checked_out"

        # visit produced access-history rows
        hist = client.get(
            "/api/access-history", headers=admin_headers,
            params={"visitor_id": vid},
        )
        assert hist.status_code == 200
        events = [r["event"] for r in hist.json()["items"]]
        assert "check_in" in events and "check_out" in events

    def test_unknown_host_rejected(self, client, admin_headers):
        resp = client.post(
            "/api/visitors",
            headers=admin_headers,
            json={"name": "Ghost", "host_user_id": 999999},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Access history
# ---------------------------------------------------------------------------
class TestAccessHistory:
    def test_paginated_listing(self, client, admin_headers):
        resp = client.get("/api/access-history", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert {"items", "total", "page"} <= set(body)

    def test_requires_auth(self, client):
        assert client.get("/api/access-history").status_code == 401


# ---------------------------------------------------------------------------
# Investigation endpoints
# ---------------------------------------------------------------------------
class TestInvestigation:
    def test_employee_report_db_fields_only(self, client, admin_headers):
        resp = client.get("/api/investigation/employee/1", headers=admin_headers)
        assert resp.status_code == 200
        face = resp.json()["faces"][0]
        assert face["person_type"] == "employee"
        assert face["full_name"] == "Administrator"
        # identity comes from the DB; forbidden identity fields never appear
        for forbidden in ("cnic", "national_id", "passport_number",
                          "home_address", "gps_location", "personal_history"):
            assert forbidden not in face
        assert "recognition_history" in face
        assert "watchlist_hits" in face

    def test_employee_report_404(self, client, admin_headers):
        resp = client.get(
            "/api/investigation/employee/999999", headers=admin_headers
        )
        assert resp.status_code == 404

    def test_unknown_report_404(self, client, admin_headers):
        resp = client.get(
            "/api/investigation/unknown/999999", headers=admin_headers
        )
        assert resp.status_code == 404

    def test_receptionist_denied(self, client, receptionist_headers):
        resp = client.get(
            "/api/investigation/employee/1", headers=receptionist_headers
        )
        assert resp.status_code == 403

    def test_analyze_rejects_empty_file(self, client, admin_headers):
        import app.services.face_service as fs

        resp = client.post(
            "/api/investigation/analyze",
            headers=admin_headers,
            files={"file": ("empty.jpg", b"", "image/jpeg")},
        )
        # Without insightface (e.g. CI) the engine-availability 503 fires
        # before file validation; with it, the empty file is rejected as 422.
        assert resp.status_code == (422 if fs.insightface_available() else 503)

    def test_analyze_rejects_invalid_image(self, client, admin_headers):
        import app.services.face_service as fs

        if not fs.insightface_available():
            return  # 503 path covered implicitly; decode not reachable
        resp = client.post(
            "/api/investigation/analyze",
            headers=admin_headers,
            files={"file": ("junk.jpg", b"not-an-image", "image/jpeg")},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AI analysis unit tests (no model download required)
# ---------------------------------------------------------------------------
class TestAIAnalysisUnits:
    def test_scene_analysis_labels_estimates(self):
        import numpy as np

        from app.services import investigation_service as inv

        img = np.full((240, 320, 3), 128, dtype=np.uint8)
        scene = inv.analyze_scene(img, num_faces=2)
        assert scene["resolution"] == [320, 240]
        assert "estimate" in scene["brightness"]
        assert "estimates" in scene["note"]
        # nothing invented: absent models are reported unavailable
        assert scene["object_detection"]["objects"] is None
        assert "unavailable" in scene["object_detection"]["method"]

    def test_blur_and_brightness_metrics(self):
        import numpy as np

        from app.services import investigation_service as inv

        flat = np.full((100, 100, 3), 200, dtype=np.uint8)
        score, label = inv._blur_metrics(flat)
        assert label == "blurry"  # zero-variance image has no edges
        value, blabel = inv._brightness_metrics(flat)
        assert blabel == "bright"

        rng = np.random.default_rng(42)
        noisy = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
        score2, label2 = inv._blur_metrics(noisy)
        assert score2 > score

    def test_new_profile_fields_roundtrip(self, client, admin_headers):
        created = client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "name": "Casey Analyst",
                "email": "casey@example.com",
                "username": "casey",
                "password": "casey-pass-123",
                "role": "security_officer",
                "job_title": "Security Analyst",
                "office_building": "HQ",
                "badge_number": "B-1042",
                "phone": "+1-555-0100",
                "status": "active",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["job_title"] == "Security Analyst"
        assert body["badge_number"] == "B-1042"
        assert body["status"] == "active"


# ---------------------------------------------------------------------------
# Audit viewer
# ---------------------------------------------------------------------------
class TestAuditViewer:
    def test_paginated_and_filterable(self, client, admin_headers):
        resp = client.get("/api/audit", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert {"items", "total", "page"} <= set(body)
        # actions dropdown source
        actions = client.get("/api/audit/actions", headers=admin_headers)
        assert actions.status_code == 200
        assert isinstance(actions.json(), list)

    def test_receptionist_denied(self, client, receptionist_headers):
        assert client.get("/api/audit", headers=receptionist_headers).status_code == 403

    def test_requires_auth(self, client):
        assert client.get("/api/audit").status_code == 401
