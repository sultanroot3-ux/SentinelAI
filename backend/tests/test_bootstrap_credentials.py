"""Production must not run on the documented bootstrap credential.

The seeded `admin` / `admin123` account exists so a fresh install is reachable,
and `must_change_password=True` is meant to force rotation at first login. That
is a prompt, not a control: nothing stops an operator from deploying with the
credential intact, and it is published in the README, INSTALL.md, ADMIN_MANUAL.md
and API_CONTRACT.md — so "the default password" is not a secret anyone has to
discover.

This pins a startup guard that refuses to boot a PRODUCTION instance while any
account still verifies against the bootstrap password. Development is warned but
allowed, because a throwaway dev database on the default credential is the
intended experience.
"""
import pytest

from app.core.security import hash_password
from app.models.models import User
from app.services.bootstrap_guard import (
    BOOTSTRAP_PASSWORD,
    BootstrapCredentialError,
    accounts_on_bootstrap_password,
    assert_no_bootstrap_credentials,
)


@pytest.fixture()
def _clean(client, db_session):
    """Remove any probe accounts this module creates, before and after."""
    _purge(db_session)
    yield
    _purge(db_session)


def _purge(db):
    db.query(User).filter(User.email.like("%@bootstrap.test")).delete(
        synchronize_session=False
    )
    db.commit()


def _make_user(db, username, password):
    u = User(
        name=username,
        email=f"{username}@bootstrap.test",
        username=username,
        password_hash=hash_password(password),
        role="admin",
    )
    db.add(u)
    db.commit()
    return u


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def test_detects_an_account_still_on_the_bootstrap_password(_clean, db_session):
    _make_user(db_session, "still_default", BOOTSTRAP_PASSWORD)

    found = accounts_on_bootstrap_password(db_session)

    assert "still_default" in found


def test_ignores_accounts_with_a_rotated_password(_clean, db_session):
    _make_user(db_session, "rotated", "an-actually-random-passphrase-9f3b")

    found = accounts_on_bootstrap_password(db_session)

    assert "rotated" not in found


def test_detection_covers_every_account_not_just_admin(_clean, db_session):
    """Any account on the published credential is the same exposure."""
    _make_user(db_session, "second_default", BOOTSTRAP_PASSWORD)
    u = _make_user(db_session, "reception_default", BOOTSTRAP_PASSWORD)
    u.role = "receptionist"
    db_session.commit()

    found = accounts_on_bootstrap_password(db_session)

    assert {"second_default", "reception_default"} <= set(found)


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------
def test_production_refuses_to_start_on_the_bootstrap_password(
    _clean, db_session, monkeypatch
):
    from app.core import config as config_module

    _make_user(db_session, "prod_default", BOOTSTRAP_PASSWORD)
    monkeypatch.setattr(config_module.settings, "ENV", "production")

    with pytest.raises(BootstrapCredentialError) as excinfo:
        assert_no_bootstrap_credentials(db_session)

    assert "prod_default" in str(excinfo.value)


def test_production_starts_once_the_credential_is_rotated(
    _clean, db_session, monkeypatch
):
    """Clean bill of health only when NO account holds the credential.

    The suite's own database is seeded with the default `admin`, so this has to
    rotate that too — which is the point: one forgotten account is enough to
    keep the door open, and the guard is supposed to say so.
    """
    from app.core import config as config_module

    _make_user(db_session, "prod_rotated", "b7Qm-rotated-secret-2f18")
    seeded = db_session.query(User).filter(User.username == "admin").first()
    original_hash = seeded.password_hash if seeded else None
    if seeded is not None:
        seeded.password_hash = hash_password("temporary-rotation-for-this-test-4c1a")
        db_session.commit()

    monkeypatch.setattr(config_module.settings, "ENV", "production")
    try:
        assert_no_bootstrap_credentials(db_session)  # must not raise
    finally:
        if seeded is not None:
            seeded.password_hash = original_hash
            db_session.commit()


def test_development_warns_but_does_not_block(_clean, db_session, monkeypatch, caplog):
    """A dev install on the default credential is the intended experience."""
    from app.core import config as config_module

    _make_user(db_session, "dev_default", BOOTSTRAP_PASSWORD)
    monkeypatch.setattr(config_module.settings, "ENV", "development")

    with caplog.at_level("WARNING", logger="sentinelai.bootstrap"):
        assert_no_bootstrap_credentials(db_session)  # must not raise

    assert any("bootstrap" in r.message.lower() for r in caplog.records)


def test_the_error_does_not_repeat_the_password(_clean, db_session, monkeypatch):
    """The refusal names the accounts; it must not echo the credential.

    Startup errors land in aggregated logs and crash reports. The value is
    already public, but writing it into every failed boot is gratuitous.
    """
    from app.core import config as config_module

    _make_user(db_session, "quiet_default", BOOTSTRAP_PASSWORD)
    monkeypatch.setattr(config_module.settings, "ENV", "production")

    with pytest.raises(BootstrapCredentialError) as excinfo:
        assert_no_bootstrap_credentials(db_session)

    assert BOOTSTRAP_PASSWORD not in str(excinfo.value)


def test_guard_runs_at_application_startup():
    """Wired into the lifespan, not merely importable."""
    import inspect

    from app import main

    source = inspect.getsource(main.lifespan)
    assert "assert_no_bootstrap_credentials" in source, (
        "the guard exists but nothing calls it during startup"
    )
