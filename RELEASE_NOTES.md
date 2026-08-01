# SentinelAI v1.1.0 — Release Notes

**Release date:** 2026-08-02

v1.1.0 closes the five blockers raised by the CTO production-readiness review
(B1–B5) plus the hardening and audit follow-ups. It is the first release whose
released commit was verified end to end by a green CI run.

Full detail in [`CHANGELOG.md`](CHANGELOG.md); review evidence in
[`docs/CTO_REVIEW_FINAL.md`](docs/CTO_REVIEW_FINAL.md); current state and
remaining manual steps in [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

---

## Highlights

**The recognition pipeline is now actually tested.** CI previously ran against
the OpenCV Haar-cascade fallback — insightface was never installed, so the
product's core function was untested. A dedicated job now installs the real
engine and runs the pipeline with `SENTINEL_REQUIRE_AI=1`, asserting accuracy in
both error directions: every identity must re-match itself above 0.95 after a
JPEG round-trip, and no cross-identity pair may reach the 0.45 threshold (B1).

**Rate limits are enforced across workers.** Login limiting and pipeline
cooldowns were module-level dicts while the shipped compose file runs two
workers, so the effective login limit was `5 × worker_count` and the "one alert
per 10 s" cooldown fired once per worker. Both were live defects in the shipped
configuration. State now lives in Redis behind atomic Lua scripts, and the app
refuses to start in production with `UVICORN_WORKERS > 1` and no
`SENTINEL_REDIS_URL` (B4).

**The AI endpoints can no longer be trivially abused.** `/api/recognition/frame`
accepts a 10 MB upload and runs a full model inference per call; any
authenticated account could saturate the worker pool. Per-user token buckets now
guard the AI endpoints and return `429` with `Retry-After` (B3).

**The backend image is 26% smaller — 2.23 GB → 1.65 GB.** The GUI OpenCV build
was dragging in Mesa and LLVM (192 MB of software OpenGL, for a `highgui` module
nothing calls), and the image shipped two buffalo_l models the application never
reads (145 MB).

**Builds are reproducible.** Four `pip-compile` lock files, 91 requirements, all
pinned and hash-verified, with CI guards against drift (B2).

---

## Security fixes

- `GET /api/users` no longer discloses `must_change_password` for other
  accounts. The directory is readable by every authenticated role by design, so
  the flag told the lowest-privileged user which admin accounts were still on a
  seeded or freshly-reset password — a target list.
- Credential leaks closed in notification failure logs. `requests` embeds the
  request URL in the exception it raises, and the Telegram bot token lives in
  that URL's path — so a bare `logger.exception(...)` published the token even
  though the call site never logged it. Same hazard for Discord webhooks; SMTP
  passwords are scrubbed too.
- `GET /api/reports/visitors` is capped at 50,000 rows and refuses oversized
  exports with `413` rather than silently truncating — a report that looks
  complete and is not is worse than no report.

## Also fixed

- **A CI check that never ran.** The step meant to prove the AI engine works
  inside the shipped image used `docker run … python -` without `-i`, so the
  interpreter read EOF, executed nothing and exited 0 — it had been passing
  unconditionally since it was added. Fixed, and hardened with a sentinel the
  step greps for, so it cannot go vacuous again.
- Deprecated `datetime.utcnow()` replaced throughout by `app/core/clock.py`,
  with a CI guard against reintroduction.
- Horizontal overflow at 375 px on the dashboard and live-camera pages.
- 13 icon-only buttons given accessible names that include the row subject
  ("Delete Jane Okafor", not a column of identical "Delete" buttons).
- Flaky Redis token-bucket tests; the suite is now idempotent against a
  persistent PostgreSQL database.

## Verification

- **271 backend tests** — green in CI on SQLite and on PostgreSQL + Redis
- **14 Playwright E2E tests** against the production frontend bundle
- **All 7 CI jobs green** on the released commit, in 3m49s
- Production image verified to load the AI engine and infer **offline**
- 20 authenticated pages swept in a real browser (zero console errors, zero
  failed requests); all 32 GET endpoints probed live with zero 5xx

## Known limitations

- **Not yet validated with real camera hardware or a real HTTPS domain.** This
  release is **approved for pilot**, not general production — `PROJECT_STATUS.md`
  lists the exact remaining steps.
- Emotion estimation, object detection and OCR report `unavailable` (no local
  models bundled); mask/glasses are low-confidence heuristics.
- Camera Locations API supports create/list only (no rename/delete).
- AI-overlay streaming is CPU-bound. Recognition throughput is flat as worker
  count rises — scale `UVICORN_WORKERS` with concurrent stream count, and add
  CPU cores (or a GPU `onnxruntime` build) for throughput.
- Biometric retention defaults to `0` (disabled — records kept indefinitely).
  Set `unknown_retention_days` for your jurisdiction.
- `react-router-dom` carries advisory GHSA-qwww-vcr4-c8h2. Not exploitable here
  (RSC-mode only; this app has no router actions and no server runtime) but it
  will appear in dependency scans.

## Upgrade

Redis is now a **hard production dependency** whenever `UVICORN_WORKERS > 1`.

```bash
docker compose build backend && docker compose up -d --force-recreate backend
docker compose logs backend | grep "Shared state backend"   # must say: redis (workers=N)
```

`docker compose up` will reuse a stale local image — force the rebuild. The
absence of that log line means shared state is not in effect; treat it as a
failed deploy.

See [`docs/DEPLOYMENT_CHECKLIST_v1.1.md`](docs/DEPLOYMENT_CHECKLIST_v1.1.md) for
the go-live checklist and [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md)
for a fresh install.
