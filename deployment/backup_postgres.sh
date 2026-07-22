#!/usr/bin/env bash
# Automated PostgreSQL backup for SentinelAI with retention.
#
# Usage:  ./backup_postgres.sh [backup_dir]
# Env:    SENTINEL_PG_URL   connection string or database name (default: sentinelai)
#         RETENTION_DAYS    how many days of backups to keep (default: 14)
#         PG_DUMP           path to pg_dump (default: pg_dump on PATH)
#
# Schedule it:
#   cron:    0 3 * * *  /opt/sentinelai/deployment/backup_postgres.sh /var/backups/sentinelai
#   docker:  docker compose exec db pg_dump -U sentinel sentinelai | gzip > backup.sql.gz
set -euo pipefail

BACKUP_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)/backups}"
DB="${SENTINEL_PG_URL:-sentinelai}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
PG_DUMP="${PG_DUMP:-pg_dump}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/sentinelai_$STAMP.sql.gz"

"$PG_DUMP" --no-owner --no-privileges "$DB" | gzip > "$OUT"

# Basic integrity check: a valid dump ends with a completion marker
if ! gunzip -c "$OUT" | tail -5 | grep -q "PostgreSQL database dump complete"; then
    echo "ERROR: backup $OUT looks incomplete" >&2
    exit 1
fi

# Retention: delete backups older than RETENTION_DAYS
find "$BACKUP_DIR" -name "sentinelai_*.sql.gz" -mtime "+$RETENTION_DAYS" -delete

SIZE="$(du -h "$OUT" | cut -f1)"
COUNT="$(ls "$BACKUP_DIR"/sentinelai_*.sql.gz 2>/dev/null | wc -l | tr -d ' ')"
echo "Backup OK: $OUT ($SIZE). $COUNT backup(s) retained (window: $RETENTION_DAYS days)."
