"""Integration tests: user management CRUD + validation."""


def _payload(**overrides):
    base = {
        "name": "Crud User",
        "email": "crud@example.com",
        "username": "cruduser",
        "password": "crud-pass-123",
        "role": "receptionist",
        "department_id": 1,
        "employee_id": "EMP-7777",
        "access_level": "standard",
    }
    base.update(overrides)
    return base


def test_create_get_update_delete_user(client, admin_headers):
    resp = client.post("/api/users", headers=admin_headers, json=_payload())
    assert resp.status_code in (200, 201), resp.text
    uid = resp.json()["id"]
    assert resp.json()["department_name"]

    resp = client.get(f"/api/users/{uid}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "cruduser"

    resp = client.put(
        f"/api/users/{uid}", headers=admin_headers, json={"name": "Renamed User"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed User"

    assert client.delete(f"/api/users/{uid}", headers=admin_headers).status_code == 200
    assert client.get(f"/api/users/{uid}", headers=admin_headers).status_code == 404


def test_duplicate_username_rejected(client, admin_headers):
    p = _payload(username="dupuser", email="dup1@example.com")
    assert client.post("/api/users", headers=admin_headers, json=p).status_code in (200, 201)
    p2 = _payload(username="dupuser", email="dup2@example.com")
    resp = client.post("/api/users", headers=admin_headers, json=p2)
    assert resp.status_code in (409, 422), resp.text


def test_invalid_email_rejected(client, admin_headers):
    resp = client.post(
        "/api/users",
        headers=admin_headers,
        json=_payload(username="bademail", email="not-an-email"),
    )
    assert resp.status_code == 422


def test_search_filter(client, admin_headers):
    resp = client.get(
        "/api/users", headers=admin_headers, params={"search": "admin"}
    )
    assert resp.status_code == 200
    data = resp.json()
    items = data if isinstance(data, list) else data.get("items", [])
    assert any(u["username"] == "admin" for u in items)


def test_photo_upload_requires_valid_extension(client, admin_headers):
    resp = client.post(
        "/api/users/1/photo",
        headers=admin_headers,
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_admin_cannot_delete_self(client, admin_headers):
    assert client.delete("/api/users/1", headers=admin_headers).status_code == 422
