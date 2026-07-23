# SentinelAI — Backup & Restore Guide

Production (`docker-compose.prod.yml`) runs a `backup` service that produces a
**daily pair** of artifacts in `./backups`, plus an optional `offsite` service
that replicates them to any rclone-supported remote.

## What is backed up

| Artifact | Contents |
|---|---|
| `sentinelai_<STAMP>.sql.gz` | full PostgreSQL dump (all tables) |
| `sentinelai_media_<STAMP>.tar.gz` | media volume — enrollment photos (`uploads/`) and evidence snapshots (`unknown_faces/`) |

Restore always uses a **matched pair from the same STAMP** — the DB references
media filenames, so a mismatched pair yields dangling references.

Retention: both are pruned after `BACKUP_RETENTION_DAYS` (default 14).

## Manual backup

```bash
# database
docker compose exec -T db pg_dump -U sentinel --no-owner --no-privileges sentinelai \
  | gzip > backups/sentinelai_manual.sql.gz
# media
docker run --rm -v sentinelai_sentinel-data:/data -v "$PWD/backups:/out" alpine \
  tar czf /out/sentinelai_media_manual.tar.gz -C /data uploads unknown_faces
```

## Restore

Stop the backend first so nothing writes mid-restore:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop backend

# 1. Database
gunzip -c backups/sentinelai_<STAMP>.sql.gz \
  | docker compose exec -T db psql -U sentinel -d sentinelai

# 2. Media (into the sentinel-data volume)
docker run --rm -v sentinelai_sentinel-data:/data -v "$PWD/backups:/in" alpine \
  sh -c 'tar xzf /in/sentinelai_media_<STAMP>.tar.gz -C /data'

docker compose -f docker-compose.yml -f docker-compose.prod.yml start backend
```

For a **clean-environment restore** (new server), run the installer first
(creates the volumes and schema), then apply the restore steps above.

## Offsite replication (H4)

Opt in with the `offsite` compose profile and an rclone remote:

```bash
# .env — example: S3
OFFSITE_REMOTE=offsite:my-bucket/sentinelai
RCLONE_CONFIG_OFFSITE_TYPE=s3
RCLONE_CONFIG_OFFSITE_PROVIDER=AWS
RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID=AKIA...
RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY=...
RCLONE_CONFIG_OFFSITE_REGION=eu-central-1
# OFFSITE_INTERVAL=21600   # seconds between syncs (default 6h)

docker compose --profile offsite -f docker-compose.yml -f docker-compose.prod.yml up -d offsite
```

Any rclone backend works — SFTP/SCP, Backblaze B2, Google Cloud Storage,
Azure Blob, etc. The sync loop **verifies** every transfer with `rclone check`
(size + hash) and logs `sync + verification OK` or a failure.

Restore from offsite: `rclone copy offsite:my-bucket/sentinelai ./backups`
then follow the Restore steps above.

## Verification & drills

- **Backup integrity**: `deployment/backup_postgres.sh` verifies the dump ends
  with PostgreSQL's completion marker; the media tarball is validated by
  `tar tzf`.
- **Restore drill** (recommended monthly): restore the latest pair into a
  scratch database and confirm row counts:
  ```bash
  gunzip -c backups/$(ls -t backups/sentinelai_*.sql.gz | head -1) \
    | docker run --rm -i postgres:16-alpine sh -c \
      'psql "$DATABASE_URL" 2>/dev/null; psql "$DATABASE_URL" -c "SELECT count(*) FROM users;"'
  ```
- **Monitoring**: `deployment/monitor.sh` alerts if the newest backup is older
  than `BACKUP_MAX_AGE_HOURS` (default 26 h).
