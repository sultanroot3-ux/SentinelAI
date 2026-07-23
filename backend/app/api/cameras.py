"""Camera + camera-location management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.db.database import get_db
from app.models.models import Camera, CameraLocation, User
from app.schemas.schemas import (
    CameraCreate,
    CameraLocationCreate,
    CameraLocationOut,
    CameraOut,
    CameraUpdate,
)
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

_MANAGER_ROLES = ("admin", "it")


# ---------- Locations ----------
@router.get("/locations", response_model=list[CameraLocationOut])
def list_locations(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(CameraLocation).order_by(CameraLocation.name).all()


@router.post("/locations", response_model=CameraLocationOut, status_code=201)
def create_location(
    payload: CameraLocationCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(*_MANAGER_ROLES)),
):
    if db.query(CameraLocation).filter(CameraLocation.name == payload.name).first():
        raise HTTPException(status_code=422, detail="Location name already exists")
    location = CameraLocation(**payload.model_dump())
    db.add(location)
    db.commit()
    db.refresh(location)
    write_audit(db, "camera_location_create",
                f"Created camera location '{location.name}'", user=admin)
    return location


# ---------- Cameras ----------
@router.get("", response_model=list[CameraOut])
def list_cameras(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return (
        db.query(Camera)
        .options(joinedload(Camera.location))
        .order_by(Camera.name)
        .all()
    )


@router.post("", response_model=CameraOut, status_code=201)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(*_MANAGER_ROLES)),
):
    if db.query(Camera).filter(Camera.name == payload.name).first():
        raise HTTPException(status_code=422, detail="Camera name already exists")
    if payload.location_id is not None and db.get(CameraLocation, payload.location_id) is None:
        raise HTTPException(status_code=422, detail="Location not found")
    camera = Camera(**payload.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)
    write_audit(db, "camera_create", f"Created camera '{camera.name}'", user=admin)
    return camera


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(*_MANAGER_ROLES)),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    data = payload.model_dump(exclude_unset=True)
    if "location_id" in data and data["location_id"] is not None:
        if db.get(CameraLocation, data["location_id"]) is None:
            raise HTTPException(status_code=422, detail="Location not found")
    for field, value in data.items():
        setattr(camera, field, value)
    db.commit()
    db.refresh(camera)
    write_audit(db, "camera_update", f"Updated camera '{camera.name}'", user=admin)
    return camera


@router.delete("/{camera_id}")
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(*_MANAGER_ROLES)),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    name = camera.name
    db.delete(camera)
    db.commit()
    write_audit(db, "camera_delete", f"Deleted camera '{name}'", user=admin)
    return {"detail": "Camera deleted"}
