"""RBAC catalogue + default camera seeding.

User.role (string) remains what auth checks at request time; the roles /
permissions tables are the authoritative, queryable catalogue of what each
role is allowed to do. Seeding is idempotent.
"""
import logging

from sqlalchemy.orm import Session

from app.models.models import Camera, CameraLocation, Permission, Role

logger = logging.getLogger("sentinelai.rbac")

# permission code -> description
PERMISSIONS: dict[str, str] = {
    "users.manage": "Create, update and delete employee accounts",
    "users.view": "View employee profiles",
    "departments.manage": "Manage departments",
    "cameras.manage": "Add, update and remove cameras and locations",
    "recognition.run": "Run face recognition on frames and streams",
    "investigation.run": "Run investigation reports on detected faces",
    "watchlists.manage": "Create watchlists and manage entries",
    "visitors.manage": "Register visitors and check them in/out",
    "logs.view": "View recognition and access logs",
    "cases.manage": "Open, update and close investigation cases",
    "reports.view": "View and export reports",
    "settings.manage": "Change system settings",
    "audit.view": "View the audit trail",
}

# role -> (description, permission codes)
ROLES: dict[str, tuple[str, list[str]]] = {
    "admin": ("Full system administrator", list(PERMISSIONS)),
    "security_officer": (
        "Security operations: investigation, cases, watchlists",
        [
            "users.view",
            "recognition.run",
            "investigation.run",
            "watchlists.manage",
            "visitors.manage",
            "logs.view",
            "cases.manage",
            "reports.view",
            "audit.view",
        ],
    ),
    "receptionist": (
        "Front desk: visitor registration and recognition",
        ["users.view", "recognition.run", "visitors.manage", "logs.view"],
    ),
    "it": (
        "IT support: cameras and system settings",
        ["users.view", "cameras.manage", "settings.manage", "logs.view"],
    ),
}


def seed_rbac(db: Session) -> None:
    """Create/refresh the role + permission catalogue (idempotent)."""
    perms: dict[str, Permission] = {
        p.code: p for p in db.query(Permission).all()
    }
    for code, description in PERMISSIONS.items():
        if code not in perms:
            perm = Permission(code=code, description=description)
            db.add(perm)
            perms[code] = perm
    db.flush()

    existing_roles = {r.name: r for r in db.query(Role).all()}
    for name, (description, codes) in ROLES.items():
        role = existing_roles.get(name)
        if role is None:
            role = Role(name=name, description=description)
            db.add(role)
        role.permissions = [perms[c] for c in codes if c in perms]
    db.commit()


def seed_default_camera(db: Session) -> None:
    """Ensure the built-in webcam exists as a Camera with a location."""
    if db.query(Camera).filter(Camera.name == "webcam").first():
        return
    location = (
        db.query(CameraLocation).filter(CameraLocation.name == "Main Office").first()
    )
    if location is None:
        location = CameraLocation(
            name="Main Office",
            building="HQ",
            floor="1",
            room="Reception",
            description="Default location for the built-in webcam",
        )
        db.add(location)
        db.flush()
    db.add(Camera(name="webcam", source="0", location_id=location.id, active=True))
    db.commit()
    logger.info("Seeded default webcam camera at Main Office")


def get_camera_by_name(db: Session, name: str) -> Camera | None:
    return db.query(Camera).filter(Camera.name == name).first()
