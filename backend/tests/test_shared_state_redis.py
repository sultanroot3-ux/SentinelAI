"""Redis-backend tests for shared state (B4).

The Redis backend's primitives are Lua scripts, so they cannot be verified by
testing the in-memory backend — the scripts are where the cross-worker
atomicity actually lives. These run against a real Redis when
SENTINEL_TEST_REDIS_URL is set (CI's redis service), and otherwise against
fakeredis, which executes the same Lua through lupa.

Both paths assert identical semantics to the in-memory backend, so a divergence
between the two implementations fails the build.
"""
import os
import time

import pytest

from app.core.shared_state import RedisBackend

REAL_REDIS_URL = os.environ.get("SENTINEL_TEST_REDIS_URL")


@pytest.fixture()
def backend():
    """A RedisBackend over a real Redis if configured, else fakeredis."""
    if REAL_REDIS_URL:
        b = RedisBackend(REAL_REDIS_URL)
        b.clear_all()
        return b

    fakeredis = pytest.importorskip(
        "fakeredis", reason="install fakeredis[lua] to test the Redis backend"
    )
    pytest.importorskip("lupa", reason="lupa is required to execute Redis Lua scripts")

    # Build the backend without connecting, then swap in the fake client and
    # re-register the scripts against it.
    b = RedisBackend.__new__(RedisBackend)
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    b._client = client
    from app.core import shared_state as ss

    b._window_add = client.register_script(ss._WINDOW_ADD_LUA)
    b._window_count = client.register_script(ss._WINDOW_COUNT_LUA)
    b._bucket_take = client.register_script(ss._BUCKET_TAKE_LUA)
    return b


def test_backend_identifies_itself(backend):
    assert backend.name == "redis"


# ---- sliding window (Lua: ZREMRANGEBYSCORE + ZADD + ZCARD) ----------------
def test_window_add_returns_running_count(backend):
    assert [backend.window_add("k", 60) for _ in range(3)] == [1, 2, 3]


def test_window_count_reports_oldest(backend):
    backend.window_add("k", 60)
    time.sleep(0.02)
    backend.window_add("k", 60)
    count, oldest = backend.window_count("k", 60)
    assert count == 2
    assert oldest is not None and oldest <= time.time()


def test_window_counts_simultaneous_events_separately(backend):
    """Two failures in the same instant must both be recorded.

    A ZSET keyed only by timestamp would collapse them into one member and
    silently under-count, weakening the brute-force limit.
    """
    for _ in range(5):
        backend.window_add("k", 60)
    assert backend.window_count("k", 60)[0] == 5


def test_window_expires_old_events(backend):
    backend.window_add("k", 1)
    time.sleep(1.1)
    assert backend.window_count("k", 1)[0] == 0


def test_window_clear(backend):
    backend.window_add("k", 60)
    backend.window_clear("k")
    assert backend.window_count("k", 60) == (0, None)


# ---- token bucket (Lua: HMGET + refill + HMSET) ---------------------------
def test_bucket_allows_burst_then_denies(backend):
    results = [backend.bucket_take("b", 5, 1.0)[0] for _ in range(8)]
    assert results[:5] == [True] * 5
    assert results[5:] == [False] * 3


def test_bucket_reports_retry_after(backend):
    for _ in range(5):
        backend.bucket_take("b", 5, 2.0)
    allowed, retry = backend.bucket_take("b", 5, 2.0)
    assert allowed is False
    assert 0.0 < retry <= 0.6


def test_bucket_refills_over_time(backend):
    for _ in range(3):
        backend.bucket_take("b", 3, 10.0)
    assert backend.bucket_take("b", 3, 10.0)[0] is False
    time.sleep(0.25)
    assert backend.bucket_take("b", 3, 10.0)[0] is True


def test_bucket_never_exceeds_capacity(backend):
    backend.bucket_take("b", 2, 100.0)
    time.sleep(0.2)
    assert [backend.bucket_take("b", 2, 100.0)[0] for _ in range(3)] == [
        True, True, False
    ]


def test_buckets_are_per_key(backend):
    for _ in range(2):
        backend.bucket_take("u1", 2, 1.0)
    assert backend.bucket_take("u1", 2, 1.0)[0] is False
    assert backend.bucket_take("u2", 2, 1.0)[0] is True


# ---- cooldown (SET NX EX) -------------------------------------------------
def test_cooldown_is_exclusive(backend):
    assert backend.cooldown_acquire("c", 60) is True
    assert backend.cooldown_acquire("c", 60) is False


def test_cooldown_expires(backend):
    assert backend.cooldown_acquire("c", 1) is True
    time.sleep(1.05)
    assert backend.cooldown_acquire("c", 1) is True


def test_cooldowns_are_per_key(backend):
    backend.cooldown_acquire("cam:a", 60)
    assert backend.cooldown_acquire("cam:b", 60) is True


def test_sub_second_cooldown_still_locks(backend):
    """Redis EX has 1s granularity — a fractional cooldown must not round to 0."""
    assert backend.cooldown_acquire("c", 0.4) is True
    assert backend.cooldown_acquire("c", 0.4) is False


# ---- parity with the in-memory backend ------------------------------------
def test_matches_memory_backend_semantics(backend):
    """The two backends must be interchangeable; divergence is a bug."""
    from app.core.shared_state import MemoryBackend

    mem = MemoryBackend()
    for key, cap, rate in (("x", 4, 1.0), ("y", 2, 5.0)):
        redis_results = [backend.bucket_take(key, cap, rate)[0] for _ in range(cap + 2)]
        mem_results = [mem.bucket_take(key, cap, rate)[0] for _ in range(cap + 2)]
        assert redis_results == mem_results, f"backends diverged on bucket {key}"

    assert backend.cooldown_acquire("cd", 30) == mem.cooldown_acquire("cd", 30) is True
    assert backend.cooldown_acquire("cd", 30) == mem.cooldown_acquire("cd", 30) is False

    for _ in range(3):
        r = backend.window_add("w", 60)
        m = mem.window_add("w", 60)
        assert r == m
