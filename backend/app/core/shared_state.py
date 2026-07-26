"""Shared, cross-worker state primitives for rate limiting and cooldowns (B4).

Why this exists
---------------
Login rate limiting and the face-pipeline cooldowns were module-level dicts.
That is only correct with a single worker process, but the shipped production
compose file runs `UVICORN_WORKERS=2` by default — so the effective login limit
was 5 x worker_count, and the "one unknown-face alert per 10 seconds" cooldown
fired once per 10s *per worker*. Both are correctness bugs in the deployed
configuration, not just theoretical ones.

Backends
--------
- Redis (`SENTINEL_REDIS_URL` set): state is shared by every worker and every
  instance. All three primitives are single atomic Lua scripts, so concurrent
  workers cannot interleave a read-modify-write.
- In-memory (default): a lock-protected process-local implementation with
  identical semantics. Correct for single-worker/single-instance deployments
  and used by the test suite.

Clock choice
------------
The in-memory implementation could use `time.monotonic()`, but a monotonic
clock is meaningless across processes — its epoch is per-process. Everything
here uses wall-clock `time.time()` so the two backends behave identically and
Redis-shared timestamps are comparable between workers.

Degradation
-----------
If Redis is configured but unreachable, calls fall back to the in-memory
implementation and log an error. Failing open entirely would remove brute-force
protection; failing closed would make an unreachable cache take down login. The
process-local limiter is the middle path: reduced (per-worker) protection
instead of none, and the service stays up.
"""
import logging
import threading
import time
from collections import defaultdict, deque

from app.core.config import settings
from app.core.redaction import redact_url

logger = logging.getLogger("sentinelai.shared_state")


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------
class MemoryBackend:
    """Process-local implementation. Correct for a single worker."""

    name = "memory"

    def __init__(self) -> None:
        self._windows: dict[str, deque] = defaultdict(deque)
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, ts)
        self._cooldowns: dict[str, float] = {}  # key -> expiry timestamp
        self._lock = threading.Lock()

    # -- sliding window ----------------------------------------------------
    def window_count(self, key: str, window_seconds: int) -> tuple[int, float | None]:
        """(events in window, oldest event timestamp or None)."""
        now = time.time()
        with self._lock:
            w = self._windows[key]
            self._prune(w, now, window_seconds)
            return len(w), (w[0] if w else None)

    def window_add(self, key: str, window_seconds: int) -> int:
        now = time.time()
        with self._lock:
            w = self._windows[key]
            self._prune(w, now, window_seconds)
            w.append(now)
            return len(w)

    def window_clear(self, key: str) -> None:
        with self._lock:
            self._windows.pop(key, None)

    @staticmethod
    def _prune(w: deque, now: float, window_seconds: int) -> None:
        while w and now - w[0] > window_seconds:
            w.popleft()

    # -- token bucket ------------------------------------------------------
    def bucket_take(
        self, key: str, capacity: float, refill_per_second: float, cost: float = 1.0
    ) -> tuple[bool, float]:
        """Take `cost` tokens. Returns (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            tokens, last = self._buckets.get(key, (capacity, now))
            tokens = min(capacity, tokens + (now - last) * refill_per_second)
            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                return True, 0.0
            self._buckets[key] = (tokens, now)
            deficit = cost - tokens
            retry = deficit / refill_per_second if refill_per_second > 0 else 3600.0
            return False, retry

    # -- cooldown ----------------------------------------------------------
    def cooldown_acquire(self, key: str, seconds: float) -> bool:
        """True if the cooldown was free and is now held for `seconds`."""
        now = time.time()
        with self._lock:
            expiry = self._cooldowns.get(key, 0.0)
            if expiry > now:
                return False
            self._cooldowns[key] = now + seconds
            return True

    def clear_all(self) -> None:
        with self._lock:
            self._windows.clear()
            self._buckets.clear()
            self._cooldowns.clear()


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------
# Each script is atomic, so concurrent workers cannot interleave read and write.
_WINDOW_ADD_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('EXPIRE', KEYS[1], math.ceil(window))
return redis.call('ZCARD', KEYS[1])
"""

# Two portability hazards are deliberately avoided here:
#
# 1. A Lua table becomes a Redis multi-bulk reply that TRUNCATES at the first
#    nil, so a nil element would silently shorten the reply. Every element
#    returned is a well-formed string, making the arity fixed at two.
# 2. `ZRANGE ... WITHSCORES` is NOT protocol-independent: RESP2 returns a flat
#    [member, score] array while RESP3 returns nested [[member, score]] pairs.
#    Reading r[2] therefore works on one protocol and yields nil on the other.
#    ZRANGE (members only) followed by ZSCORE is unambiguous on both.
_WINDOW_COUNT_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
local oldest = ''
if count > 0 then
  local m = redis.call('ZRANGE', KEYS[1], 0, 0)
  if m and m[1] then
    local s = redis.call('ZSCORE', KEYS[1], m[1])
    if s then oldest = tostring(s) end
  end
