"""Shared pytest fixtures.

The test environment is configured BEFORE the app is imported: a temporary
SQLite database and temporary data directories, so tests never touch the real
PostgreSQL database or the project's uploads/snapshots.
"""
import os
import tempfile
from pathlib import Path

import pytest

# --- environment must be set before any `app.*` import ---------------------
# Default: throwaway SQLite. CI's PostgreSQL job sets SENTINEL_TEST_DATABASE_URL
# to run the identical suite against a real PostgreSQL service container.
_TMP = Path(tempfile.mkdtemp(prefix="sentinel_test_"))
os.environ["SENTINEL_DATABASE_URL"] = os.environ.get(
    "SENTINEL_TEST_DATABASE_URL", f"sqlite:///{_TMP}/test.db"
)
os.environ["SENTINEL_UPLOADS_DIR"] = str(_TMP / "uploads")
os.environ["SENTINEL_UNKNOWN_FACES_DIR"] = str(_TMP / "unknown_faces")
os.environ["SENTINEL_LOGS_DIR"] = str(_TMP / "logs")
os.environ["SENTINEL_DATABASE_DIR"] = str(_TMP)
os.environ["SENTINEL_SECRET_KEY"] = "test-secret-key-not-for-production"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """App with lifespan run (tables created + admin seeded)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def officer_headers(client, admin_headers):
    """A security_officer account (RBAC middle tier)."""
    client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "name": "Test Officer",
            "email": "officer@example.com",
            "username": "officer",
            "password": "officer-pass-123",
            "role": "security_officer",
            "department_id": 1,
            "employee_id": "EMP-9001",
            "access_level": "standard",
        },
    )
    resp = client.post(
        "/api/auth/login", json={"username": "officer", "password": "officer-pass-123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(scope="session")
def receptionist_headers(client, admin_headers):
    """A receptionist account (lowest RBAC tier used in tests)."""
    client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "name": "Test Receptionist",
            "email": "reception@example.com",
            "username": "reception",
            "password": "reception-pass-123",
            "role": "receptionist",
            "department_id": 3,
            "employee_id": "EMP-9002",
            "access_level": "standard",
        },
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": "reception", "password": "reception-pass-123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
