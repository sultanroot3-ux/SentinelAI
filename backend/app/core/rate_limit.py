"""In-memory login rate limiting (sliding window, per username + client IP).

After MAX_FAILURES failed attempts within WINDOW_SECONDS, further attempts for
that (username, ip) pair are rejected with 429 until the window slides past.
Successful login clears the counter.

In-memory state is per-process — sufficient for the single-instance
deployments this project targets. For multi-instance deployments swap the
store for Redis (interface kept deliberately small).
"""
import threading
import time
from collections import defaultdict, deque

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60  # 15 minutes

_failures: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = threading.Lock()


def _key(username: str, ip: str) -> tuple[str, str]:
    return (username.lower(), ip)


def _prune(window: deque, now: float) -> None:
    while window and now - window[0] > WINDOW_SECONDS:
        window.popleft()


def check_allowed(username: str, ip: str) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    now = time.monotonic()
    with _lock:
        window = _failures[_key(username, ip)]
        _prune(window, now)
        if len(window) >= MAX_FAILURES:
            retry_after = int(WINDOW_SECONDS - (now - window[0])) + 1
            return False, max(retry_after, 1)
    return True, 0


def record_failure(username: str, ip: str) -> None:
    now = time.monotonic()
    with _lock:
        window = _failures[_key(username, ip)]
        _prune(window, now)
        window.append(now)


def record_success(username: str, ip: str) -> None:
    with _lock:
        _failures.pop(_key(username, ip), None)


def reset_all() -> None:
    """Test helper: clear all rate-limit state."""
    with _lock:
        _failures.clear()
