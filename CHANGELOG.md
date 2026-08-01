# Changelog

All notable changes to SentinelAI are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).

## [1.1.0] — 2026-08-02

Closes the five blockers from the CTO production-readiness review (B1–B5), plus
the hardening and audit follow-ups. First release verified end to end by a green
CI run on the released commit.

### Added
- **Real AI engine in CI.** A dedicated job installs insightface + ONNX Runtime
  and runs the recognition pipeline with `SENTINEL_REQUIRE_AI=1`, so a missing
  engine fails the build instead of silently skipping (B1)
- **Redis-backed shared state** for login rate limiting, endpoint quotas and
  pipeline cooldowns, each a single atomic Lua script. The app refuses to start
  in production with `UVICORN_WORKERS > 1` and no `SENTINEL_REDIS_URL` (B4)
- **Per-user quotas on the expensive AI endpoints**, returning `429` with
  `Retry-After` and auditing breaches (B3)
- **Playwright E2E in CI** on every PR and push to `main`, against the
  production frontend bundle (B5)
- `app/core/clock.py` — explicit time helpers replacing deprecated
  `datetime.utcnow()`, with a CI guard against reintroduction
- `scripts/loadtest.py` — capacity, soak and limiter load-test harness
- `backend/requirements-headless.txt` — pinned, hash-verified headless OpenCV
- `PROJECT_STATUS.md`, `docs/PERFORMANCE.md` (§1–§4), `docs/CTO_REVIEW_FINAL.md`

### Changed
- **Backend image 2.23 GB → 1.65 GB.** Dropped the GUI OpenCV build (which
  dragged in Mesa + LLVM: 192 MB of software OpenGL for a `highgui` module
  nothing calls) and the two buffalo_l models the app never reads (145 MB)
- `FaceAnalysis` now names its modules explicitly, so development and
  production load the same three models
- Deterministic, hash-verified dependency locks across four files (B2)
- `recognition_accuracy` renamed to `match_rate` in the published contract
- Worker-scaling guidance corrected: more `UVICORN_WORKERS` does **not**
  increase recognition throughput (measured flat from concurrency 1→8)

### Fixed
- **The CI check meant to prove the AI engine works inside the shipped image
  never ran.** `docker run … python -` without `-i` gets EOF and exits 0, so it
  passed unconditionally. Fixed, and hardened with a sentinel so it cannot go
  vacuous again
- `GET /api/users` no longer discloses `must_change_password` for other
  accounts — it told any authenticated user which admins were still on a
  default password
- Credential leaks in Telegram/Discord/SMTP failure logs (the bot token and
  webhook URL live in the exception text `requests` raises)
- `GET /api/reports/visitors` capped at 50,000 rows; refuses oversized exports
  with `413` rather than silently truncating
- Horizontal overflow at 375px on the dashboard and live-camera pages
- 13 icon-only buttons given subject-bearing `aria-label`s
- Flaky Redis token-bucket tests, and the suite is now idempotent against a
  persistent PostgreSQL database

## [1.0.4] — 2026-07-24

Fixes from a final pre-freeze codebase audit (backend + frontend). No new features.

### Security
- Login no longer leaks whether a username exists via response timing (always runs a bcrypt verification)
- Uploaded files are capped at 10 MB and rejected before being read into memory (prevents a trivial memory-exhaustion DoS by any authenticated user)
- `GET /api/settings` restricted to admin/it, and `GET /api/reports/visitors` to admin/security_officer (previously any authenticated user could read channel config / export the full visitor & recognition logs); matching nav items are now role-gated
- Deleting an unknown-face record (biometric evidence) and changing its status are now audited; permission denials (403) are logged

### Fixed
- Added a missing index on `recognition_logs.user_id` (the highest-volume table, queried by every investigation report and the logs page) — avoids full table scans as the table grows
- Request schemas now enforce `max_length` matching the DB columns, so over-length input returns 422 instead of a 500 on PostgreSQL
- Made the insightface model singleton and the embedding cache rebuild thread-safe (they are touched concurrently by the request threadpool)
- Added `.dockerignore` — the backend image no longer bakes in the host's ~700 MB dev virtualenv, and the build context no longer includes database backups
- Removed dead code (unused `refreshUser` auth-context method); the unread-notification badge no longer under-counts past 50

## [1.0.3] — 2026-07-24

HIGH-priority enterprise-readiness requirements (H1–H4). No new product features.

### Added
- **Biometric retention (H1)**: `unknown_retention_days` setting + background purge of expired unknown-person records (snapshot + embedding + row), protecting case-linked and watchlisted records, audited on every purge; `docs/DATA_RETENTION.md`
- **Stream tokens (H2)**: `POST /api/camera/stream-token` issues 60-second single-purpose tokens for the MJPEG URL; access tokens rejected on the stream, stream tokens rejected on the API; nginx logs strip query strings
- **Media backups (H3)**: daily backup service now also archives the media volume (enrollment photos + evidence snapshots); `docs/BACKUP_RESTORE.md`
- **Offsite backups (H4)**: opt-in `offsite` compose profile replicates backups to any rclone target with post-transfer verification

### Security
- Live-stream authentication no longer exposes a reusable 30-minute credential in web-server logs (H2)

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
