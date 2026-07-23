#!/bin/sh
# Daily pg_dump loop for the docker "backup" service (see docker-compose.prod.yml).
# Env: PGPASSWORD, RETENTION_DAYS (default 14)
set -u
RETENTION_DAYS="${RETENTION_DAYS:-14}"

while true; do
  STAMP="$(date +%Y%m%d_%H%M%S)"
  OUT="/backups/sentinelai_${STAMP}.sql.gz"
  if pg_dump -h db -U sentinel --no-owner --no-privileges sentinelai | gzip > "$OUT"; then
    echo "backup OK: $OUT ($(du -h "$OUT" | cut -f1))"
  else
    echo "backup FAILED at $STAMP" >&2
    rm -f "$OUT"
  fi
  find /backups -name "sentinelai_*.sql.gz" -mtime "+$RETENTION_DAYS" -delete
  sleep 86400
done
