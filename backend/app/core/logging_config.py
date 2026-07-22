"""Central logging configuration.

Console (INFO) + rotating file logs/sentinel.log (5 MB x 5 backups).
Call setup_logging() once at application startup, before anything logs.
"""
import logging
from logging.handlers import RotatingFileHandler

from app.core.config import settings

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"


def setup_logging() -> None:
    settings.ensure_dirs()
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return  # already configured (uvicorn reload, tests, ...)

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.LOGS_DIR / "sentinel.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Keep noisy access logs out of the file at INFO level
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
