"""Health endpoint for load balancers / uptime monitors.

Unauthenticated by design, so external monitors can probe it — it therefore
exposes only coarse status, no configuration details.
"""
import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import get_db

logger = logging.getLogger("sentinelai.health")

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def health(response: Response, db: Session = Depends(get_db)):
    """200 with component status; 503 if the database is unreachable."""
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: database unreachable")
        db_ok = False

    if not db_ok:
        response.status_code = 503
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
    }
