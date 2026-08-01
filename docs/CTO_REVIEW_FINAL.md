# SentinelAI — CTO Production Readiness Review (Final)

**Date:** 2026-07-26
**Branch:** `feature/e2e-playwright`
**Reviewer:** CTO
**Scope:** Resolution of blockers B1–B5 plus the secondary findings raised in the
previous review.

**Verdict: Approved for enterprise production deployment**, subject to the two
operational conditions in §8. Every claim below is backed by a command that was
actually executed; §7 lists what could *not* be verified locally and why.

---

## 1. Executive summary

| ID | Blocker | Status |
|----|---------|--------|
| **B1** | Real AI engine (InsightFace/ONNX Runtime) installed and tested in CI, not just the Haar fallback | **Resolved — verified** |
| **B2** | Pin all Python dependencies / lock file for deterministic builds | **Resolved — verified** |
| **B3** | Rate limiting on expensive AI endpoints | **Resolved — verified live** |
| **B4** | Replace per-process rate limiting and cooldowns with shared backend | **Resolved — verified live** |
| **B5** | Playwright E2E integrated into GitHub Actions on PR and push to main | **Resolved — verified green in CI on `main`** |

| Secondary finding | Status |
|---|---|
| Misleading "recognition accuracy" metric | **Resolved** (renamed `match_rate`; docs regenerated and now drift-guarded) |
| Sensitive values in logs | **Resolved** (four leak sites fixed, three of which were non-obvious) |
| Unbounded list endpoints | **Resolved** (report export capped; collections paginated) |
| Accessibility | **Substantially improved** (see §5.4) |

**Test evidence at time of sign-off**

| Suite | Result |
|---|---|
| Backend (`pytest`, SQLite + real InsightFace) | **259 passed**, 0 failed, 0 skipped, 99s |
| Playwright E2E (Chromium, production build) | **14 passed**, 1.2m |
| Frontend production build | Clean, 359 kB JS / 101 kB gzip |
| Backend production image | Built (2.23 GB at sign-off; **1.65 GB since** — §10.1); AI engine loads and infers **offline** inside the container |
| Frontend production image | Built |
| Production compose stack | Booted healthy: PostgreSQL + Redis + backend (2 workers) |
| Dependency locks | 89 requirements across 3 files — **100% pinned and hash-verified** |

---

## 2. B1 — Real AI engine in CI

**Previously:** CI never installed `insightface`/`onnxruntime`. The suite ran
against the OpenCV Haar-cascade fallback, so the recognition pipeline — the
product's entire reason to exist — was untested. A regression in embedding,
matching or thresholding would have shipped undetected.

**Now:**

- `backend/requirements-ai.in` / `.txt` pin the engine as a first-class,
  hash-verified dependency set.
- A dedicated CI job (`ai-engine-tests`) installs it, caches the ~300 MB
  `buffalo_l` pack, asserts `face_service.insightface_available()`, then runs
  the pipeline suite with `SENTINEL_REQUIRE_AI=1` — **a missing engine fails the
  build instead of silently skipping.**
- `backend/tests/test_ai_pipeline.py` (345 lines) tests real behaviour, not
  mocks: 512-d embedding shape/normalisation/determinism, detection on a group
  photo, and — most importantly — **accuracy in both error directions**:

  - *False reject:* every identity must re-match itself above 0.95 after a JPEG
    round-trip (the exact transform an enrolment photo undergoes).
  - *False accept:* no cross-identity pair may reach the 0.45 threshold.
  - *Separation:* the configured threshold must sit inside the gap with >0.4
    margin, so the number in `settings` is validated, not assumed.

  It also covers pipeline side effects (recognition logs, unknown-face records
  with stored embeddings, cooldown suppression) and liveness against genuine
  106-point landmark data.

- The `docker-build` CI job runs the engine check **inside the built image**, so
  a production container cannot quietly degrade to Haar.

**Verified.** Locally, `insightface_available()` returns `True` and the full
suite of 259 tests — including the AI pipeline — passes with the real engine.
Inside the production image:

```
AI ENGINE OK: insightface + onnxruntime, buffalo_l loaded offline
detector ran on a blank frame, returned 0 faces (expected 0)
```

The model is baked in with a pinned SHA-256, so the container needs no network
at runtime.

---

## 3. B2 — Deterministic dependencies

**Previously:** unpinned ranges meant two builds a week apart could ship
different transitive code.

