"""SentinelAI FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.security import hash_password
from app.db.database import Base, SessionLocal, engine
from app.models.models import Department, User
from app.services.rbac_service import seed_default_camera, seed_rbac
from app.services.settings_service import seed_default_settings

from app.api import (
    access_history,
    audit,
    analytics,
    auth,
    camera,
    cameras,
    cases,
    departments,
    health,
    investigation,
    logs,
    media,
    notifications,
    rbac,
    recognition,
    reports,
    settings as settings_api,
    unknown,
    users,
    visitors,
    watchlists,
)

setup_logging()
logger = logging.getLogger("sentinelai")


def seed_database(retries: int = 5) -> None:
    """Idempotent seed: admin user + default departments + default settings.

    Concurrency-safe: with multiple uvicorn workers every worker runs this at
    startup, and two can race between the exists-check and the insert. The
    loser's IntegrityError is retried — on retry the exists-checks see the
    other worker's committed rows and skip them.
    """
    import random
    import time

    from sqlalchemy.exc import IntegrityError

    for attempt in range(1, retries + 1):
        try:
            _seed_database_once()
            return
        except IntegrityError:
            if attempt == retries:
                raise
            # Jittered backoff desynchronizes workers that raced in lockstep;
            # it also gives the winner time to COMMIT before we re-check.
            delay = random.uniform(0.2, 1.0) * attempt
            logger.info(
                "Seed race with another worker (attempt %d) — retrying in %.1fs",
                attempt, delay,
            )
            time.sleep(delay)


def _seed_database_once() -> None:
    db = SessionLocal()
    try:
        for name, description in (
            ("Security", "Physical and digital security team"),
            ("IT", "Information technology department"),
            ("Reception", "Front-desk and visitor management"),
        ):
            if not db.query(Department).filter(Department.name == name).first():
                db.add(Department(name=name, description=description))
        db.commit()

        if not db.query(User).filter(User.username == "admin").first():
            security_dept = (
                db.query(Department).filter(Department.name == "Security").first()
            )
            db.add(
                User(
                    name="Administrator",
                    email="admin@sentinelai.local",
                    username="admin",
                    password_hash=hash_password("admin123"),
                    role="admin",
                    department_id=security_dept.id if security_dept else None,
                    employee_id="EMP-0001",
                    access_level="full",
                    # Force the default credentials to be rotated on first login
                    must_change_password=True,
                )
            )
            db.commit()
            logger.info("Seeded default admin user (admin / admin123)")

        seed_default_settings(db)
        seed_rbac(db)
        seed_default_camera(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_for_environment()  # refuses unsafe production config
    settings.ensure_dirs()
    # Development/test convenience only. Production schema is managed
    # exclusively by Alembic — the container entrypoint runs
    # `alembic upgrade head` and refuses to start the app if it fails.
    if not settings.is_production:
        Base.metadata.create_all(bind=engine)
    seed_database()
    # Biometric retention purge (no-op while unknown_retention_days == 0)
    import asyncio

    from app.services.retention_service import retention_loop

    retention_task = asyncio.create_task(retention_loop())
    logger.info("SentinelAI backend ready (env=%s).", settings.ENV)
    yield
    retention_task.cancel()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort handler: log the full traceback, return a clean JSON error.

    (HTTPException / validation errors are handled by FastAPI before this.)
    """
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline security headers on every response.

    HSTS is only meaningful (and only sent) in production, where the app sits
    behind TLS — sending it over plain HTTP in dev would be ignored anyway.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Biometric media (user photos, unknown-visitor snapshots) is sensitive and is
# NOT served from a public static mount. It is delivered only through the
# authenticated /api/media router using short-lived signed URLs (app.api.media).

# Routers
app.include_router(health.router)
app.include_router(media.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(departments.router)
app.include_router(recognition.router)
app.include_router(camera.router)
app.include_router(logs.router)
app.include_router(unknown.router)
app.include_router(cases.router)
app.include_router(analytics.router)
app.include_router(reports.router)
app.include_router(notifications.router)
app.include_router(settings_api.router)
app.include_router(investigation.router)
app.include_router(cameras.router)
app.include_router(watchlists.router)
app.include_router(visitors.router)
app.include_router(access_history.router)
app.include_router(rbac.router)
app.include_router(audit.router)


@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "status": "ok",
        "docs": "/docs",
    }
