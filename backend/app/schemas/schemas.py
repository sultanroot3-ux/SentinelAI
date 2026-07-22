"""Pydantic v2 schemas matching the SentinelAI API contract."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "security_officer", "receptionist", "it"]
UnknownStatus = Literal["new", "reviewed", "case_opened"]
CaseStatus = Literal["open", "investigating", "closed"]
CasePriority = Literal["low", "medium", "high", "critical"]
NotificationLevel = Literal["info", "warning", "alert"]


# ---------- Auth ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    username: str
    role: str
    department_id: int | None = None
    department_name: str | None = None
    employee_id: str | None = None
    access_level: str | None = None
    photo_url: str | None = None
    face_registered: bool = False
    must_change_password: bool = False
    created_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


# ---------- Users ----------
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    username: str
    password: str = Field(min_length=8)
    role: Role = "receptionist"
    department_id: int | None = None
    employee_id: str | None = None
    access_level: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    username: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: Role | None = None
    department_id: int | None = None
    employee_id: str | None = None
    access_level: str | None = None


# ---------- Departments ----------
class DepartmentCreate(BaseModel):
    name: str
    description: str | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    user_count: int = 0


# ---------- Recognition ----------
class LivenessResult(BaseModel):
    passed: bool
    method: str


class FaceResult(BaseModel):
    box: list[int]  # [x, y, w, h]
    confidence: float
    match: UserOut | None = None
    score: float | None = None
    liveness: LivenessResult


class RecognitionResponse(BaseModel):
    faces: list[FaceResult]


# ---------- Camera ----------
class CameraStatus(BaseModel):
    available: bool
    source: str


# ---------- Logs ----------
class RecognitionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    user_name: str | None = None
    camera: str
    score: float | None = None
    snapshot_url: str | None = None
    timestamp: datetime


class PaginatedLogs(BaseModel):
    items: list[RecognitionLogOut]
    total: int
    page: int


# ---------- Unknown faces ----------
class UnknownFaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    snapshot_url: str | None = None
    camera: str
    status: str
    case_id: int | None = None
    timestamp: datetime


class UnknownFaceUpdate(BaseModel):
    status: UnknownStatus


class PaginatedUnknown(BaseModel):
    items: list[UnknownFaceOut]
    total: int
    page: int


# ---------- Cases ----------
class CaseCreate(BaseModel):
    unknown_face_id: int
    priority: CasePriority = "medium"
    notes: str | None = None
    assigned_to: int | None = None


class CaseUpdate(BaseModel):
    status: CaseStatus | None = None
    priority: CasePriority | None = None
    notes: str | None = None
    assigned_to: int | None = None
    resolution: str | None = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_number: str
    unknown_face_id: int | None = None
    snapshot_url: str | None = None
    camera: str | None = None
    status: str
    priority: str
    notes: str | None = None
    assigned_to: int | None = None
    assigned_to_name: str | None = None
    resolution: str | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedCases(BaseModel):
    items: list[CaseOut]
    total: int
    page: int


# ---------- Analytics ----------
class AnalyticsSummary(BaseModel):
    total_users: int
    today_visitors: int
    today_unknown: int
    open_cases: int
    recognition_accuracy: float


class DailyPoint(BaseModel):
    date: str
    recognized: int
    unknown: int


class PeakHourPoint(BaseModel):
    hour: int
    count: int


class CameraPoint(BaseModel):
    camera: str
    count: int


# ---------- Notifications ----------
class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    message: str
    level: str
    read: bool
    created_at: datetime


# ---------- Settings ----------
class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    recognition_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    liveness_enabled: bool | None = None
    camera_source: str | None = None
    notify_on_unknown: bool | None = None


SettingsMap = dict[str, Any]
