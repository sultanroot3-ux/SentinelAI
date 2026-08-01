"""Application settings for SentinelAI backend.

Values can be overridden via environment variables prefixed with SENTINEL_
(e.g. SENTINEL_SECRET_KEY, SENTINEL_DATABASE_URL) or a backend/.env file.
"""
import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# macOS: FastAPI serves requests on worker threads, but OpenCV's AVFoundation
# backend can only show the camera-permission prompt from the main run loop —
# opening the camera from a thread fails with "can not spin main run loop".
# Camera permission must be granted to the launching app beforehand (System
# Settings -> Privacy & Security -> Camera); this flag skips the in-process
# prompt and just captures.
if sys.platform == "darwin":
    os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

# Known development-only secret; production must override it.
_DEV_SECRET_KEY = "sentinelai-super-secret-key-change-in-production"

# backend/app/core/config.py -> parents[2] == backend/, parents[3] == project root
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "SentinelAI - Intelligent Vision Security Platform"
    # Single source of truth for the release version. It reaches the published
    # API contract via FastAPI(version=...) -> docs/openapi.json, and CI asserts
    # it matches frontend/package.json and the top CHANGELOG entry. Before this
    # existed the contract advertised FastAPI's default "0.1.0" while the
    # frontend claimed "1.0.0" and the tags said v1.0.4 — three different
    # answers to "what version is this?".
    APP_VERSION: str = "1.1.0"
    # "development" (default) or "production". Production refuses to start
    # with the built-in dev secret — see validate_for_environment().
    ENV: str = "development"
    SECRET_KEY: str = _DEV_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database. Empty string -> SQLite file fallback (zero-config dev mode).
    # For PostgreSQL set e.g. SENTINEL_DATABASE_URL=postgresql+psycopg2://user@localhost/sentinelai
    DATABASE_URL: str = ""

    # Paths (relative to project root, as absolute paths)
    DATABASE_DIR: Path = PROJECT_ROOT / "database"
    DATABASE_PATH: Path = PROJECT_ROOT / "database" / "sentinel.db"
    UPLOADS_DIR: Path = PROJECT_ROOT / "uploads"
    UNKNOWN_FACES_DIR: Path = PROJECT_ROOT / "unknown_faces"
    LOGS_DIR: Path = PROJECT_ROOT / "logs"

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Shared state for rate limiting and face-pipeline cooldowns (B4). Empty =
    # per-process in-memory state, which is only correct with a single worker.
    # Set e.g. redis://redis:6379/0 whenever UVICORN_WORKERS > 1 or more than
    # one backend instance runs — see app.core.shared_state.
    REDIS_URL: str = ""

    # Reverse proxies whose X-Forwarded-For header may be trusted for client-IP
    # resolution (rate limiting). Empty = trust nothing (XFF ignored). Set to
    # the proxy/LB address or CIDR in production, e.g. ["172.16.0.0/12"] for the
    # Docker compose network. Accepts single IPs and CIDR ranges.
    TRUSTED_PROXY_IPS: list[str] = []

    @property
    def database_url(self) -> str:
        """Configured DATABASE_URL (PostgreSQL) or the SQLite file fallback."""
        return self.DATABASE_URL or f"sqlite:///{self.DATABASE_PATH}"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"

    @property
    def worker_count(self) -> int:
        """Uvicorn worker processes, as the entrypoint will actually launch them.

        Read from the environment rather than a setting because it is consumed
        by the entrypoint shell script, not by the app — but the app must know
        it to validate that shared state is configured (see B4).
        """
        try:
            return max(int(os.environ.get("UVICORN_WORKERS", "1")), 1)
        except ValueError:
            return 1

    def validate_for_environment(self) -> None:
        """Fail fast on unsafe production configuration (called at startup)."""
        if not self.is_production:
            return
        problems = []
        if self.SECRET_KEY == _DEV_SECRET_KEY:
            problems.append(
                "SENTINEL_SECRET_KEY is the built-in development key — set a "
                "unique secret (e.g. `openssl rand -hex 32`)."
            )
        if len(self.SECRET_KEY) < 32:
            problems.append("SENTINEL_SECRET_KEY must be at least 32 characters.")
        if not self.DATABASE_URL:
            problems.append(
                "SENTINEL_DATABASE_URL is not set — production must not fall "
                "back to the SQLite dev database."
            )
        # Multi-worker without shared state means per-worker rate limits and
        # per-worker pipeline cooldowns (B4). Refuse rather than silently
        # multiplying the login attempt allowance by the worker count.
        if self.worker_count > 1 and not self.REDIS_URL:
            problems.append(
                f"UVICORN_WORKERS={self.worker_count} but SENTINEL_REDIS_URL is "
                "not set — login rate limiting and face-pipeline cooldowns would "
                "be per-worker. Set SENTINEL_REDIS_URL (e.g. redis://redis:6379/0) "
                "or run a single worker."
            )
        if problems:
            raise RuntimeError(
                "Refusing to start with unsafe production config:\n- "
                + "\n- ".join(problems)
            )

    def ensure_dirs(self) -> None:
        """Create runtime directories if they do not exist."""
        for d in (
            self.DATABASE_DIR,
            self.UPLOADS_DIR,
            self.UNKNOWN_FACES_DIR,
            self.LOGS_DIR,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
