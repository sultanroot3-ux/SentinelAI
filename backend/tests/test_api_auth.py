"""Integration tests: authentication endpoints."""


def test_login_success(client):
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"


def test_login_wrong_password(client):
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "nope"}
    )
    assert resp.status_code == 401
    assert "detail" in resp.json()


def test_login_unknown_user(client):
    resp = client.post(
        "/api/auth/login", json={"username": "ghost", "password": "whatever"}
    )
    assert resp.status_code == 401


def test_me_returns_current_user(client, admin_headers):
    resp = client.get("/api/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_protected_endpoint_without_token(client):
    assert client.get("/api/users").status_code == 401


def test_protected_endpoint_with_garbage_token(client):
    resp = client.get(
        "/api/users", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


def test_camera_stream_rejects_bad_query_token(client):
    resp = client.get("/api/camera/stream", params={"token": "garbage"})
    assert resp.status_code == 401
