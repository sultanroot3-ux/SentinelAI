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
