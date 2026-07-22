"""Integration tests: health endpoint + security headers middleware."""


def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"


def test_health_requires_no_auth(client):
    # monitors must be able to probe without credentials
    assert client.get("/api/health").status_code == 200


def test_security_headers_present(client):
    resp = client.get("/api/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "camera=()" in resp.headers["Permissions-Policy"]


def test_hsts_absent_in_development(client):
    resp = client.get("/api/health")
    assert "Strict-Transport-Security" not in resp.headers


def test_headers_on_error_responses_too(client):
    resp = client.get("/api/users")  # 401
    assert resp.status_code == 401
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
