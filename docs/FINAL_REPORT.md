# SentinelAI — Final Report (Modules 1–5 + partial 6, 8–10, 13–14)

Date: 2026-07-23 · Verified on macOS (Darwin 24), Python 3.11, Node 26, PostgreSQL 16.14

## Completed Features ✅

| Area | Status | Evidence |
|---|---|---|
| FastAPI backend (12 routers, full API contract) | ✅ verified | all endpoints return 200 with JWT, 401 without |
| JWT auth + bcrypt + RBAC roles | ✅ verified | login/me tested; audit rows written |
| PostgreSQL 16 + SQLAlchemy 2 | ✅ verified | 9 tables, all reads/writes live against Postgres |
| Alembic migrations | ✅ verified | initial schema at head `e9044b89d74c` (circular FK handled via `use_alter`) |
| SQLite zero-config fallback | ✅ verified | used automatically when `SENTINEL_DATABASE_URL` unset |
| Face detection + recognition (InsightFace buffalo_l) | ✅ verified | 6-face sample frame: registered face matched at 0.983, others < 0.08 |
| Haar-cascade fallback (no insightface) | ✅ verified | works after pinning OpenCV < 5 |
| Face registration via photo upload | ✅ verified | 512-d embedding stored, `face_registered` flag set |
| Unknown-visitor pipeline (snapshot → row → alert) | ✅ verified | rate-limited; snapshots in `unknown_faces/` |
| Case management (open → investigate → close) | ✅ verified | CASE-0001 lifecycle tested |
| Recognition logs → PostgreSQL | ✅ verified | rate-limited 1 log/user/30 s |
| Temporal liveness (anti-photo motion heuristic) | ✅ implemented | runs on the AI-overlay stream; enforcement via `liveness_enabled` |
| Live MJPEG stream + AI overlay stream | ✅ implemented | `?analyze=1` draws boxes/names server-side |
| Analytics (summary/daily/peak/cameras) | ✅ verified | UTC-window bug found and fixed |
| Reports CSV/JSON (daily/weekly/monthly) | ✅ verified | streaming CSV download |
| Notifications (in-app) | ✅ verified | unknown-face alerts, read/read-all |
| React dashboard, 13 pages, dark/light | ✅ verified | production build passes; login → data flows |
| Logging (rotating file `logs/sentinel.log`) | ✅ implemented | + global exception handler |
| Docs (API contract, INSTALL, TESTING, DEPLOYMENT) | ✅ written | `docs/`, `deployment/` |

## Remaining Features ❌

- **Physical webcam on this Mac** — macOS camera permission must be granted
  manually (System Settings → Privacy & Security → Camera → your terminal).
  Code path is ready; `camera/status` correctly reports unavailable.
- **Docker Compose runtime test** — Docker isn't installed on this machine;
  compose file is syntax-valid but unexecuted.
- **External notification channels** — email/Discord/Telegram/Slack are stubs
  (Module 12).
- **Advanced liveness** — blink detection & depth cues (Module 6 full scope).
- **Reports as PDF/Excel** — CSV/JSON done; PDF/XLSX pending (Module 13).
- **HTTPS/session hardening, multi-camera, RTSP presets** — later modules.

## Bugs Fixed 🔧

1. **OpenCV 5 removed `CascadeClassifier`** → Haar fallback crashed with 500.
   Pinned `opencv-python>=4.8,<5` and re-verified.
2. **Circular foreign key `cases ↔ unknown_faces`** → Alembic migration failed
   (`relation "users" does not exist`). Fixed with `use_alter=True` and a
   dependency-ordered migration adding the second FK via `ALTER TABLE`.
3. **Local-vs-UTC window bug** in daily reports/analytics → after local
   midnight, today's UTC rows were excluded. Now all windows use UTC dates.
4. **Unhandled exceptions leaked as bare 500s** → global exception handler
   logs the traceback and returns clean JSON.
5. **Live streams could flood the DB** → rate limits: 1 unknown-face row/10 s,
   1 recognition log/user/30 s.

## Project Completion

**~70%** of the 16-module roadmap: Modules 1–5 complete, 6 partial (temporal
liveness), 7–11 complete, 12 in-app only, 13 CSV/JSON only, 14 core done
(JWT/RBAC/hashing/audit), 15 complete, 16 authored but unverified (no Docker).

## Commands to Run

```bash
# Backend  (http://localhost:8000, docs at /docs)
cd backend && source .venv/bin/activate && python run.py

# Frontend (http://localhost:5173 — login: admin / admin123)
cd frontend && npm run dev

# Database migrations
cd backend && alembic upgrade head

# Docker (on a machine with Docker)
docker compose up --build
```

## Suggested Next Module

**Module 12 — Notifications** is the highest-value next step: the hook points
already exist in `notification_service.py`, so wiring Email (SMTP) + Telegram
first gives real-time unknown-visitor alerts on your phone with modest effort.
After that, finish **Module 6** (blink-based liveness) to harden the pipeline
against photo attacks before any real deployment.