end
return {tostring(count), oldest}
"""

_BUCKET_TAKE_LUA = """
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity; ts = now end
tokens = math.min(capacity, tokens + (now - ts) * refill)
local ttl = math.ceil(capacity / refill) + 60
if tokens >= cost then
  redis.call('HMSET', KEYS[1], 'tokens', tokens - cost, 'ts', now)
  redis.call('EXPIRE', KEYS[1], ttl)
  return {1, '0'}
end
redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], ttl)
return {0, tostring((cost - tokens) / refill)}
"""


class RedisBackend:
    """Cross-worker/cross-instance implementation backed by Redis."""

    name = "redis"

    def __init__(self, url: str) -> None:
        import redis  # imported lazily so redis is optional

        self._client = redis.Redis.from_url(
            url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2
        )
        self._client.ping()  # fail fast at construction, not at first request
        self._window_add = self._client.register_script(_WINDOW_ADD_LUA)
        self._window_count = self._client.register_script(_WINDOW_COUNT_LUA)
        self._bucket_take = self._client.register_script(_BUCKET_TAKE_LUA)

    def window_count(self, key: str, window_seconds: int) -> tuple[int, float | None]:
        count, oldest = self._window_count(
            keys=[key], args=[time.time(), window_seconds]
        )
        return int(count), (float(oldest) if oldest else None)

    def window_add(self, key: str, window_seconds: int) -> int:
        # A unique member per event: the ZSET counts events, not distinct scores
        # (two failures in the same millisecond must both be recorded).
        now = time.time()
        member = f"{now}:{threading.get_ident()}"
        return int(self._window_add(keys=[key], args=[now, window_seconds, member]))

    def window_clear(self, key: str) -> None:
        self._client.delete(key)

    def bucket_take(
        self, key: str, capacity: float, refill_per_second: float, cost: float = 1.0
    ) -> tuple[bool, float]:
        allowed, retry = self._bucket_take(
            keys=[key], args=[time.time(), capacity, refill_per_second, cost]
        )
        return bool(int(allowed)), float(retry)

    def cooldown_acquire(self, key: str, seconds: float) -> bool:
        # SET NX EX is already atomic — no script needed.
        return bool(
            self._client.set(key, "1", nx=True, ex=max(int(round(seconds)), 1))
        )

    def clear_all(self) -> None:
        self._client.flushdb()


# ---------------------------------------------------------------------------
# Facade: picks a backend, degrades to memory on Redis failure
# ---------------------------------------------------------------------------
class SharedState:
    """Backend-agnostic entry point used by rate_limit and face_service."""

    _KEY_PREFIX = "sentinelai:"

    def __init__(self) -> None:
        self._memory = MemoryBackend()
        self._redis: RedisBackend | None = None
        self._degraded = False
        if settings.REDIS_URL:
            try:
                self._redis = RedisBackend(settings.REDIS_URL)
                # redact_url, not the raw value: a production SENTINEL_REDIS_URL
                # normally embeds the cache password in its userinfo.
                logger.info(
                    "Shared state backend: Redis (%s)", redact_url(settings.REDIS_URL)
                )
            except Exception:
                logger.exception(
                    "Redis configured (SENTINEL_REDIS_URL) but unreachable — falling "
                    "back to per-process state. Rate limits are now per-worker."
                )
                self._degraded = True
        else:
            logger.info(
                "Shared state backend: in-memory (set SENTINEL_REDIS_URL for "
                "multi-worker correctness)."
            )

    @property
    def backend_name(self) -> str:
        if self._redis is not None:
            return "redis"
        return "memory (degraded)" if self._degraded else "memory"

    @property
    def is_shared(self) -> bool:
        """True when state is genuinely shared across workers."""
        return self._redis is not None

    def _call(self, method: str, *args):
        """Invoke on Redis when available, degrading to memory on failure."""
        if self._redis is not None:
            try:
                return getattr(self._redis, method)(*args)
            except Exception:
                logger.exception(
                    "Redis %s failed — degrading to per-process state for this call",
                    method,
                )
                self._degraded = True
        return getattr(self._memory, method)(*args)

    def _k(self, key: str) -> str:
        return f"{self._KEY_PREFIX}{key}"

    # -- public API --------------------------------------------------------
    def window_count(self, key: str, window_seconds: int) -> tuple[int, float | None]:
        return self._call("window_count", self._k(key), window_seconds)

    def window_add(self, key: str, window_seconds: int) -> int:
        return self._call("window_add", self._k(key), window_seconds)

    def window_clear(self, key: str) -> None:
        self._call("window_clear", self._k(key))

    def bucket_take(
        self, key: str, capacity: float, refill_per_second: float, cost: float = 1.0
    ) -> tuple[bool, float]:
        return self._call("bucket_take", self._k(key), capacity, refill_per_second, cost)

    def cooldown_acquire(self, key: str, seconds: float) -> bool:
        return self._call("cooldown_acquire", self._k(key), seconds)

    def reset_all(self) -> None:
        """Test helper: clear every backend's state."""
        self._memory.clear_all()
        if self._redis is not None:
            try:
                self._redis.clear_all()
            except Exception:
                logger.exception("Could not flush Redis during reset")


shared_state = SharedState()
