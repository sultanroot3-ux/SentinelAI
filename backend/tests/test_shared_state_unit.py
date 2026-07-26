"""Unit tests for the shared-state primitives behind rate limiting (B4).

These test the semantics both backends must honour. The Redis backend is
exercised by the same assertions in CI's redis job via SENTINEL_REDIS_URL.
"""
import time

import pytest

from app.core.shared_state import MemoryBackend, SharedState


@pytest.fixture()
def backend():
    return MemoryBackend()


# ---- sliding window -------------------------------------------------------
def test_window_counts_events(backend):
    for _ in range(4):
        backend.window_add("k", 60)
    count, oldest = backend.window_count("k", 60)
    assert count == 4
    assert oldest is not None and oldest <= time.time()


def test_window_add_returns_running_count(backend):
    assert [backend.window_add("k", 60) for _ in range(3)] == [1, 2, 3]


def test_window_expires_old_events(backend):
    backend.window_add("k", 1)
    assert backend.window_count("k", 1)[0] == 1
    time.sleep(1.1)
    assert backend.window_count("k", 1)[0] == 0


def test_window_clear(backend):
    backend.window_add("k", 60)
    backend.window_clear("k")
    assert backend.window_count("k", 60) == (0, None)


def test_windows_are_independent(backend):
    backend.window_add("a", 60)
    assert backend.window_count("b", 60)[0] == 0


# ---- token bucket ---------------------------------------------------------
def test_bucket_allows_burst_then_denies(backend):
    results = [backend.bucket_take("b", capacity=5, refill_per_second=1.0)[0]
               for _ in range(8)]
    assert results[:5] == [True] * 5
    assert results[5:] == [False] * 3


def test_bucket_reports_retry_after(backend):
    for _ in range(5):
        backend.bucket_take("b", 5, 2.0)
    allowed, retry = backend.bucket_take("b", 5, 2.0)
    assert allowed is False
    # One token at 2/s costs 0.5s; allow slack for the refill during the calls.
    assert 0.0 < retry <= 0.6


def test_bucket_refills_over_time(backend):
    for _ in range(3):
        backend.bucket_take("b", 3, 10.0)
    assert backend.bucket_take("b", 3, 10.0)[0] is False
    time.sleep(0.25)  # 10/s refill -> ~2.5 tokens back
    assert backend.bucket_take("b", 3, 10.0)[0] is True


def test_bucket_never_exceeds_capacity(backend):
    backend.bucket_take("b", 2, 100.0)
    time.sleep(0.2)  # would refill 20 tokens if uncapped
    assert [backend.bucket_take("b", 2, 100.0)[0] for _ in range(3)] == [
        True, True, False
    ]


def test_buckets_are_per_key(backend):
    for _ in range(2):
        backend.bucket_take("u1", 2, 1.0)
    assert backend.bucket_take("u1", 2, 1.0)[0] is False
    assert backend.bucket_take("u2", 2, 1.0)[0] is True


# ---- cooldown -------------------------------------------------------------
def test_cooldown_is_exclusive(backend):
    assert backend.cooldown_acquire("c", 60) is True
    assert backend.cooldown_acquire("c", 60) is False


def test_cooldown_expires(backend):
    assert backend.cooldown_acquire("c", 1) is True
    time.sleep(1.05)
    assert backend.cooldown_acquire("c", 1) is True


def test_cooldowns_are_per_key(backend):
    backend.cooldown_acquire("cam:a", 60)
    assert backend.cooldown_acquire("cam:b", 60) is True, (
        "a second camera must not be suppressed by the first camera's cooldown"
    )


def test_cooldown_acquire_is_atomic_under_threads(backend):
    """Exactly one of N racing threads may win the window."""
    import threading

    wins = []
    lock = threading.Lock()

    def worker():
        got = backend.cooldown_acquire("race", 30)
        with lock:
            wins.append(got)

    threads = [threading.Thread(target=worker) for _ in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wins.count(True) == 1, f"expected exactly one winner, got {wins.count(True)}"


# ---- facade ---------------------------------------------------------------
def test_facade_reports_backend_and_sharing():
    state = SharedState()
    assert state.backend_name in ("memory", "redis", "memory (degraded)")
    assert state.is_shared is (state.backend_name == "redis")


def test_facade_reset_clears_everything():
    state = SharedState()
    state.window_add("w", 60)
    state.bucket_take("b", 1, 1.0)
    state.cooldown_acquire("c", 60)
    state.reset_all()
    assert state.window_count("w", 60)[0] == 0
    assert state.cooldown_acquire("c", 60) is True


def test_facade_namespaces_keys():
    """Keys are prefixed so a shared Redis is not polluted by bare names."""
    state = SharedState()
    assert state._k("login:x") == "sentinelai:login:x"
