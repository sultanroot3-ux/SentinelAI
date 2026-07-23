# SentinelAI — Administrator Manual (v1.0)

Audience: system administrators and security officers operating a deployed
SentinelAI instance. For deployment itself see `deployment/DEPLOYMENT.md`;
for daily front-desk use see `docs/USER_MANUAL.md`.

## 1. First login

- URL: `https://<your-domain>/` — sign in with the seeded account
  `admin / admin123`. The system **forces a password change** on first login.
- Rotate this immediately; the audit log records every administrative action.

## 2. Roles & permissions

Four roles (view the full matrix at **Roles & Permissions** in the sidebar):

| Role | Intended for | Highlights |
|---|---|---|
| `admin` | System owner | everything (13 permissions) |
| `security_officer` | Security desk | investigation, cases, watchlists, visitors, audit |
| `receptionist` | Front desk | recognition, visitor check-in/out, logs |
| `it` | IT support | cameras, locations, settings |

Role assignment happens per-user on the **Users** page. The catalogue itself
is seeded by the backend and read-only.

## 3. Employee management (Users page)

- **Create** users with the full profile: name, email, username, role,
  department, employee ID, job title, office/building, badge number, phone,
  access level, status (active/inactive).
- **Enroll a face**: row action *Upload photo* → pick a clear, frontal,
  well-lit photo. A 512-d embedding is computed and stored; the photo becomes
  the profile picture. Re-upload any time to re-enroll.
- **Investigation report**: row action *eye icon* → full profile + recognition
  history + watchlist status.
- Deleting a user removes their face data (embeddings cascade).

## 4. Cameras & locations

- **Camera Locations**: create named locations (building/floor/room) first.
- **Cameras**: register each camera with a *source* — `0` for the host webcam,
  or an RTSP/HTTP URL for IP cameras — and assign a location. The `webcam`
  camera is seeded by default.
- The active streaming source is chosen on **Settings → camera_source**.
- Inactive cameras stay in the registry (history keeps referencing them).

## 5. Recognition tuning (Settings page)

| Setting | Default | Notes |
|---|---|---|
| `recognition_threshold` | 0.45 | cosine similarity required for a match; raise to reduce false accepts |
| `liveness_enabled` | false | when on, faces failing temporal liveness are treated as spoofs and not logged |
| `camera_source` | "0" | OpenCV source for the live stream |
| `notify_on_unknown` | true | create an alert notification per unknown sighting |

Notification channels (email/SMTP, Telegram, Discord) are configured on the
same page; secrets are masked after saving.

## 6. Watchlists

**Watchlists** page → create a list (level: info/warning/alert) → add entries:
an **employee** or an **unknown person** (by Unknown-Visitors record ID).
Any investigation involving a flagged person shows a prominent watchlist
banner with the reason.

## 7. Visitors

Register expected visitors (name, company, host, badge). Check-in/check-out
buttons record events into **Access History**. Visitor lifecycle:
`expected → checked_in → checked_out`.

## 8. Investigation workflow

1. **Live Camera** — AI Overlay ON shows real-time recognition.
2. Unknown sightings land in **Unknown Visitors** (each gets a stable
   `UNK-xxxxxx` id, snapshot, embedding, camera, timestamp).
3. *Investigate* → full report: similar prior sightings (embedding match),
   watchlist hits, AI estimates (age/gender/pose/quality — all labelled
   estimates; nothing is invented).
4. *Open Case* → track in **Cases** (priority, assignee, notes, resolution).
5. **Audit Log** records every administrative step of the investigation.

## 9. Backups & restore

- Docker production runs a daily `pg_dump` (gzip) into `./backups`,
  retention `BACKUP_RETENTION_DAYS` (default 14).
- Manual backup: `deployment/backup_postgres.sh` (verifies dump integrity).
- **Restore**:
  ```bash
  gunzip -c backups/sentinelai_YYYYMMDD_HHMMSS.sql.gz | \
    docker compose exec -T db psql -U sentinel -d sentinelai
  ```
- Uploaded photos / snapshots live in the `sentinel-data` volume — include it
  in host-level backups: `docker run --rm -v sentinelai_sentinel-data:/d -v $PWD:/out alpine tar czf /out/media_backup.tgz /d`.

## 10. Monitoring

- `GET /api/health` → `{"status":"ok","database":"up"}` (unauthenticated,
  served on plain HTTP too for load balancers).
- `deployment/monitor.sh` (cron every 5 min) checks API health, container
  states, disk usage, and backup recency; non-zero exit on failure.
- Container healthchecks are defined in compose; `docker compose ps` shows
  health at a glance. Logs: `docker compose logs -f backend`.

## 11. Security operations

- **Audit Log** page: every admin action (who/what/when), filterable.
- Tokens: access 30 min, refresh 7 days single-use rotation; *change
  password* revokes all refresh tokens for that account.
- Login rate limiting: 5 failures / 15 min per username+IP → 429.
- Biometric media is only reachable through signed, expiring URLs.
- TLS certificates renew automatically (certbot container, 12 h cycle).

## 12. Troubleshooting

| Symptom | Check |
|---|---|
| Camera Offline badge | host camera permissions; `camera_source` value; on Linux ensure `/dev/video0` is mapped into the container |
| Recognition slow / choppy AI overlay | CPU-bound inference — raise `UVICORN_WORKERS`, lower AI-overlay use, or move to AVX2/GPU hardware |
| 429 on login | rate limiter engaged — wait for `Retry-After` or check for brute-force attempts in the audit log |
| Unknown flood from one person | enroll them (Users → photo) or raise `recognition_threshold` carefully |
| Health check `database: down` | `docker compose ps db`, then `docker compose logs db` |