**Now:** a three-layer `pip-compile` lock (`requirements`, `-dev`, `-ai`), all
generated with `--generate-hashes`. `-dev` and `-ai` are constrained by
`-c requirements.txt`, so dev, CI and production resolve to identical versions
of every shared package. Docker installs with `--require-hashes`, so a build
either reproduces the audited set exactly or fails.

Two CI guards prevent regression: one asserts every requirement is pinned *and*
hashed; the other re-runs `pip-compile` and fails if the lock has drifted from
its `.in` source.

**Verified:**

```
requirements.txt:     49 reqs, 0 unpinned/unhashed
requirements-dev.txt: 17 reqs, 0 unpinned/unhashed
requirements-ai.txt:  23 reqs, 0 unpinned/unhashed
```

The production image built successfully under `--require-hashes`, which is the
end-to-end proof that the locks are internally consistent.

---

## 4. B3 / B4 — Quotas and shared state

These are treated together because the fix for B3 is only *correct* because of
B4.

**B3 — expensive-endpoint quotas.** `/api/recognition/frame` accepts a 10 MB
upload and runs a full model inference per call. Any authenticated account could
saturate the worker pool. A per-user token bucket now guards the AI endpoints
(`recognition` 20 burst / 60 per min; `investigation` 10 / 12 per min;
`stream_token` 30 / 30 per min), returning `429` with `Retry-After`, and
auditing quota breaches.

**B4 — shared state.** Login rate limiting and pipeline cooldowns were
module-level dicts, while the shipped compose file runs `UVICORN_WORKERS=2`. The
effective login limit was therefore `5 × worker_count`, and the "one alert per
10 s" cooldown fired once per 10 s *per worker*. Both were live defects in the
shipped configuration.

`app/core/shared_state.py` introduces a Redis-backed sliding window, token bucket
and cooldown, each a **single atomic Lua script** so concurrent workers cannot
interleave a read-modify-write. Two portability hazards are handled explicitly
and documented in-file: Lua tables truncating at the first `nil`, and
`ZRANGE … WITHSCORES` returning different shapes under RESP2 vs RESP3. Redis
being unreachable degrades to per-process state with a logged error rather than
taking down login.

The app now **refuses to start** in production with `UVICORN_WORKERS > 1` and no
`SENTINEL_REDIS_URL`.

**Verified against the live production stack** (PostgreSQL + Redis + backend at
2 workers, `SENTINEL_ENV=production`):

- *B4, cross-worker login limiting:* attempts 1–5 returned `401`, attempt 6 and 7
  returned `429`. Blocked at exactly `MAX_FAILURES=5` despite two workers — the
  pre-fix behaviour would have allowed 10. State confirmed in Redis at
  `sentinelai:login:admin:172.18.0.1`.
- *B4, guard:* a production container with `UVICORN_WORKERS=2` and no Redis
  refuses to start with an actionable message.
- *B4, observability:* both workers log `Shared state backend: redis (workers=2)`.
- *B3, quota:* 40 concurrent `POST /api/recognition/frame` → **34× 200, 6× 429**,
  with quota state in Redis at `sentinelai:quota:recognition:1`.

43 unit/integration tests cover the two backends' semantics, including an
equivalence test asserting the Redis and in-memory implementations behave
identically, and an atomicity test under thread contention.

---

## 5. B5 and secondary findings

### 5.1 B5 — Playwright in CI

An `e2e-tests` job runs on every PR and push to `main`. It boots a real uvicorn
backend and serves the **production frontend bundle** (`vite preview`), not the
dev server, and uploads reports/traces on failure. The config isolates E2E onto a
disposable SQLite database deleted before each boot, and logs in through the UI
once, reusing storage state.

**Verified locally:** 14 passed in 1.2m. The run logs show the real `buffalo_l`
ONNX models loading, so E2E exercises the genuine AI path end to end.

### 5.2 Misleading metric

`recognition_accuracy` → `match_rate`. It is the share of detections that matched
an enrolled person: it has no ground truth, and a lobby full of genuine strangers
drives it down while the model performs perfectly. Calling that "accuracy"
invites a boardroom misreading of a security control.

The API, schema and dashboard were already renamed. **This review found the
published contract had not been:** `docs/openapi.json` and `docs/API_CONTRACT.md`
still advertised `recognition_accuracy` to integrators. Both are corrected, and
because a hand-maintained snapshot is what allowed the drift, `openapi.json` is
now **generated** by `scripts/export-openapi.py` and **drift-checked in CI**.

### 5.3 Sensitive values in logs

Four leaks fixed; three were not visible at the call site:

1. `shared_state.py` logged the full `SENTINEL_REDIS_URL` at INFO — production
   Redis URLs embed the password in userinfo.
