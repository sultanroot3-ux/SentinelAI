# SentinelAI — Project Status

**Version:** 1.1.0 · **Status:** Approved for pilot · **Updated:** 2026-08-02

Every figure below was produced by running something, not by inspection. Where
something could not be executed it says **Not verified** and why. Read that
literally: it means no evidence exists, not that it is expected to fail.

---

## 1. Current version

| Source | Value |
|---|---|
| `backend/app/core/config.py` → `APP_VERSION` | **1.1.0** |
| `docs/openapi.json` → `info.version` | **1.1.0** |
| `frontend/package.json` → `version` | **1.1.0** |
| `CHANGELOG.md` (top entry) | **1.1.0** |
| `RELEASE_NOTES.md` | **1.1.0** |

`APP_VERSION` is the single source of truth; it reaches the published API
contract via `FastAPI(version=...)`. A CI step asserts all five agree, because
before v1.1.0 they did not: the contract advertised FastAPI's default `0.1.0`
while `package.json` said `1.0.0` and the newest tag was `v1.0.4`.

---

## 2. Features implemented

**Recognition**
- InsightFace/ArcFace 512-d embeddings via ONNX Runtime, `buffalo_l` baked into
  the image (no runtime download, works fully offline)
- Cosine matching against an in-memory normalised matrix — O(1) DB round-trips
  per frame regardless of enrolled-user count
- Liveness detection from 106-point landmarks
- Unknown-face capture with snapshot + embedding, and per-camera cooldown

**Operations**
- Live MJPEG camera feed, with an optional AI-overlay variant
- Employee enrolment with photo upload; visitor registration and check-in/out
- Watchlists, cases, unknown-visitor triage, access history
- Investigation tool: per-employee and per-unknown reports, live frame analysis
- Analytics (summary, daily, peak hours, per-camera) and report export
  (CSV/PDF/XLSX, capped at 50,000 rows)
- Notifications via SMTP, Telegram and Discord

**Platform**
- JWT auth with refresh-token rotation and single-use revocation
- RBAC across four roles, enforced server-side
- Redis-backed shared state for rate limits, quotas and cooldowns
- Full audit log; configurable biometric retention purge
- Alembic migrations applied at container start, failing the boot on error

---

## 3. Verified — by execution

| Area | Evidence |
|---|---|
| Backend suite | **271 tests passed** — SQLite, and PostgreSQL 16 + Redis 7 |
| E2E | **14 Playwright tests passed** against the production frontend bundle |
| CI | **All 7 jobs green** on the released commit, 3m49s (run `30714812120`) |
| AI engine in the shipped image | `ENGINE_CHECK_PASSED` in CI: 6 faces detected, 512-d normalised embedding, under `--network none` |
| Recognition accuracy | Both error directions asserted: self-match > 0.95 after JPEG round-trip; no cross-identity pair reaches the 0.45 threshold |
| Quota (B3) | 40 concurrent frames from one user → 23 allowed / 17 × `429`, shared through Redis |
| Login limiter (B4) | Blocked at `MAX_FAILURES` across 2 workers; a follow-up burst is fully refused |
| UI | 20 authenticated routes swept in real Chromium — **zero** console errors, uncaught exceptions or failed requests |
| Interactions | 74 buttons clicked, 30 modals opened/closed, 7 search inputs, 10 filters — zero errors |
| API surface | All **32 GET endpoints** probed live — **zero 5xx** |
| Responsive / theme | Clean at 375 / 768 / 1440 px; dark–light toggle persists across reload |
| RBAC | As a real receptionist: `403` on audit, settings, watchlists, reports and `POST /api/users`; `401` unauthenticated |
| Docker | 1.65 GB backend, runs as uid 10001, prod compose config valid |
| Dependency locks | 91 requirements across 4 files, all pinned and hash-verified, drift-checked |
| Camera streaming | Source open, plain MJPEG, **AI-overlay MJPEG**, slot release, and recognition side effects — exercised against a synthetic video source |
| Stream cap logic | Refuses beyond 4 per process, releases fully, over-release clamped |

---

## 4. Remaining manual verification

These are the only blockers between "pilot" and "general production". Each has
an explicit pass criterion.

