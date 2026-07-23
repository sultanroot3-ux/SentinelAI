# SentinelAI v1.0.4 — Release Notes

**Release date:** 2026-07-24

v1.0.4 is a hardening release: fixes from a final, from-scratch audit of the
whole codebase (backend + frontend) before freezing. No new features.

## Security & correctness fixes

- **Login timing side channel** closed — an unknown username now takes the same
  time as a real one (always runs bcrypt), so the generic error can't be
  bypassed to enumerate accounts.
- **Upload DoS** closed — all image uploads are capped at 10 MB and rejected
  before being read into memory.
- **Two authorization gaps** closed — `GET /api/settings` (channel config) and
  `GET /api/reports/visitors` (full log export) were readable by any
  authenticated user; now restricted to admin/it and admin/security_officer
  respectively, with matching nav gating.
- **Audit coverage** completed — deleting biometric evidence (unknown-face
  records) and permission denials are now logged.
- **Missing DB index** on `recognition_logs.user_id` added (highest-volume
  table; every investigation report queried it with a full scan).
- **Input validation** — request schemas enforce `max_length` matching the DB,
  turning would-be PostgreSQL 500s into clean 422s.
- **Thread-safety** — the AI model singleton and embedding cache are now locked
  against the request threadpool.
- **Image/build hygiene** — added `.dockerignore`; the backend image dropped
  the host's ~700 MB dev virtualenv it had been baking in.
- **Dead code** removed; the unread-notification badge no longer under-counts.

Verified: 141 backend tests, frontend build, full production Docker stack, CI.

---

# SentinelAI v1.0.3 — Release Notes

**Release date:** 2026-07-24

v1.0.3 completes the HIGH-priority production requirements from the engineering
review (H1–H4). No new product features.

## Enterprise-readiness hardening

- **H1 — Biometric data retention.** New `unknown_retention_days` setting
  (Settings → Data Retention; default 0 = disabled). A background job purges
  unknown-person records — snapshot, embedding, and DB row — older than the
  window; records linked to a case or on a watchlist are never purged; every
  purge is written to the audit log. Documented in `docs/DATA_RETENTION.md`.
  Verified by 7 backend tests + in-browser settings check.
- **H2 — Log-safe MJPEG authentication.** The live stream no longer accepts
  the 30-minute API access token in its URL. The dashboard fetches a
  single-purpose **60-second stream token** (`POST /api/camera/stream-token`);
  access tokens are rejected on the stream, stream tokens are rejected on the
  API. nginx additionally logs request paths without query strings. Verified
  live: access token → 401, stream token → accepted, **zero `token=` in nginx
  logs**; plus 6 backend tests.
- **H3 — Complete media backups.** The daily backup service now produces a
  matched pair — database dump **and** a media tarball (enrollment photos +
  evidence snapshots). Verified end to end with a clean-environment restore
  (DB + media into fresh volumes) and a cross-integrity check that a restored
  `photo_url` resolves to a restored file.
- **H4 — Offsite backups.** Optional `offsite` compose profile replicates
  `./backups` to any rclone-supported target (S3, SCP/SFTP, B2, GCS, Azure…)
  and **verifies every transfer** with `rclone check`. Verified: sync loop
  reported `0 differences, 4 matching files`. See `docs/BACKUP_RESTORE.md`.

Upgrade: `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.

---

# SentinelAI v1.0.2 — Release Notes

**Release date:** 2026-07-23

v1.0.2 resolves the four production blockers identified in the final
engineering review (C1–C4). No new features.

## Production fixes

- **C1 — Migrations own the production schema.** The container entrypoint now
  runs `alembic upgrade head` before starting the app and refuses to start if
  it fails; `create_all` is development-only. Existing v1.0.1 databases
  (schema built by `create_all`, no `alembic_version`) are detected and
  adopted automatically. Verified: fresh install (×3), upgrade from a real
  v1.0.1 database with data preserved, rollback + re-upgrade, and fail-fast
  on an unreachable database.
- **C2 — TLS certificates hot-reload on renewal.** A watcher inside the nginx
  container detects certificate changes on the certbot volume and reloads
  nginx with zero downtime. Verified by simulated renewal: reload logged, new
  certificate served, 40/40 requests succeeded during the swap.
- **C3 — Embedding cache is multi-worker consistent.** Every lookup checks a
  cheap DB version signature (count + max id of `face_embeddings`); workers
  that did not handle an enrollment rebuild automatically. Verified live with
  two production workers: enroll → 12/12 immediate recognitions, no restart.
- **C4 — AI engine and model ship in the image.** insightface + onnxruntime
  are now installed in the production image (previously it silently fell back
  to detection-only), with the buffalo_l model pack baked in and pinned by
  SHA-256. Verified: container starts and runs inference with networking
  disabled (`--network none`).
- Also fixed: multi-worker seed race at first startup (worker crash on
  duplicate-key) — now retried with jittered backoff; verified across three
  cold starts.

Upgrade: `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
(the entrypoint migrates automatically).

