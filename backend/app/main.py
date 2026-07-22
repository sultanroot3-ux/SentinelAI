"""SentinelAI FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.security import hash_password
from app.db.database import Base, SessionLocal, engine
from app.models.models import Department, User
from app.services.settings_service import seed_default_settings

from app.api import (
    analytics,
    auth,
    camera,
    cases,
    departments,
    logs,
    notifications,
    recognition,
    reports,
    settings as settings_api,
    unknown,
    users,
)

setup_logging()
logger = logging.getLogger("sentinelai")


def seed_database() -> None:
    """Idempotent seed: admin user + default departments + default settings."""
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
                )
            )
            db.commit()
            logger.info("Seeded default admin user (admin / admin123)")

        seed_default_settings(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    seed_database()
    logger.info("SentinelAI backend ready.")
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort handler: log the full traceback, return a clean JSON error.

    (HTTPException / validation errors are handled by FastAPI before this.)
    """
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file mounts (per API contract)
app.mount(
    "/static/uploads",
    StaticFiles(directory=str(settings.UPLOADS_DIR)),
    name="uploads",
)
app.mount(
    "/static/unknown_faces",
    StaticFiles(directory=str(settings.UNKNOWN_FACES_DIR)),
    name="unknown_faces",
)

# Routers
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


@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "status": "ok",
        "docs": "/docs",
    }