2. **Telegram:** `requests` embeds the request URL in the exception it raises,
   and the bot token lives in that URL's path — so a bare
   `logger.exception("Telegram notification failed")` published the token even
   though the call site never logged it.
3. **Discord:** identical hazard; the whole webhook URL is the credential.
4. A *rejected* webhook URL was logged verbatim — still someone's credential,
   just not Discord's.

`app/core/redaction.py` provides `redact_url` (masks userinfo passwords),
`redact_endpoint` (drops credential-bearing paths, keeps the host — the question
a log reader actually has) and `scrub` (removes known secrets from third-party
exception text). SMTP failures also scrub the password.

**18 tests** cover this, including per-channel assertions that the secret is
absent from `caplog` while the diagnostic text survives. These were confirmed
non-vacuous: reverting the Telegram fix makes
`test_telegram_failure_does_not_log_the_bot_token` fail.

### 5.4 Unbounded endpoints

Collection endpoints were already bounded via `apply_limit` with `X-Total-Count`
and `X-Result-Truncated`, and the large tables (audit, access history, cases,
logs) are paginated.

This review found one genuinely unbounded path remaining: **`GET
/api/reports/visitors`** loaded every `RecognitionLog` in the period into memory
and built a PDF/XLSX from it. On a busy site a monthly export is millions of rows
— an out-of-memory vector reachable by any admin or security officer. It is now
capped at 50,000 rows and **refuses** an oversized export with `413` and the row
count rather than silently truncating: a report that looks complete and is not is
worse than no report. Covered by tests across all four formats.

*Deliberately left unpaginated:* RBAC roles/permissions, departments, camera
locations and the audit action list. These are fixed or slow-growing catalogues
(tens of rows) whose size is bounded by configuration, not by traffic. Paginating
them would add client complexity for no risk reduction.

### 5.5 Accessibility

Already in place: skip link, `:focus-visible` rings, `prefers-reduced-motion`
(WCAG 2.3.3), a full modal focus trap with focus restore and `aria-labelledby`,
and labelled nav/theme/notification controls.

This review fixed the remaining gap: **13 icon-only buttons** across Users,
Cameras, Departments, Visitors and Watchlists were named only by `title`, which
is not a reliable accessible name and is never surfaced on touch. Each now
carries an `aria-label` that **includes the row subject** — `Delete Jane Okafor`
rather than a column of twenty identical "Delete" buttons — plus an explicit
`type="button"`. The Playwright watchlist spec now targets the subject-bearing
name, so the improvement is regression-tested.

---

## 6. Additional items found and fixed during this review

- `docs/openapi.json` regenerated and CI-guarded (§5.2).
- `backend/.coverage` was untracked *and* un-ignored; coverage artifacts added to
  `.gitignore`.
- Shared-state backend selection was logged before `setup_logging()` installed
  handlers, so the message went nowhere. Startup now restates it, and escalates
  to **ERROR** if a multi-worker process is running per-worker state.
- `deploy.json` added at the repo root per instruction, describing the
  frontend/backend service split with `/api/*` routed to the backend.

---

## 7. What was *not* verified, and why

Stated plainly so the residual risk is owned rather than hidden:

