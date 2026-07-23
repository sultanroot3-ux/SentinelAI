# Changelog

All notable changes to SentinelAI are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).

## [1.0.2] — 2026-07-23

Production-blocker fixes from the final engineering review. No new features.

### Fixed
- **Migrations (C1)**: container entrypoint runs `alembic upgrade head` and fails fast; `create_all` is development-only; automatic adoption (stamp) of unversioned v1.0.1 databases; verified fresh install / upgrade / rollback / failure paths
- **TLS reload (C2)**: nginx hot-reloads automatically when certbot renews certificates (zero-downtime, verified by simulated renewal) — previously renewed certs were never loaded, guaranteeing an outage at first renewal
- **Multi-worker embedding cache (C3)**: DB version-signature revalidation; newly enrolled faces recognized immediately by all workers (verified live with 2 workers)
- **AI model persistence (C4)**: insightface + onnxruntime now included in the production image with the buffalo_l model baked in (SHA-256 pinned); fully offline-capable — previously the production image had no recognition engine and would download models at runtime
- Multi-worker seed race: first startup with several workers could crash the losing worker on duplicate-key; now retried with jittered backoff

## [1.0.0] — 2026-07-23

First production-ready release.

### Added
- **AI engine**: InsightFace (ArcFace, buffalo_l) face recognition with 512-d embeddings; OpenCV Haar-cascade fallback; face registration via photo upload; unknown-visitor pipeline (snapshot → case management → notifications); temporal liveness detection (blink + non-rigid motion + head-pose micro-movement)
- **Enterprise Investigation System**: full investigation reports (database-only identity, camera + location, recognition history, watchlist hits, snapshot); unknown persons get stable `UNK-xxxxxx` IDs with stored embeddings and similar-sighting linkage; AI attribute estimates (age, gender, head pose, face quality, blur, brightness, mask/glasses heuristics) — every value labelled an estimate, absent models report `unavailable`; RBAC catalogue (4 roles × 13 permissions); cameras + locations registry; visitor management with check-in/out; watchlists with alert levels; access-history timeline; read-only audit viewer
- **Backend**: FastAPI with 21 routers; PostgreSQL via SQLAlchemy 2 + Alembic migrations (19 tables) with zero-config SQLite fallback
- **Authentication**: JWT access tokens (30 min) + single-use rotating refresh tokens (7 days) with server-side revocation; login rate limiting (5 attempts / 15 min per username+IP); RBAC (admin, security officer, receptionist, IT); bcrypt hashing; forced password change for seeded accounts; audit logging; biometric media behind short-lived signed URLs
- **Dashboard**: React (Vite) with 21 pages, role-gated navigation, dark/light themes, mobile responsive, live MJPEG camera feed with server-side AI overlay, SVG analytics charts, investigation workflow
- **Notifications**: in-app + Email (SMTP) + Telegram + Discord, configurable from the dashboard with masked secrets
- **Reports**: CSV / JSON / PDF / Excel exports (daily, weekly, monthly)
- **Ops**: one-command Ubuntu production install (`deployment/install_ubuntu.sh`); Docker Compose production stack (PostgreSQL 16, non-root multi-stage backend image, nginx TLS termination on 80/443, Let's Encrypt auto-renewal, daily gzip backups with retention, healthchecks, log rotation); health-monitoring cron script; performance/load test report
- **Quality**: 123-test pytest suite (unit + integration) run in CI against both SQLite and PostgreSQL; frontend build job; Docker image build + production compose validation in CI; Playwright E2E over all 20 authenticated pages

### Fixed (during development, pre-release)
- OpenCV 5 removed `CascadeClassifier` — pinned `opencv-python < 5`
- Circular FK `cases ↔ unknown_faces` broke the initial migration — resolved with `use_alter`
- UTC/local date-window bug excluded today's rows from daily reports and analytics after local midnight
- `func.strftime` (SQLite-only) crashed peak-hours analytics on PostgreSQL — replaced with portable `extract`
- `func.date()` key-type mismatch silently zeroed daily analytics on PostgreSQL
- macOS AVFoundation camera failure under FastAPI worker threads (`OPENCV_AVFOUNDATION_SKIP_AUTH`)
- Unrooted `models/` gitignore pattern excluded the `backend/app/models` source package from the repository

[1.0.0]: https://github.com/sultanroot3-ux/SentinelAI/releases/tag/v1.0.0
