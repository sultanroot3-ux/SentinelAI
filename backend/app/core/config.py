"""Application settings for SentinelAI backend.

Values can be overridden via environment variables prefixed with SENTINEL_
(e.g. SENTINEL_SECRET_KEY, SENTINEL_DATABASE_URL) or a backend/.env file.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

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
    SECRET_KEY: str = "sentinelai-super-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 12 hours

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

    @property
    def database_url(self) -> str:
        """Configured DATABASE_URL (PostgreSQL) or the SQLite file fallback."""
        return self.DATABASE_URL or f"sqlite:///{self.DATABASE_PATH}"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

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