> **Update — items 1 and 2 below have since been resolved.** Commit `7555352`
> ("v1.1.0: close CTO review blockers B1–B5 and hardening follow-ups") was
> pushed to `main` and CI run
> [`30195679996`](https://github.com/sultanroot3-ux/SentinelAI/actions/runs/30195679996)
> completed **successfully in 3m40s with all 7 jobs green**:
>
> | Job | Result | Duration |
> |---|---|---|
> | AI engine (insightface + ONNX Runtime) | success | 2m07s |
> | Backend (pytest, PostgreSQL + Redis) | success | 1m24s |
> | Backend (pytest, SQLite) | success | 1m05s |
> | E2E (Playwright) | success | 1m22s |
> | Docker images build | success | 3m36s |
> | Dependency locks (pinned + hashed) | success | 20s |
> | Frontend (build) | success | 17s |
>
> This means **B1, B2, B4 and B5 are now verified in CI on `main`**, not merely
> locally: the AI job proved the real engine runs with `SENTINEL_REQUIRE_AI=1`,
> the PostgreSQL + Redis job exercised the shared-state backend against a real
> Redis service container, and the Docker job verified the AI engine inside the
> built image. Items 3 and 4 below still stand.

1. ~~**GitHub Actions has not been observed executing.**~~ **Resolved** — see the
   update above. (Original note: the cold-cache `buffalo_l` download was the
   main risk; the job completed in 2m07s.)
2. ~~**The PostgreSQL + Redis CI job** was verified by proxy.~~ **Resolved** —
   it ran against a real Redis service container in CI.
3. **HTTPS / Let's Encrypt / certbot** paths in `docker-compose.prod.yml` were
   config-validated only. They need a real domain and cannot be exercised
   locally. **Still outstanding.**
4. ~~**Load and soak testing** was not performed.~~ **Resolved** — see §10.3 and
   [`PERFORMANCE.md`](PERFORMANCE.md) §1–§4.

---

## 8. Conditions of approval

Two operational conditions, neither blocking the deployment decision:

1. **Redis is now a hard production dependency** whenever `UVICORN_WORKERS > 1`.
   It must be monitored. If Redis becomes unreachable the system degrades to
   per-worker limits — it stays up, but brute-force protection weakens, and that
   degradation is logged at ERROR and must be alerted on.
2. ~~**Watch the first CI run on `main`**~~ — **satisfied.** Run `30195679996`
   passed all 7 jobs on `main` in 3m40s, including the cold-cache model
   download (2m07s). No action outstanding.

### Recommended next (not blocking)

- ~~The 2.23 GB backend image is dominated by ONNX Runtime and the model
  pack.~~ **Done** — now **1.65 GB**. See §10.1.
- ~~`datetime.utcnow()` is deprecated and used throughout.~~ **Done** — see
  §10.2. The suggested fix (aware datetimes everywhere) turned out not to be
  applicable here; the reasoning is recorded because it is the kind of thing
  that gets re-proposed.
- Add automated accessibility assertions (e.g. `axe-core` in Playwright) so a11y
  regressions are caught mechanically rather than by review. **Still open.**

---

## 9. Sign-off

All five blockers are resolved and independently verified by execution, not by
inspection. The two findings this review added — the drifted public API contract
and the credential-leaking exception logs — are also fixed and tested.

The recognition pipeline that justifies the product is now genuinely tested;
builds are reproducible; the AI endpoints cannot be trivially abused; and
multi-worker deployments enforce the limits they advertise.

**SentinelAI is approved for enterprise production deployment.**

---

## 10. Addendum — post-approval hardening (2026-08-01)

Three of the four items left open at sign-off are now closed. Each was verified
by execution, and each turned up something the original plan had not anticipated,
recorded here so it is not re-derived later.

### 10.1 Backend image: 2.23 GB → **1.65 GB**

Two independent causes, both larger than expected.

**192 MB of software OpenGL.** `insightface` hard-declares `opencv-python` — the
GUI build — which links `libGL.so.1`. On Debian trixie `libgl1` *hard*-depends on
`libglx-mesa0` → `mesa-libgallium` → `libllvm19`. A headless security appliance
was shipping LLVM and a full software rasteriser to support a `highgui` module
nothing calls; there is no `imshow`/`waitKey`/`namedWindow` anywhere in the tree.
The build now installs the audited set, uninstalls the GUI build and reinstalls
the same OpenCV version from `requirements-headless.txt` — sequentially, because
both distributions own the same `cv2/` directory and resolving them together
makes the winner depend on install order. The new lock is pinned and
hash-verified like the others, so **B2 still holds**: nothing enters the image
except from an audited lock. apt layer 229 MB → 17.9 MB.

**145 MB of unused models.** buffalo_l ships five; the app reads three. Nothing
touches `face.landmark_3d_68` (`1k3d68.onnx`, 144 MB) or `face.sex`/`face.age`
(`genderage.onnx`). `FaceAnalysis` now names its modules explicitly. That matters
beyond size: a bare `FaceAnalysis()` adapts to whatever `.onnx` files it finds,
so without the explicit list a code path using `face.sex` would work on a
developer machine with the full pack and fail *only* in production. Model layer
341 MB → 196 MB.

The prune is asserted in both directions. A silent no-op is the dangerous
outcome: if a future pack renamed `w600k_r50.onnx`, an `rm -f` of the unused
names would still succeed, the build would go green, and the missing recognition
model would surface as "nothing ever matches" — read in production as a
threshold-tuning problem, not a broken build.

*Not done:* the venv is still 811 MB and is now the bulk of the image
(`onnx`, `sympy`, `scipy`, `onnxruntime`). Trimming it means deleting from
`site-packages` after install, which breaks the B2 property that image contents
match the audited lock. Not worth that trade.

### 10.2 `datetime.utcnow()` — migrated, but not the way §8 suggested

All 28 call sites across 10 files now go through `app/core/clock.py`.

The recommendation was "migrate to timezone-aware `datetime.now(timezone.utc)`".
**That is not applicable here, and the reason should be recorded because it will
be proposed again.** SQLite backs local development, the pytest suite and the
Playwright E2E run, and SQLite has no timestamp type: SQLAlchemy formats the
value into a string and **drops `tzinfo` even when the column declares
`timezone=True`** — verified empirically. Reads come back naive regardless. Code
comparing `row.created_at` against an aware `now()` would pass on PostgreSQL and
raise `TypeError` on SQLite: a bug class visible on only one backend.

The convention is therefore the one `create_refresh_token()` already followed by
hand (`expire.replace(tzinfo=None)` before the insert), now explicit and applied
everywhere — **aware at the edges, naive UTC in the database**: `utcnow()` for
columns, `now_utc()` for JWT `exp` and other offset-aware boundaries,
`to_naive_utc()` as the one-way door (which *converts* rather than strips, so a
non-UTC input is shifted instead of silently recording the wrong instant).

Output formats are unchanged on purpose; adding a `+00:00` offset to
`generated_at` would have been a silent change to the published API contract for
no correctness gain. A CI guard fails the build on any reintroduction, and was
confirmed non-vacuous by planting a call.

### 10.3 Load and soak testing — done; full results in `PERFORMANCE.md`

`scripts/loadtest.py` measures per-request cost, ramps concurrency, soaks, and
exercises both limiters under simultaneous load. Run against the production
compose stack (PostgreSQL + Redis + backend at 2 workers). **All limiter
assertions passed.** Three findings worth surfacing here:

1. **Cost is per *face*, not per frame:** ≈ 460 ms detection + ≈ 800 ms per face.
   Sizing on an average face count rather than the worst case will
   under-provision a reception area badly.

2. **Throughput is flat from concurrency 1 to 8** while latency grows linearly —
   the service is fully CPU-bound, because ONNX Runtime already parallelises a
   single inference across every core. **This inverts the guidance in §5 of
   `PERFORMANCE.md` v1.0 and the deployment checklist:** raising
   `UVICORN_WORKERS` does *not* raise recognition throughput. It multiplies
   memory (≈ 1.25 GiB per worker) and adds queueing. Scale workers with *MJPEG
   stream count*; scale *cores* for recognition throughput.

3. **The login limiter's first burst is bounded by attacker concurrency, not by
   `MAX_FAILURES`.** 10 simultaneous wrong passwords all reached the password
   check; the next 5 were all blocked. `check_allowed()` runs before bcrypt and
   `record_failure()` after, so the window is atomic but the check-then-act
   interval is not. Deliberately not changed — counting attempts before verifying
   would let any unauthenticated party lock any account out, which is a worse
   failure for a security product. Documented as an accepted trade-off.

Soak was clean: 5 minutes at saturation, p95 *fell* (46.4 s → 27.7 s), RSS flat
within 1.8% across 12 samples, no 5xx and no dropped connections.

### 10.4 A defect this work uncovered: the image AI check never ran

§2 claimed "the `docker-build` CI job runs the engine check **inside the built
image**, so a production container cannot quietly degrade to Haar." **That claim
was not backed by the check as written.**

```
docker run --rm --entrypoint python sentinelai-backend:ci - <<'PY'
```

Without `-i`, Docker does not attach stdin. `python -` read EOF, executed
nothing and exited 0, so the step passed unconditionally from the day it was
added — including in run `30195679996`, which §7 cites as evidence. Confirmed by
planting a `SystemExit` in the heredoc and watching the step still exit 0.

Fixed with `-i`, and hardened so the failure mode cannot recur silently: the
script prints a sentinel and the step greps for it, so a check that does not run
fails the build instead of passing. It now also runs real inference on a real
photo under `--network none` — 6 faces, 512-d normalised embedding — rather than
only initialising sessions, and a companion step asserts `libgl1`, `libllvm19`,
`mesa-libgallium` and the two pruned models are absent from the image.

The B1 claim is now true. It was verified by hand on the built image while
closing §10.1; CI will verify it on the next run.

### 10.5 Still open

- **HTTPS / Let's Encrypt / certbot** (§7.3) — needs a real domain.
- **Automated accessibility assertions** (`axe-core` in Playwright) — §8.
- Absolute throughput figures in `PERFORMANCE.md` come from a 2017 dual-core
  laptop. The cost model and saturation shape transfer; the req/s numbers do
  not. Re-run `scripts/loadtest.py` on the target hardware before committing to
  a camera count.
