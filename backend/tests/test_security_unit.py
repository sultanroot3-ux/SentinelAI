"""Unit tests: password hashing and JWT creation/validation."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password, verify_password

FAKE_USER = SimpleNamespace(id=1, username="alice", role="admin")


def test_hash_and_verify_password():
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("wrong", hashed)


def test_hashes_are_salted():
    assert hash_password("same") != hash_password("same")


def test_access_token_roundtrip():
    token = create_access_token(FAKE_USER)
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["sub"] == "1"
    assert payload["username"] == "alice"
    assert payload["role"] == "admin"
    assert "exp" in payload


def test_expired_token_rejected():
    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=5)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with pytest.raises(Exception) as excinfo:
        decode_token(expired)
    assert getattr(excinfo.value, "status_code", None) == 401


def test_tampered_token_rejected():
    token = create_access_token(FAKE_USER)
    with pytest.raises(Exception) as excinfo:
        decode_token(token[:-2] + "xx")
    assert getattr(excinfo.value, "status_code", None) == 401
