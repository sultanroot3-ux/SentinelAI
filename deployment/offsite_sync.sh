#!/bin/sh
# Offsite backup replication loop (docker "offsite" service, rclone image).
# Copies /backups to $OFFSITE_REMOTE and VERIFIES the transfer with
# `rclone check` (size + hash comparison) after every sync.
# Env: OFFSITE_REMOTE (rclone remote:path), OFFSITE_INTERVAL seconds (21600),
#      RCLONE_CONFIG_* backend credentials (see docker-compose.prod.yml).
set -u

if [ -z "${OFFSITE_REMOTE:-}" ]; then
  echo "[offsite] OFFSITE_REMOTE not set — offsite replication disabled." >&2
  # Sleep forever rather than crash-loop; the operator opted into the profile
  # but hasn't configured a remote yet.
  exec sleep infinity
fi

INTERVAL="${OFFSITE_INTERVAL:-21600}"
echo "[offsite] replicating /backups -> $OFFSITE_REMOTE every ${INTERVAL}s"

while true; do
  if rclone copy /backups "$OFFSITE_REMOTE" --include "sentinelai_*" 2>&1; then
    if rclone check /backups "$OFFSITE_REMOTE" --one-way --include "sentinelai_*" 2>&1; then
      echo "[offsite] sync + verification OK ($(date -u +%FT%TZ))"
    else
      echo "[offsite] VERIFICATION FAILED — remote does not match local" >&2
    fi
  else
    echo "[offsite] sync FAILED ($(date -u +%FT%TZ))" >&2
  fi
  sleep "$INTERVAL"
done
