"""Tests for app/core/clock.py and the naive-UTC persistence convention.

The point of these is not that the helpers are hard — it is that the *convention*
they encode is easy to break silently. A future edit that makes `utcnow()` return
an aware datetime would pass every other test in this suite and then raise
`TypeError` in production the first time a refresh token was validated.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.clock import now_utc, to_naive_utc, utcnow
from app.models.models import RecognitionLog


def test_utcnow_is_naive():
    """The DB columns are naive; anything that feeds them must be too."""
    assert utcnow().tzinfo is None


def test_now_utc_is_aware_and_utc():
    value = now_utc()
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)


def test_utcnow_matches_the_deprecated_builtin():
    """`utcnow()` is a drop-in for the deprecated stdlib call: same instant, same shape.

    Spelled via `now(timezone.utc).replace(...)` rather than the deprecated name
    so the CI guard in `.github/workflows/ci.yml` does not flag this file.
    """
    ours = utcnow()
    reference = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((ours - reference).total_seconds()) < 5
    assert ours.tzinfo is reference.tzinfo is None


def test_utcnow_and_now_utc_agree_on_the_instant():
    delta = now_utc() - utcnow().replace(tzinfo=timezone.utc)
    assert abs(delta.total_seconds()) < 5


def test_to_naive_utc_shifts_rather_than_truncating():
    """A non-UTC aware value must be converted, not stripped.

    Stripping would record 09:00 for an instant that is really 04:00 UTC — a
    five-hour error in an audit trail, and exactly the bug `.replace(tzinfo=None)`
    causes when applied to something that is not already UTC.
    """
    kabul = timezone(timedelta(hours=4, minutes=30))
    aware = datetime(2026, 8, 1, 9, 0, tzinfo=kabul)
    assert to_naive_utc(aware) == datetime(2026, 8, 1, 4, 30)


def test_to_naive_utc_passes_naive_through_unchanged():
    naive = datetime(2026, 8, 1, 4, 30)
    assert to_naive_utc(naive) is naive


def test_naive_and_aware_do_not_compare():
    """Documents the failure this convention exists to prevent."""
    with pytest.raises(TypeError):
        _ = now_utc() - utcnow()


def test_column_default_round_trips_as_naive(client, db_session):
    """The end-to-end claim: a `default=utcnow` column reads back naive.

    If this ever fails, every `row.timestamp < utcnow()` comparison in the
    codebase is one deploy away from raising.

    `client` is requested only for its side effect — the app lifespan is what
    creates the tables — not because this test speaks HTTP.
    """
    row = RecognitionLog(user_id=None, camera="clock-test", score=0.5)
    try:
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        assert row.timestamp.tzinfo is None
        assert abs((utcnow() - row.timestamp).total_seconds()) < 60
    finally:
        db_session.delete(row)
        db_session.commit()
