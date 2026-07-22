# SentinelAI — Complete Final Report (100%)

Date: 2026-07-23 · Verified on macOS (Darwin 24), Python 3.11, Node 26,
PostgreSQL 16.14, Docker 29.5.2 (colima)

Every module of the 16-module roadmap is implemented and verified, with the
narrow, explicitly-listed exceptions in "Honest Limitations" below.

## Feature Matrix ✅

| # | Module | Status | Verification |
|---|---|---|---|
| 1 | Python foundation | ✅ | project structure, services, tooling |
| 2 | AI foundation (NumPy/OpenCV) | ✅ | vectorized matching, image pipeline |
| 3 | Camera (USB/IP/RTSP, MJPEG) | ✅ | real webcam: 720p frames; raw + analyzed generators PASS |
| 4 | Face detection (InsightFace, Haar fallback) | ✅ | 6/6 faces in sample frame, conf ≥ 0.87 |
| 5 | Face recognition (ArcFace 512-d, cosine) | ✅ | registered face matched at **0.983**; strangers < 0.08 |
| 6 | Liveness (blink + motion + head pose) | ✅ | 3/3 synthetic scenarios pass; landmarks mapped empirically (eyes 33–42 / 87–96) |
| 7 | User registration + face enrolment | ✅ | photo upload → embedding stored → `face_registered` |
| 8 | Database (PostgreSQL + Alembic, SQLite fallback) | ✅ | 9 tables at head `e9044b89d74c`; all rows verified in pg |
| 9 | Backend API (12 routers) | ✅ | 17-endpoint final sweep: all 200, unauth 401 |
| 10 | Dashboard (React, 13 pages, dark/light) | ✅ | production build passes; AI-overlay toggle; channel settings UI |
| 11 | Investigation cases | ✅ | CASE-0001 lifecycle: open → assign → close with resolution |
| 12 | Notifications (in-app + Email + Telegram + Discord) | ✅ | all three channels delivered to local sinks end-to-end; secrets masked |
| 13 | Reports (CSV, JSON, **PDF**, **Excel**) | ✅ | PDF 1.4 + XLSX validated; 4 download buttons |
| 14 | Security (JWT, RBAC, bcrypt, audit, masking) | ✅ | bad-password/no-token/bad-token 401; receptionist PUT settings → 403; 27 audit rows |
| 15 | Analytics | ✅ | summary/daily/peak-hours/cameras with real pg data |
| 16 | Deployment (Docker Compose: pg + backend + nginx frontend) | ✅ | full stack ran in containers; login through nginx proxy 200 |

## Bugs Found & Fixed This Round 🔧

1. **`func.strftime` is SQLite-only** — `/api/analytics/peak-hours` returned
   500 on PostgreSQL. Fixed with portable `extract('hour', ...)`.
2. **Silent zero-counts in `/api/analytics/daily` on PostgreSQL** —
   `func.date()` returns `date` objects on pg but strings on SQLite; the
   string-keyed lookup never matched. Fixed with key normalization.
3. **macOS camera dead under FastAPI worker threads** — AVFoundation cannot
   prompt for permission off the main run loop. Fixed with
   `OPENCV_AVFOUNDATION_SKIP_AUTH=1` (set automatically on darwin) plus a
   documented launch rule (`python run.py`, not the `uvicorn` console script,
   which macOS TCC treats as an unauthorized process).
4. **Docker build failures** — missing buildx plugin and a stale Docker
   Desktop `credsStore` in `~/.docker/config.json` (backed up, then removed).

## Performance Optimizations ⚡

- **Vectorized face matching with in-memory cache**: all registered
  embeddings are held as one unit-normalized matrix; matching is a single
  `matrix @ embedding` per face instead of a full-table read + Python loop
  per frame. Cache invalidates on photo upload / user delete. Recognition
  results verified identical (0.9833) before/after.
- Analyzed stream runs inference every Nth frame with cached overlays
  between inferences; DB flood protection (1 unknown/10 s, 1 log/user/30 s).
- Notification fan-out on a daemon thread — the recognition path never waits
  on SMTP/webhooks.

## Test Evidence Summary

- **Endpoints**: 17/17 → 200 with JWT; 401 unauthorized; 403 for non-admin
  settings write.
- **PostgreSQL**: users=2, recognition_logs=4, unknown_faces=6, cases=1,
  audit_logs=27, notifications=7 — all written through the live app.
- **Recognition**: multi-face frame → 6 detected, 1 correct match @ 0.983.
- **Liveness**: static photo ✗, handheld photo ✗, live-with-blink ✓ (synthetic
  harness); real-camera analyzed stream produced overlay frames.
- **Camera**: real 1280×720 capture; raw + AI-overlay MJPEG generators PASS.
- **Notifications**: SMTP sink received `[SentinelAI ALERT] Unknown person
  detected`; Telegram sink received `/bot<token>/sendMessage` with chat_id;
  Discord sink received embed JSON.
- **Reports**: `file` identifies PDF 1.4; openpyxl re-opens the XLSX.
- **Docker**: 3 containers up (pg healthy), login through nginx 200.
- **Frontend**: `npm run build` clean (71 kB gz).

## Honest Limitations

- Liveness is a strong heuristic (blink + motion + pose), not a certified
  PAD (ISO 30107) system — a high-quality *video* replay can still pass.
  Depth/IR hardware would be the next step.
- Host webcam is unreachable from macOS/Windows Docker containers (OS
  limitation) — use RTSP sources in containerized deployments.
- Email/Telegram/Discord were verified against local protocol sinks, not
  external providers (no real credentials on this machine); payloads follow
  the providers' documented formats.

## Run Commands

```bash
# Backend (use run.py — see camera note in INSTALL.md)
cd backend && source .venv/bin/activate && python run.py

# Frontend
cd frontend && npm run dev          # http://localhost:5173  admin / admin123

# Migrations
cd backend && alembic upgrade head

# Full stack in Docker
docker compose up --build -d
```

## Project Completion: **100%**

All 16 roadmap modules implemented and verified. Future-features backlog
(voice recognition, license plates, RFID, mobile app, cloud sync) remains
open by design.
