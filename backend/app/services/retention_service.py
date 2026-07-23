"""Biometric data retention: automatic purge of expired unknown-face records.

Policy (docs/DATA_RETENTION.md):
- `unknown_retention_days` (Settings, default 0 = retention disabled) controls
  how long unknown-person records — snapshot image, stored face embedding,
  and the unknown_faces row — are kept.
- Records are NEVER purged, regardless of age, when they are:
    * linked to an investigation case (evidence), or
    * on a watchlist.
- Every purge run that deletes anything writes an audit entry listing the
  purged record identifiers.
- Employee biometric data is not covered here: it is deleted with the user
  account (embeddings cascade), which is already audited.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Case, UnknownFace, WatchlistEntry
from app.services.audit_service import write_audit
from app.services.settings_service import get_setting

logger = logging.getLogger("sentinelai.retention")

# How often the background loop checks (purge itself is cheap when idle)
PURGE_INTERVAL_SECONDS = 6 * 3600


def _delete_snapshot_file(snapshot_url: str | None) -> None:
    """Remove the snapshot image referenced by an unknown_faces row, if any."""
    if not snapshot_url:
        return
    name = Path(snapshot_url).name
    if not name:
        return
    path = settings.UNKNOWN_FACES_DIR / name
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete snapshot file %s", path)


def purge_expired_unknowns(db: Session) -> int:
    """Delete unknown-face records older than the configured retention window.

    Returns the number of purged records. No-op when retention is disabled.
    """
    retention_days = int(get_setting(db, "unknown_retention_days", 0) or 0)
    if retention_days <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    # Protected: evidence linked to a case (either direction) or watchlisted
    case_linked = db.query(Case.unknown_face_id).filter(
        Case.unknown_face_id.isnot(None)
    )
    watchlisted = db.query(WatchlistEntry.unknown_face_id).filter(
        WatchlistEntry.unknown_face_id.isnot(None)
    )

    expired = (
        db.query(UnknownFace)
        .filter(
            UnknownFace.timestamp < cutoff,
            UnknownFace.case_id.is_(None),
            ~UnknownFace.id.in_(case_linked),
            ~UnknownFace.id.in_(watchlisted),
        )
        .all()
    )
    if not expired:
        return 0

    purged_ids = []
    for row in expired:
        _delete_snapshot_file(row.snapshot_url)
        purged_ids.append(row.unknown_person_id or f"id={row.id}")
        # embeddings are removed by the FaceEmbedding cascade;
        # access_history keeps its rows with unknown_face_id set NULL (FK)
        db.delete(row)
    db.commit()

    shown = ", ".join(purged_ids[:25])
    if len(purged_ids) > 25:
        shown += f", … +{len(purged_ids) - 25} more"
    write_audit(
        db,
        "retention_purge",
        f"Purged {len(purged_ids)} unknown-face record(s) older than "
        f"{retention_days} days (snapshots + embeddings deleted): {shown}",
    )
    logger.info("Retention purge removed %d unknown-face record(s)", len(purged_ids))
    return len(purged_ids)


async def retention_loop() -> None:
    """Background task: run the purge on startup and then periodically."""
    from app.db.database import SessionLocal

    while True:
        try:
            db = SessionLocal()
            try:
                purge_expired_unknowns(db)
            finally:
                db.close()
        except Exception:  # never let the loop die
            logger.exception("Retention purge failed")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
