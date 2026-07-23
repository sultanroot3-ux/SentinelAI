"""SQLAlchemy ORM models for SentinelAI."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# RBAC: roles / permissions
# ---------------------------------------------------------------------------
# User.role remains the string used by auth (require_roles); these tables are
# the authoritative catalogue of what each role may do, seeded at startup.
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    roles: Mapped[list["Role"]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    users: Mapped[list["User"]] = relationship(back_populates="department")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="receptionist", nullable=False)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    employee_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    access_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ---- employee profile ----
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    office_building: Mapped[str | None] = mapped_column(String(120), nullable=True)
    badge_number: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    face_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 512-d float32 embedding stored as raw bytes (numpy .tobytes()); None if not registered
    face_embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Forces a password change on next login (set for seeded/reset accounts)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    department: Mapped["Department | None"] = relationship(back_populates="users")
    recognition_logs: Mapped[list["RecognitionLog"]] = relationship(back_populates="user")
    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """Server-side record of issued refresh tokens (enables rotation + revocation)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class CameraLocation(Base):
    __tablename__ = "camera_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    building: Mapped[str | None] = mapped_column(String(120), nullable=True)
    floor: Mapped[str | None] = mapped_column(String(40), nullable=True)
    room: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    cameras: Mapped[list["Camera"]] = relationship(back_populates="location")


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    # OpenCV source: device index ("0") or stream URL/path
    source: Mapped[str] = mapped_column(String(255), default="0", nullable=False)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("camera_locations.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    location: Mapped["CameraLocation | None"] = relationship(back_populates="cameras")


class RecognitionLog(Base):
    __tablename__ = "recognition_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    camera: Mapped[str] = mapped_column(String(80), default="webcam", nullable=False)
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )

    user: Mapped["User | None"] = relationship(back_populates="recognition_logs")
    camera_ref: Mapped["Camera | None"] = relationship()


class UnknownFace(Base):
    __tablename__ = "unknown_faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Stable public identifier ("UNK-000042") assigned on insert
    unknown_person_id: Mapped[str | None] = mapped_column(
        String(20), unique=True, index=True, nullable=True
    )
    snapshot_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    camera: Mapped[str] = mapped_column(String(80), default="webcam", nullable=False)
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    # use_alter breaks the circular FK cycle unknown_faces <-> cases:
    # this constraint is added with ALTER TABLE after both tables exist.
    case_id: Mapped[int | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )

    camera_ref: Mapped["Camera | None"] = relationship()
    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="unknown_face", cascade="all, delete-orphan"
    )


class FaceEmbedding(Base):
    """Face embeddings for employees and unknown persons.

    Exactly one of user_id / unknown_face_id is set. Employees may have several
    embeddings (multiple enrollment photos); unknowns get one per sighting.
    """

    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    unknown_face_id: Mapped[int | None] = mapped_column(
        ForeignKey("unknown_faces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 512-d float32 numpy .tobytes()
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    model: Mapped[str] = mapped_column(String(40), default="buffalo_l", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped["User | None"] = relationship(back_populates="embeddings")
    unknown_face: Mapped["UnknownFace | None"] = relationship(back_populates="embeddings")


class Visitor(Base):
    __tablename__ = "visitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    company: Mapped[str | None] = mapped_column(String(120), nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    badge_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="expected", nullable=False)
    check_in: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    host: Mapped["User | None"] = relationship()


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str] = mapped_column(String(20), default="warning", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    entries: Mapped[list["WatchlistEntry"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistEntry(Base):
    """A person on a watchlist: an employee OR an unknown person."""

    __tablename__ = "watchlist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    unknown_face_id: Mapped[int | None] = mapped_column(
        ForeignKey("unknown_faces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    watchlist: Mapped["Watchlist"] = relationship(back_populates="entries")
    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])
    unknown_face: Mapped["UnknownFace | None"] = relationship(foreign_keys=[unknown_face_id])


class AccessHistory(Base):
    """Every detection / entry / exit event, tied to whoever was seen."""

    __tablename__ = "access_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    visitor_id: Mapped[int | None] = mapped_column(
        ForeignKey("visitors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unknown_face_id: Mapped[int | None] = mapped_column(
        ForeignKey("unknown_faces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    # detected | entry | exit | check_in | check_out
    event: Mapped[str] = mapped_column(String(20), default="detected", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )

    user: Mapped["User | None"] = relationship()
    visitor: Mapped["Visitor | None"] = relationship()
    camera_ref: Mapped["Camera | None"] = relationship()


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    unknown_face_id: Mapped[int | None] = mapped_column(
        ForeignKey("unknown_faces.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    unknown_face: Mapped["UnknownFace | None"] = relationship(foreign_keys=[unknown_face_id])
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assigned_to])


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="info", nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    # JSON-encoded value so booleans / floats / strings round-trip with types intact
    value: Mapped[str] = mapped_column(Text, nullable=False)
