# Changelog

All notable changes to SentinelAI are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).

## [1.0.0] — 2026-07-23

First production-ready release.

### Added
- **AI engine**: InsightFace (ArcFace, buffalo_l) face recognition with 512-d embeddings; OpenCV Haar-cascade fallback; face registration via photo upload; unknown-visitor pipeline (snapshot → case management → notifications); temporal liveness detection (blink + non-rigid motion + head-pose micro-movement)
- **Backend**: FastAPI with 13 routers (auth, users, departments, recognition, camera, logs, unknown, cases, analytics, reports, notifications, settings, health); PostgreSQL via SQLAlchemy 2 + Alembic migrations with zero-config SQLite fallback
- **Authentication**: JWT access tokens (30 min) + single-use rotating refresh tokens (7 days) with server-side revocation; login rate limiting (5 attempts / 15 min per username+IP); RBAC (admin, security officer, receptionist, IT); bcrypt hashing; forced password change for seeded accounts; audit logging
- **Dashboard**: React (Vite) with 13 pages, dark/light themes, live MJPEG camera feed with server-side AI overlay, SVG analytics charts, investigation case workflow
- **Notifications**: in-app + Email (SMTP) + Telegram + Discord, configurable from the dashboard with masked secrets
- **Reports**: CSV / JSON / PDF / Excel exports (daily, weekly, monthly)
- **Ops**: Docker Compose (PostgreSQL + backend + nginx with TLS); HTTPS with security headers (HSTS, CSP, X-Frame-Options); automated PostgreSQL backup script with retention; `/api/health` endpoint; rotating file logs
- **Quality**: 79-test pytest suite (unit + integration) run in CI against both SQLite and PostgreSQL, plus frontend build job

### Fixed (during development, pre-release)
- OpenCV 5 removed `CascadeClassifier` — pinned `opencv-python < 5`
- Circular FK `cases ↔ unknown_faces` broke the initial migration — resolved with `use_alter`
- UTC/local date-window bug excluded today's rows from daily reports and analytics after local midnight
- `func.strftime` (SQLite-only) crashed peak-hours analytics on PostgreSQL — replaced with portable `extract`
- `func.date()` key-type mismatch silently zeroed daily analytics on PostgreSQL
- macOS AVFoundation camera failure under FastAPI worker threads (`OPENCV_AVFOUNDATION_SKIP_AUTH`)
- Unrooted `models/` gitignore pattern excluded the `backend/app/models` source package from the repository

[1.0.0]: https://github.com/sultanroot3-ux/SentinelAI/releases/tag/v1.0.0
