# SentinelAI — Deployment Guide

## Production: single command (recommended)

On a fresh Ubuntu server with a DNS record pointing at it:

```bash
git clone <your-repo-url> sentinelai && cd sentinelai
sudo bash deployment/install_ubuntu.sh --domain sentinel.example.com --email admin@example.com
```

This installs Docker, generates secrets into `.env`, obtains a Let's Encrypt
certificate, renders the production nginx config, starts the full stack
(PostgreSQL, backend, nginx on 80/443, certbot auto-renewal, daily backups)
and smoke-tests `/api/health`. Idempotent — safe to re-run.

LAN / IP-only deployments (no public domain):

```bash
sudo bash deployment/install_ubuntu.sh --self-signed
```

After install, see `docs/DEPLOYMENT_CHECKLIST.md` for the go-live checklist
and `docs/ADMIN_MANUAL.md` for operations. Add monitoring with cron:

```
*/5 * * * *  /opt/sentinelai/deployment/monitor.sh || logger -t sentinelai "health FAILED"
```

## Ubuntu Server (bare metal)

```bash
sudo apt update && sudo apt install -y python3.11-venv nodejs npm nginx libgl1

# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install insightface onnxruntime   # optional, real recognition
# run as a service:
sudo tee /etc/systemd/system/sentinelai.service <<'EOF'
[Unit]
Description=SentinelAI Backend
After=network.target

[Service]
WorkingDirectory=/opt/sentinelai/backend
ExecStart=/opt/sentinelai/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
Environment=SENTINEL_SECRET_KEY=<generate-a-long-random-key>

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now sentinelai

# Frontend
cd ../frontend
npm install && npm run build
# serve dist/ with nginx, proxy /api and /static to 127.0.0.1:8000
```

Put nginx in front with HTTPS (certbot) — never expose the API over plain HTTP
outside the LAN.

## Docker

```bash
docker compose up --build -d
```

- Data (database, uploads, snapshots) persists in the `sentinel-data` volume.
- On Linux, pass the webcam through: uncomment the `devices:` block in
  `docker-compose.yml`. On macOS/Windows Docker cannot access the host camera —
  use an IP/RTSP camera as `camera_source` in Settings instead.

## Raspberry Pi (4/5, 64-bit OS)

- Use `opencv-python-headless` and skip insightface (too heavy); or run
  detection on the Pi and recognition on a server.
- Set `camera_source` to `0` for the Pi camera (with `libcamera` v4l2 layer) or
  an RTSP URL.
- Expect ~5–10 FPS detection at 640×480; lower the stream resolution in
  Settings if needed.

## HTTPS

**Docker (built-in):** the frontend container terminates TLS on port 8443.
Generate a local cert once (`./deployment/generate_self_signed_cert.sh`), or
mount real certificates into `docker/certs/` (`sentinel.crt` + `sentinel.key`).
Port 5173 (HTTP) redirects to HTTPS; `/api/health` stays available on HTTP
for load-balancer probes.

**Bare metal:** use certbot with the nginx site config —
`sudo certbot --nginx -d your.domain` — then mirror the security headers from
`docker/nginx.conf` (HSTS, CSP, X-Frame-Options, nosniff, Referrer-Policy).

## Backups

`deployment/backup_postgres.sh` dumps the database (gzip), verifies the dump
completed, and prunes backups older than `RETENTION_DAYS` (default 14):

```bash
# cron — daily at 03:00
0 3 * * *  /opt/sentinelai/deployment/backup_postgres.sh /var/backups/sentinelai
```

Restore: `gunzip -c sentinelai_<stamp>.sql.gz | psql -d sentinelai`.
Also back up `uploads/` and `unknown_faces/` (snapshots live on disk).

## Monitoring

- `GET /api/health` — unauthenticated, returns `{status, database}`;
  503 when the database is down. Point your uptime monitor at it (the Docker
  backend container uses it as its healthcheck too).
- Logs: rotating file at `logs/sentinel.log` (5 MB × 5) + stdout. Audit trail
  in the `audit_logs` table (logins, failed logins, rate-limited attempts,
  user/case/settings changes, password changes).

## Production checklist

- [ ] Change the default `admin` password (forced on first login)
- [ ] Set `SENTINEL_ENV=production` — the backend then refuses to start with
      the dev secret key or without a database URL
- [ ] Set `SENTINEL_SECRET_KEY` (`openssl rand -hex 32`) and
      `SENTINEL_DB_PASSWORD` in `.env` (see `.env.example`)
- [ ] Real TLS certificates (certbot) in place of the self-signed pair
- [ ] Schedule `backup_postgres.sh` via cron; test a restore once
- [ ] Point an uptime monitor at `/api/health`
- [ ] Review local biometric-privacy law (GDPR / BIPA) and post required signage
- [ ] Restrict dashboard access to your internal network / VPN
