# SentinelAI — Deployment Guide

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

## Production checklist

- [ ] Change the default `admin` password immediately
- [ ] Set a strong `SENTINEL_SECRET_KEY` environment variable
- [ ] HTTPS via reverse proxy (nginx + certbot)
- [ ] Back up `database/` and `unknown_faces/` regularly
- [ ] Review local biometric-privacy law (GDPR / BIPA) and post required signage
- [ ] Restrict dashboard access to your internal network / VPN