1. **Real camera hardware.** Set `camera_source` to a device index or
   `rtsp://…`. Confirm the feed renders, then leave it streaming **≥4 hours**
   and confirm no worker leak (active stream count returns to 0 after clients
   close). Pull the cable; confirm it recovers.
   *Why it matters:* this is the product's core function, and it has only been
   exercised with a synthetic file source.

2. **Stream cap end to end.** Open 9+ concurrent live views against the real
   (infinite) feed. Expect **`503` + `Retry-After`** past 4 per worker.
   *Why separately:* a finite file terminates at EOF, so it cannot hold a slot
   long enough to reach the cap. Only the cap *logic* is verified today.

3. **HTTPS on a real domain.** Point DNS, run `docker-compose.prod.yml`, confirm
   the certificate issues. Then `certbot renew --force-renewal` and confirm
   nginx hot-reloads without dropping connections.

4. **Re-run the load test on the pilot host** (`scripts/loadtest.py`). The
   published figures were measured on a CPU that was thermally throttled to 25%
   and are likely wrong.

5. **Set `SENTINEL_TRUSTED_PROXY_IPS`.** Behind a proxy, leaving it unset
   collapses per-client login rate limiting into one global bucket.

6. **Set `unknown_retention_days`** to a finite value for your jurisdiction.

---

## 5. Known limitations

- **Not validated on real camera hardware or a real HTTPS domain** (§4).
- Emotion estimation, object detection and OCR report `unavailable` — no local
  models are bundled. Mask/glasses are low-confidence heuristics.
- Camera Locations API supports create/list only (no rename/delete).
- Recognition throughput is **flat as worker count rises** — ONNX Runtime
  already uses every core for a single inference. Scale `UVICORN_WORKERS` with
  concurrent MJPEG stream count; add CPU cores or a GPU `onnxruntime` build for
  throughput. Budget ~1.25 GiB RSS per worker.
- Biometric retention defaults to `0` (disabled — kept indefinitely).
- `GET /api/users` is readable by every authenticated role by design (a
  receptionist needs the directory). It exposes staff email, phone, badge number
  and access level. Password state is no longer disclosed.
- The login limiter's **first** simultaneous burst is bounded by attacker
  concurrency rather than `MAX_FAILURES`: `check_allowed()` runs before bcrypt
  and `record_failure()` after. Deliberately unchanged — counting attempts
  before verifying would let anyone lock any account out.
- `react-router-dom` carries GHSA-qwww-vcr4-c8h2. **Not exploitable here**
  (RSC-mode only; this app has no router actions and no server runtime), but it
  appears in dependency scans.
- `GET /api/departments/{id}` has no UI consumer and no automated test.
- Frontend ships one 359 kB eager bundle (101 kB gzipped); no route-level code
  splitting.

---

## 6. Roadmap — v1.1.x and beyond

**Next (v1.1.x)**
- Complete the pilot validation in §4 and promote to general production
- `axe-core` in the E2E suite so accessibility regressions fail mechanically
- A finite default for `unknown_retention_days` (privacy by default)
- Test coverage for `GET /api/departments/{id}`
- Camera Locations rename/delete

**Later**
- Multi-camera concurrency and a GPU `onnxruntime` build
- Route-level code splitting
- Object detection · license plate recognition · QR / RFID
- Voice recognition · cloud sync · mobile app

---

## 7. Project statistics

| Metric | Value |
|---|---|
| Backend tests | **271** across 24 files |
| E2E tests | **14** across 9 specs |
| API routes | **65** (32 GET, all probed live) |
| Frontend routes | **22** (21 pages + login) |
| React components | 12 |
| Backend Python | 6,266 lines (`backend/app`) |
| Frontend source | 7,623 lines (`frontend/src`) |
| Alembic migrations | 4 |
| Documentation | 15 files in `docs/` + 6 at the root |
| CI jobs | **7**, green on the released commit |
| Dependency locks | 91 requirements, 4 files, pinned + hash-verified |
| Backend image | **1.65 GB** (was 2.23 GB) |
| Frontend image | 74.1 MB |
| Commits | 28 |

---

## 8. Verdict

**Approved for pilot.** Not approved for general production until §4 items 1–3
are complete.

The reasoning is in `docs/CTO_REVIEW_FINAL.md`. In short: defect density is low
and the test suite is meaningful rather than decorative, but the paths that
matter most to a camera security product — real hardware and real TLS — have no
execution evidence behind them. That is a gap a pilot closes, not more desk
review.
