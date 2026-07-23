#!/bin/sh
# Daily backup loop for the docker "backup" service (see docker-compose.prod.yml).
# Backs up BOTH the database and the media volume (enrollment photos,
# evidence snapshots) — a restore needs the pair from the same day.
# Env: PGPASSWORD, RETENTION_DAYS (default 14)
set -u
RETENTION_DAYS="${RETENTION_DAYS:-14}"

while true; do
  STAMP="$(date +%Y%m%d_%H%M%S)"

  # 1. Database
  DB_OUT="/backups/sentinelai_${STAMP}.sql.gz"
  if pg_dump -h db -U sentinel --no-owner --no-privileges sentinelai | gzip > "$DB_OUT"; then
    echo "backup OK: $DB_OUT ($(du -h "$DB_OUT" | cut -f1))"
  else
    echo "backup FAILED (database) at $STAMP" >&2
    rm -f "$DB_OUT"
  fi

  # 2. Media (uploads, unknown-face snapshots) from the sentinel-data volume
  if [ -d /data ]; then
    MEDIA_OUT="/backups/sentinelai_media_${STAMP}.tar.gz"
    if tar czf "$MEDIA_OUT" -C /data uploads unknown_faces 2>/dev/null; then
      echo "backup OK: $MEDIA_OUT ($(du -h "$MEDIA_OUT" | cut -f1))"
    else
      echo "backup FAILED (media) at $STAMP" >&2
      rm -f "$MEDIA_OUT"
    fi
  fi

  # 3. Retention
  find /backups -name "sentinelai_*.sql.gz" -mtime "+$RETENTION_DAYS" -delete
  find /backups -name "sentinelai_media_*.tar.gz" -mtime "+$RETENTION_DAYS" -delete

  sleep 86400
done
