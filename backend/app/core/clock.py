"""Time helpers.

`datetime.utcnow()` is deprecated (Python 3.12) and scheduled for removal. It is
also a long-standing footgun: it returns a *naive* datetime holding UTC, so the
value carries no evidence of which zone it is in and silently compares equal to
a naive local time.

This module replaces it with two explicit functions:

- `utcnow()` — naive datetime holding UTC. Use this for anything that touches a
  database column, because that is what the columns store.
- `now_utc()` — timezone-aware UTC. Use this at boundaries that understand
  offsets (JWT `exp`, ISO-8601 output, arithmetic against other aware values).

**Why the persistence layer stays naive.** The obvious "fix" is to make every
column `DateTime(timezone=True)` and use aware datetimes throughout. That does
not work here, because SQLite backs local development, the pytest suite and the
Playwright E2E run, and SQLite has no timestamp type: SQLAlchemy formats the
datetime into a string and **drops `tzinfo` even when the column declares
`timezone=True`**, so reads come back naive regardless. Code written to compare
`row.created_at` against an aware `now` would pass on PostgreSQL and raise
`TypeError: can't subtract offset-naive and offset-aware datetimes` on SQLite —
a whole class of bug that only appears on one backend.

So the convention is: **aware at the edges, naive-UTC in the database**, and
`to_naive_utc()` is the one-way door between them. `create_refresh_token()`
already worked this way (`expire.replace(tzinfo=None)` before the insert); this
module makes the convention explicit and applies it everywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["now_utc", "utcnow", "to_naive_utc"]


def now_utc() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def to_naive_utc(value: datetime) -> datetime:
    """Convert any datetime to naive UTC, the form the database columns hold.

    Aware values are converted to UTC first, so a non-UTC input is shifted
    rather than having its offset silently discarded. Naive values are assumed
    to already be UTC and returned unchanged.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utcnow() -> datetime:
    """Current UTC time as a naive datetime — a drop-in for `datetime.utcnow()`.

    Identical semantics, without the deprecation. Use for database columns and
    for comparison against values read back from them.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
