"""Unit tests: settings service typed storage + secret handling constants."""
from app.services.settings_service import (
    DEFAULT_SETTINGS,
    SECRET_KEYS,
    SECRET_MASK,
    get_all_settings,
    get_setting,
    set_settings,
)


def test_defaults_present(client, db_session):
    values = get_all_settings(db_session)
    for key in DEFAULT_SETTINGS:
        assert key in values


def test_set_and_get_roundtrip(client, db_session):
    set_settings(db_session, {"recognition_threshold": 0.6})
    assert get_setting(db_session, "recognition_threshold") == 0.6
    set_settings(db_session, {"recognition_threshold": 0.45})


def test_bool_and_int_types_preserved(client, db_session):
    set_settings(db_session, {"liveness_enabled": False, "smtp_port": 2525})
    assert get_setting(db_session, "liveness_enabled") is False
    assert get_setting(db_session, "smtp_port") == 2525
    # Restore the DEFAULTS, not arbitrary values. This previously left
    # liveness_enabled=False behind, and because the suite shares one database
    # every later module silently ran with anti-spoofing off — the watchlist
    # suite passed only because of that leak and failed when run alone.
    set_settings(
        db_session,
        {
            "liveness_enabled": DEFAULT_SETTINGS["liveness_enabled"],
            "smtp_port": DEFAULT_SETTINGS["smtp_port"],
        },
    )
    assert get_setting(db_session, "liveness_enabled") is True


def test_secret_keys_are_known_settings():
    assert SECRET_KEYS <= set(DEFAULT_SETTINGS)
    assert SECRET_MASK == "********"
