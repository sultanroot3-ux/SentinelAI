#!/usr/bin/env bash
# SentinelAI health monitor — run from cron every 5 minutes:
#   */5 * * * *  /opt/sentinelai/deployment/monitor.sh || logger -t sentinelai "health check FAILED"
#
# Checks: API health (incl. DB), container states, disk space, backup recency.
# Exits non-zero on any failure so cron/systemd can alert.
set -uo pipefail

BASE_URL="${SENTINEL_URL:-http://localhost}"
BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "$0")/.." && pwd)/backups}"
DISK_LIMIT_PCT="${DISK_LIMIT_PCT:-90}"
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-26}"
FAIL=0

say() { echo "[monitor] $*"; }

# 1. API + database health
HEALTH="$(curl -fsS -m 10 "$BASE_URL/api/health" 2>/dev/null)" || HEALTH=""
if echo "$HEALTH" | grep -q '"status":[[:space:]]*"ok"'; then
  say "API health: OK"
else
  say "API health: FAILED ($HEALTH)"; FAIL=1
fi

# 2. Container states (only when docker is present — skips bare-metal installs)
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  BAD="$(docker ps --filter "health=unhealthy" --format '{{.Names}}')"
  DOWN="$(docker compose ps --status=exited --format '{{.Name}}' 2>/dev/null)"
  if [[ -n "$BAD$DOWN" ]]; then
    say "Containers unhealthy/exited: $BAD $DOWN"; FAIL=1
  else
    say "Containers: OK"
  fi
fi

# 3. Disk space
USED_PCT="$(df -P "$BACKUP_DIR" 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')"
if [[ -n "${USED_PCT:-}" && "$USED_PCT" -ge "$DISK_LIMIT_PCT" ]]; then
  say "Disk usage ${USED_PCT}% >= ${DISK_LIMIT_PCT}%"; FAIL=1
else
  say "Disk: OK (${USED_PCT:-?}% used)"
fi

# 4. Backup recency
LATEST="$(ls -t "$BACKUP_DIR"/sentinelai_*.sql.gz 2>/dev/null | head -1)"
if [[ -n "$LATEST" ]]; then
  AGE_H=$(( ( $(date +%s) - $(stat -c %Y "$LATEST" 2>/dev/null || stat -f %m "$LATEST") ) / 3600 ))
  if [[ "$AGE_H" -gt "$BACKUP_MAX_AGE_HOURS" ]]; then
    say "Latest backup is ${AGE_H}h old (limit ${BACKUP_MAX_AGE_HOURS}h)"; FAIL=1
  else
    say "Backups: OK (latest ${AGE_H}h old)"
  fi
else
  say "Backups: NONE FOUND in $BACKUP_DIR"; FAIL=1
fi

exit $FAIL
