"""Rate limiting: login brute-force protection and expensive-endpoint quotas.

Two independent limiters, both backed by app.core.shared_state so behaviour is
correct across uvicorn workers and instances (B4):

- Login (sliding window): after MAX_FAILURES failures within WINDOW_SECONDS for
  a (username, ip) pair, further attempts are rejected until the window slides.
  A successful login clears the counter.

- Expensive endpoints (token bucket): per-user quotas for the AI endpoints,
  which each cost a full model inference and accept a 10 MB upload (B3). A
  bucket allows a short burst and then settles to a sustained rate, which fits
  real usage (an operator scanning a few frames) while stopping a request loop
  from saturating the worker pool.
"""
import logging
import time

from app.core.shared_state import shared_state

logger = logging.getLogger("sentinelai.rate_limit")

# ---- login ----------------------------------------------------------------
MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60  # 15 minutes


def _login_key(username: str, ip: str) -> str:
    return f"login:{username.lower()}:{ip}"


def check_allowed(username: str, ip: str) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    count, oldest = shared_state.window_count(_login_key(username, ip), WINDOW_SECONDS)
    if count >= MAX_FAILURES and oldest is not None:
        retry_after = int(WINDOW_SECONDS - (time.time() - oldest)) + 1
        return False, max(retry_after, 1)
    return True, 0


def record_failure(username: str, ip: str) -> None:
    shared_state.window_add(_login_key(username, ip), WINDOW_SECONDS)


def record_success(username: str, ip: str) -> None:
    shared_state.window_clear(_login_key(username, ip))


# ---- expensive (AI) endpoints ---------------------------------------------
# Sustained rate and burst size per user, per endpoint class. Recognition is
# the interactive one (an operator watching a feed), investigation is heavier
# (detection + per-face heuristics + optional OCR) so it gets a tighter quota.
QUOTAS: dict[str, tuple[float, float]] = {
    # name: (burst capacity, sustained requests per second)
    "recognition": (20.0, 1.0),      # 20 burst, then 60/min
    "investigation": (10.0, 0.2),    # 10 burst, then 12/min
    "stream_token": (30.0, 0.5),     # cheap, but not free — streams hold a worker
}


def check_quota(name: str, user_id: int) -> tuple[bool, int]:
    """Take one token from a user's bucket for `name`.

    Returns (allowed, retry_after_seconds). An unknown name is allowed through
    rather than failing the request — a missing quota entry is a configuration
    bug, not a reason to break the endpoint.
    """
    quota = QUOTAS.get(name)
    if quota is None:
        logger.warning("No quota configured for %r — allowing", name)
        return True, 0
    capacity, refill = quota
    allowed, retry_after = shared_state.bucket_take(
        f"quota:{name}:{user_id}", capacity, refill
    )
    if not allowed:
        logger.warning(
            "Quota exceeded: user_id=%s endpoint=%s (retry in %.1fs)",
            user_id, name, retry_after,
        )
    return allowed, max(int(retry_after) + 1, 1)


def reset_all() -> None:
    """Test helper: clear all rate-limit state."""
    shared_state.reset_all()
