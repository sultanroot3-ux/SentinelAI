# SentinelAI v1.0 — Production Deployment Checklist

## Pre-deployment

- [ ] Server: Ubuntu 22.04/24.04, 4 GB+ RAM (8 GB recommended with AI overlay), 20 GB+ disk
- [ ] DNS `A` record for your domain points at the server
- [ ] Ports 80 and 443 reachable from the internet (Let's Encrypt) — or plan `--self-signed`
- [ ] Camera plan: host webcam mapped via `devices: /dev/video0` (Linux) or IP/RTSP camera URL
- [ ] Repository cloned to the server (e.g. `/opt/sentinelai`)

## Deploy

- [ ] `sudo bash deployment/install_ubuntu.sh --domain <fqdn> --email <email>`
- [ ] Installer finished with `Health check OK`
- [ ] `docker compose ps` — all services `running` / `healthy`
- [ ] `.env` is `chmod 600` and backed up somewhere safe (it holds the JWT + DB secrets)

## First-run configuration

- [ ] Log in as `admin / admin123` → forced password change completed
- [ ] Settings: set `camera_source` (RTSP URL or device index), verify Live Camera shows video
- [ ] Settings: `recognition_threshold` (default 0.45) and `liveness_enabled` reviewed
- [ ] Notification channels configured & tested (email / Telegram / Discord) or explicitly disabled
- [ ] Camera Locations + Cameras registered for every physical camera
- [ ] Departments created; employee accounts created with correct roles
- [ ] Employee faces enrolled (clear frontal photos); green-box recognition verified on Live Camera
- [ ] Test the unknown-person flow: unenrolled face → Unknown Visitors entry + notification

## Security verification

- [ ] `https://<domain>/` serves with a valid certificate (padlock, no warnings)
- [ ] `curl -sI https://<domain> | grep -i strict` shows HSTS; CSP / X-Frame-Options / nosniff present
- [ ] `curl -sI http://<domain>` → 301 redirect to HTTPS
- [ ] Backend port 8000 is NOT reachable from outside (`curl http://<domain>:8000` fails)
- [ ] Login rate limiting works: 6 wrong passwords → HTTP 429
- [ ] A receptionist account cannot open admin pages (403s server-side)
- [ ] Audit Log records the actions you just performed

## Operations

- [ ] Daily backup ran: `ls backups/` shows `sentinelai_*.sql.gz` (wait for first cycle or run `deployment/backup_postgres.sh`)
- [ ] Restore drill performed once on a scratch database
- [ ] `deployment/monitor.sh` added to cron (`*/5 * * * *`) with alerting on failure
- [ ] Log rotation confirmed (`docker compose logs` bounded by 10 MB × 5 files per service)
- [ ] Certbot renewal container running (`docker compose ps certbot`)
- [ ] Update procedure noted: `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`

## Sign-off

- [ ] Load check on the deployed host: `npx autocannon -c 50 -d 15 https://<domain>/api/health` — no errors
- [ ] `docs/ADMIN_MANUAL.md` handed to the operating team
- [ ] `docs/USER_MANUAL.md` shared with front-desk staff
