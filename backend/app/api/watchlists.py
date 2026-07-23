"""Watchlist management: lists + entries (employees or unknown persons)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.security import require_roles
from app.db.database import get_db
from app.models.models import UnknownFace, User, Watchlist, WatchlistEntry
from app.schemas.schemas import (
    WatchlistCreate,
    WatchlistEntryCreate,
    WatchlistEntryOut,
    WatchlistOut,
)
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])

_WATCHLIST_ROLES = ("admin", "security_officer")


def _serialize_entry(entry: WatchlistEntry) -> WatchlistEntryOut:
    return WatchlistEntryOut(
        id=entry.id,
        watchlist_id=entry.watchlist_id,
        user_id=entry.user_id,
        user_name=entry.user.name if entry.user else None,
        unknown_face_id=entry.unknown_face_id,
        unknown_person_id=(
            entry.unknown_face.unknown_person_id if entry.unknown_face else None
        ),
        reason=entry.reason,
        added_by=entry.added_by,
        created_at=entry.created_at,
    )


def _serialize_watchlist(wl: Watchlist) -> WatchlistOut:
    return WatchlistOut(
        id=wl.id,
        name=wl.name,
        description=wl.description,
        level=wl.level,
        active=wl.active,
        created_at=wl.created_at,
        entries=[_serialize_entry(e) for e in wl.entries],
    )


@router.get("", response_model=list[WatchlistOut])
def list_watchlists(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_WATCHLIST_ROLES)),
):
    lists = (
        db.query(Watchlist)
        .options(
            joinedload(Watchlist.entries).joinedload(WatchlistEntry.user),
            joinedload(Watchlist.entries).joinedload(WatchlistEntry.unknown_face),
        )
        .order_by(Watchlist.name)
        .all()
    )
    return [_serialize_watchlist(wl) for wl in lists]


@router.post("", response_model=WatchlistOut, status_code=201)
def create_watchlist(
    payload: WatchlistCreate,
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles(*_WATCHLIST_ROLES)),
):
    if db.query(Watchlist).filter(Watchlist.name == payload.name).first():
        raise HTTPException(status_code=422, detail="Watchlist name already exists")
    wl = Watchlist(**payload.model_dump())
    db.add(wl)
    db.commit()
    db.refresh(wl)
    write_audit(db, "watchlist_create", f"Created watchlist '{wl.name}'", user=officer)
    return _serialize_watchlist(wl)


@router.post("/{watchlist_id}/entries", response_model=WatchlistEntryOut, status_code=201)
def add_entry(
    watchlist_id: int,
    payload: WatchlistEntryCreate,
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles(*_WATCHLIST_ROLES)),
):
    wl = db.get(Watchlist, watchlist_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    if (payload.user_id is None) == (payload.unknown_face_id is None):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of user_id or unknown_face_id",
        )
    if payload.user_id is not None and db.get(User, payload.user_id) is None:
        raise HTTPException(status_code=422, detail="User not found")
    if (
        payload.unknown_face_id is not None
        and db.get(UnknownFace, payload.unknown_face_id) is None
    ):
        raise HTTPException(status_code=422, detail="Unknown person not found")

    entry = WatchlistEntry(
        watchlist_id=watchlist_id,
        user_id=payload.user_id,
        unknown_face_id=payload.unknown_face_id,
        reason=payload.reason,
        added_by=officer.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    write_audit(
        db,
        "watchlist_entry_add",
        f"Added entry to watchlist '{wl.name}' "
        f"(user={payload.user_id}, unknown={payload.unknown_face_id})",
        user=officer,
    )
    return _serialize_entry(entry)


@router.delete("/{watchlist_id}/entries/{entry_id}")
def remove_entry(
    watchlist_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles(*_WATCHLIST_ROLES)),
):
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None or entry.watchlist_id != watchlist_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    write_audit(db, "watchlist_entry_remove",
                f"Removed entry {entry_id} from watchlist {watchlist_id}", user=officer)
    return {"detail": "Entry removed"}


@router.delete("/{watchlist_id}")
def delete_watchlist(
    watchlist_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(require_roles(*_WATCHLIST_ROLES)),
):
    wl = db.get(Watchlist, watchlist_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    name = wl.name
    db.delete(wl)
    db.commit()
    write_audit(db, "watchlist_delete", f"Deleted watchlist '{name}'", user=officer)
    return {"detail": "Watchlist deleted"}
