"""CRITICAL-1: biometric media must never be publicly accessible.

Verifies the old public static mounts are gone and that media is only
reachable through valid, short-lived signed URLs.
"""
import time

from app.core.media import sign_media_path, verify_media_signature


# ---------------------------------------------------------------------------
# Signing unit tests
# ---------------------------------------------------------------------------
def test_sign_and_verify_roundtrip():
    signed = sign_media_path("/static/uploads/user_1_abc.jpg")
    assert signed.startswith("/api/media/uploads/user_1_abc.jpg?")
    assert "sig=" in signed and "exp=" in signed
    # extract and verify
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(signed).query)
    assert verify_media_signature("uploads", "user_1_abc.jpg", int(q["exp"][0]), q["sig"][0])


def test_sign_none_returns_none():
    assert sign_media_path(None) is None
    assert sign_media_path("") is None


def test_expired_signature_rejected():
    exp = int(time.time()) - 10
    from app.core.media import _sign

    sig = _sign("uploads", "x.jpg", exp)
    assert verify_media_signature("uploads", "x.jpg", exp, sig) is False


def test_tampered_signature_rejected():
    signed = sign_media_path("/static/unknown_faces/unknown_x.jpg")
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(signed).query)
    exp = int(q["exp"][0])
    assert verify_media_signature("unknown_faces", "unknown_x.jpg", exp, "deadbeef") is False
    # wrong filename with a valid-for-other-file signature
    assert verify_media_signature("unknown_faces", "OTHER.jpg", exp, q["sig"][0]) is False


def test_unknown_category_rejected():
    exp = int(time.time()) + 100
    from app.core.media import _sign

    sig = _sign("secrets", "x", exp)
    assert verify_media_signature("secrets", "x", exp, sig) is False


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------
def test_public_static_mount_is_gone(client):
    # The old anonymous path must no longer resolve
    resp = client.get("/static/unknown_faces/anything.jpg")
    assert resp.status_code == 404
    resp = client.get("/static/uploads/anything.jpg")
    assert resp.status_code == 404


def test_media_endpoint_requires_valid_signature(client):
    resp = client.get("/api/media/uploads/whatever.jpg", params={"exp": 9999999999, "sig": "bad"})
    assert resp.status_code == 403


def test_media_endpoint_rejects_expired(client):
    from app.core.media import _sign

    exp = int(time.time()) - 5
    sig = _sign("uploads", "whatever.jpg", exp)
    resp = client.get("/api/media/uploads/whatever.jpg", params={"exp": exp, "sig": sig})
    assert resp.status_code == 403


def test_media_serves_real_file_with_valid_signature(client, admin_headers, tmp_path):
    # Drop a real file into the uploads dir and fetch it via a signed URL
    from app.core.config import settings

    settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    f = settings.UPLOADS_DIR / "test_media_file.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0JPEGDATA")

    signed = sign_media_path("/static/uploads/test_media_file.jpg")
    resp = client.get(signed)
    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xff\xe0JPEGDATA"


def test_media_path_traversal_blocked(client):
    from app.core.media import _sign

    exp = int(time.time()) + 100
    # even with a valid signature for the traversal string, basename guard blocks it
    sig = _sign("uploads", "../../etc/passwd", exp)
    resp = client.get("/api/media/uploads/../../etc/passwd", params={"exp": exp, "sig": sig})
    assert resp.status_code in (403, 404)


def test_signed_snapshot_urls_in_unknown_list(client, admin_headers, db_session):
    from app.models.models import UnknownFace

    row = UnknownFace(snapshot_url="/static/unknown_faces/sig_test.jpg", camera="c")
    db_session.add(row)
    db_session.commit()
    resp = client.get("/api/unknown", headers=admin_headers, params={"status": "new"})
    assert resp.status_code == 200
    data = resp.json()
    items = data if isinstance(data, list) else data.get("items", [])
    hit = next(i for i in items if i["id"] == row.id)
    # Response must expose a signed /api/media URL, never the raw /static path
    assert hit["snapshot_url"].startswith("/api/media/unknown_faces/")
    assert "/static/" not in hit["snapshot_url"]
