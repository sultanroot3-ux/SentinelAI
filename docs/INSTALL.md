# SentinelAI — Installation Guide

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | backend |
| Node.js | 18+ | frontend (Vite) |
| PostgreSQL | 14+ | optional — SQLite fallback works with zero config |
| Xcode CLT / build-essential | — | only needed to compile `insightface` |

## 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Optional: real face recognition

```bash
pip install insightface onnxruntime
```

Without these the backend falls back to OpenCV Haar-cascade **detection only**
(faces are boxed but never identified). The first recognition request downloads
the `buffalo_l` model pack (~300 MB) to `~/.insightface/`.

### Database

**SQLite (default, zero config):** just start the server — a `database/sentinel.db`
file is created automatically.

**PostgreSQL (recommended):**

```bash
# macOS
brew install postgresql@16 && brew services start postgresql@16
/usr/local/opt/postgresql@16/bin/createdb sentinelai
# Ubuntu
sudo apt install postgresql && sudo -u postgres createdb sentinelai
```

Create `backend/.env`:

```env
SENTINEL_DATABASE_URL=postgresql+psycopg2://<user>@localhost:5432/sentinelai
```

Apply migrations (Alembic):

```bash
cd backend
.venv/bin/alembic upgrade head
```

> The server also auto-creates missing tables at startup, so Alembic is only
> strictly required for future schema *changes* — but running it keeps the
> version table in sync from day one.

### Start

```bash
python run.py            # or: uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000 — interactive docs at http://localhost:8000/docs
- First startup seeds `admin` / `admin123` and 3 departments.

## 2. Frontend

```bash
cd frontend
npm install
npm run dev              # http://localhost:5173 (proxies /api to :8000)
```

Production build: `npm run build` → `frontend/dist/`.

## 3. Camera (macOS note)

macOS requires per-app camera consent. The first time the backend opens the
webcam you may see *"not authorized to capture video"* — grant access in
**System Settings → Privacy & Security → Camera** for your terminal app, then
restart the backend. IP/RTSP cameras need no permission: set `camera_source`
to the stream URL in the dashboard Settings page.

> **Important:** start the backend with `python run.py` or
> `python -m uvicorn app.main:app` — NOT the bare `uvicorn` console script.
> macOS TCC attributes the console-script launch as a different (never
> authorized) process and camera capture silently fails with
> "not authorized to capture video (status 0)" even after you granted access.

## 4. Docker (all-in-one)

```bash
docker compose up --build
```

Brings up PostgreSQL 16, the backend (port 8000) and the frontend (port 5173).
Host webcams are not reachable from macOS/Windows containers — use an RTSP
camera source, or run the backend natively.

## Configuration reference

Environment variables (prefix `SENTINEL_`, or put them in `backend/.env`):

| Variable | Default | Purpose |
|---|---|---|
| `SENTINEL_SECRET_KEY` | dev key | JWT signing key — **change in production** |
| `SENTINEL_DATABASE_URL` | *(empty → SQLite)* | SQLAlchemy database URL |
| `SENTINEL_ACCESS_TOKEN_EXPIRE_MINUTES` | 720 | JWT lifetime |

Runtime settings (dashboard → Settings): `recognition_threshold`,
`liveness_enabled`, `camera_source`, `notify_on_unknown`.