---

# SentinelAI v1.0.1 — previous release

SentinelAI is an intelligent vision security platform: real-time face
recognition on live camera streams, enterprise investigation tooling, and a
full operations dashboard — self-hosted, with all data in your own
PostgreSQL database. No external or third-party data sources are ever used.

## Highlights

### Recognition engine
- InsightFace (ArcFace `buffalo_l`) 512-d embeddings, in-memory vectorized
  matching, OpenCV fallback
- Temporal liveness (blink + non-rigid motion + head-pose micro-movement)
  on live streams; single-frame method honestly labelled on uploads
- Live MJPEG streaming with server-side AI overlays (green/red/amber)

### Enterprise Investigation System
- Full investigation reports: employee profile (database-only identity),
  camera + location, detection history, watchlist hits, snapshot
- Unknown-person pipeline: stable `UNK-xxxxxx` IDs, stored embeddings,
  similar-sighting linkage by cosine similarity
- AI attribute estimates — age, gender, head pose, face quality, blur,
  brightness, mask/glasses heuristics — every value labelled an estimate;
  attributes without a local model report `unavailable`, never guessed
- Watchlists (employees or unknowns) with alert levels; visitor management
  with check-in/out; access history timeline; RBAC catalogue; audit trail

### Dashboard
- 21 pages, React + Vite: live camera, investigation, visitors, watchlists,
  cameras & locations, roles & permissions matrix, audit log viewer, access
  history, analytics, reports (CSV/JSON/PDF/Excel), notifications, settings
- Role-gated navigation, dark/light themes, mobile responsive

### Security
- JWT access (30 min) + single-use rotating refresh tokens with server-side
  revocation; forced password change for seeded accounts
- Login rate limiting; RBAC enforced on every endpoint; full audit logging
- Biometric media served only via short-lived signed URLs
- TLS with HSTS, CSP, X-Frame-Options, nosniff, Referrer-Policy,
  Permissions-Policy

### Production operations
- One-command Ubuntu deployment (`deployment/install_ubuntu.sh`): Docker
  stack with PostgreSQL 16, non-root backend image, nginx TLS termination,
  Let's Encrypt with auto-renewal, daily gzip backups with retention,
  container healthchecks, log rotation
- Health monitoring script for cron; performance-tested (see
  `docs/PERFORMANCE.md`)
- CI: pytest against SQLite + PostgreSQL, frontend build, Docker image
  builds, production compose validation

## Quality
- **123 backend tests** (unit + integration), run in CI on SQLite and
  PostgreSQL
- Playwright E2E: all 20 authenticated pages + interaction flows verified
- Zero-trust verification pass over every feature (see
  `docs/COMPLETE_FINAL_REPORT.md`)

## Known limitations
- Emotion estimation, object detection and OCR report `unavailable` (no
  local models bundled); mask/glasses are low-confidence heuristics
- Camera Locations API supports create/list only (no rename/delete)
- AI-overlay streaming is CPU-bound at roughly 1 fps/camera on commodity
  hardware; scale workers/hardware with camera count
- Login rate limiting is tracked in-memory per worker process: with
  `UVICORN_WORKERS=N` the effective limit is 5×N failed attempts per
  15 minutes (verified against the production stack). A shared store
  (Redis) would tighten this; acceptable for the default N=2

## Upgrade / install
See `deployment/DEPLOYMENT.md` (single-command install) and
`docs/DEPLOYMENT_CHECKLIST.md` (go-live checklist).
