"""Integration tests: role-based access control boundaries."""


def test_receptionist_cannot_update_settings(client, receptionist_headers):
    resp = client.put(
        "/api/settings", headers=receptionist_headers, json={"liveness_enabled": True}
    )
    assert resp.status_code == 403


def test_receptionist_cannot_create_user(client, receptionist_headers):
    resp = client.post(
        "/api/users",
        headers=receptionist_headers,
        json={
            "name": "X",
            "email": "x@example.com",
            "username": "x1",
            "password": "password-123",
            "role": "receptionist",
        },
    )
    assert resp.status_code == 403


def test_receptionist_cannot_delete_user(client, receptionist_headers):
    assert client.delete("/api/users/1", headers=receptionist_headers).status_code == 403


def test_receptionist_cannot_manage_departments(client, receptionist_headers):
    resp = client.post(
        "/api/departments", headers=receptionist_headers, json={"name": "Nope"}
    )
    assert resp.status_code == 403


def test_officer_can_manage_cases(client, officer_headers):
    resp = client.get("/api/cases", headers=officer_headers)
    assert resp.status_code == 200


def test_officer_cannot_update_settings(client, officer_headers):
    resp = client.put(
        "/api/settings", headers=officer_headers, json={"liveness_enabled": True}
    )
    assert resp.status_code == 403


def test_admin_can_update_settings(client, admin_headers):
    resp = client.put(
        "/api/settings", headers=admin_headers, json={"notify_on_unknown": True}
    )
    assert resp.status_code == 200


def test_all_read_endpoints_allow_any_authenticated(client, receptionist_headers):
    for ep in (
        "/api/users",
        "/api/departments",
        "/api/logs",
        "/api/unknown",
        "/api/cases",
        "/api/analytics/summary",
        "/api/notifications",
    ):
        assert client.get(ep, headers=receptionist_headers).status_code == 200, ep


def test_sensitive_reads_are_role_restricted(client, receptionist_headers):
    # Settings expose channel config; reports export the full visitor/recognition
    # log. Both must be denied to a receptionist (settings.manage = admin/it;
    # reports.view = admin/security_officer).
    assert client.get("/api/settings", headers=receptionist_headers).status_code == 403
    assert (
        client.get("/api/reports/visitors", headers=receptionist_headers).status_code
        == 403
    )
