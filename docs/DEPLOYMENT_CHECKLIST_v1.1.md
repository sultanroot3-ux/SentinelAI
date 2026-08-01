# SentinelAI v1.1.0 — Final Deployment Checklist

Covers what changed in v1.1.0 (blockers B1–B5) and the split
Vercel-frontend / container-backend topology. The physical-install steps
(server sizing, DNS, camera wiring, first-run configuration, operations) are
unchanged — follow [`DEPLOYMENT_CHECKLIST.md`](DEPLOYMENT_CHECKLIST.md) for
those. Rationale for every item here is in
[`CTO_REVIEW_FINAL.md`](CTO_REVIEW_FINAL.md).

---

## 0. Release gate — already satisfied

Recorded so you can confirm you are deploying the audited build, not re-run it.

- [x] Commit `7555352` on `main` ("v1.1.0: close CTO review blockers B1–B5")
- [x] CI run `30195679996` — **all 7 jobs green in 3m40s**
- [x] Backend suite 259 passed · Playwright 14 passed · locks 89/89 pinned+hashed
- [x] Production image verified to load the AI engine **offline** inside the container

If you are deploying a later commit, re-confirm CI is green for *that* commit.

---

## 1. Backend — the part that must NOT go on Vercel

The backend needs a container host (VM with `docker-compose.prod.yml`, Railway,
Render or Fly.io). It cannot run as a serverless function: 1.65 GB image,
persistent disk, long-lived MJPEG connections.

### Required environment

- [ ] `SENTINEL_SECRET_KEY` — unique, ≥32 chars (`openssl rand -hex 32`). The app
      refuses the built-in dev key in production.
- [ ] `SENTINEL_DATABASE_URL` — PostgreSQL. SQLite is refused in production.
- [ ] `SENTINEL_REDIS_URL` — **mandatory whenever `UVICORN_WORKERS > 1`.**
      Without it the app refuses to start (this is B4; per-worker rate limits
      would multiply the login allowance by the worker count).
- [ ] `SENTINEL_TRUSTED_PROXY_IPS` — set to the proxy/LB range in front of the
      backend. **If you use the Vercel rewrite, the backend sees Vercel's egress
      IP for every request; leaving this unset means every user in the world
      shares a single login rate-limit bucket.** This is the single easiest way
      to silently defeat B3/B4 in the new topology.
- [ ] `UVICORN_WORKERS` — scale with **concurrent MJPEG stream count** (each
      stream holds a worker thread), **not** with expected recognition load.
      Load testing showed recognition throughput is flat from concurrency 1 to
      8: ONNX Runtime already uses every core for a single inference, so extra
      workers add queueing and ~1.25 GiB of RSS each without doing more work.
      For recognition throughput, add **cores** or a GPU `onnxruntime` build.
      See [`PERFORMANCE.md`](PERFORMANCE.md) §2–§3.

### Post-boot verification

- [ ] `docker compose ps` — `db`, `redis`, `backend` all `healthy`
- [ ] Logs show `Shared state backend: redis (workers=N)`.
      If they show `memory` with N > 1, **stop** — limits are per-worker.
- [ ] Logs show `[entrypoint] Migrations OK.`
- [ ] `curl -sf https://<backend>/api/health` → `{"status":"ok","database":"up"}`
- [ ] **B4 live check** — 6 wrong passwords in a row:
      ```bash
      for i in $(seq 1 6); do
        curl -s -o /dev/null -w "%{http_code} " -X POST https://<backend>/api/auth/login \
          -H 'Content-Type: application/json' \
          -d '{"username":"admin","password":"wrong"}'
      done   # expect: 401 401 401 401 401 429
      ```
      A 6th `401` means shared state is not working.
- [ ] **B3 live check** — quota returns `429` with `Retry-After` under
      concurrent load on `/api/recognition/frame`.
- [ ] Redis holds `sentinelai:*` keys (`redis-cli KEYS 'sentinelai:*'`)

---

## 2. Frontend on Vercel

- [ ] **Backend URL substituted** in `frontend/vercel.json` — replace *both*
      occurrences of `https://REPLACE-ME.example.com`:
      ```bash
      cd frontend
      sed -i '' 's|https://REPLACE-ME.example.com|https://YOUR-BACKEND-URL|g' vercel.json
      ```
      ⚠️ Deploying with the placeholder still in place produces a UI that loads
      and then fails every API call.
- [ ] `vercel login` && `vercel link` — **Root Directory = `frontend`** (the repo
      root is not a Vite project and will fail to build)
- [ ] `vercel` → preview URL, smoke-tested
- [ ] `vercel --prod` → production

### Post-deploy verification

- [ ] Login page loads; logging in succeeds (proves the `/api/*` rewrite works)
- [ ] Deep link works — open `https://<vercel-domain>/watchlists` directly in a
      fresh tab (proves the SPA fallback rewrite)
- [ ] Snapshot images render (proves the `/static/*` rewrite)
- [ ] `curl -sI https://<vercel-domain> | grep -iE 'strict-transport|content-security|x-frame'`
      → HSTS, CSP and `X-Frame-Options: DENY` present
- [ ] Browser console shows **no CORS errors** — if you see any, the rewrite is
      being bypassed and requests are going cross-origin

---

## 3. Security sign-off

- [ ] Seeded `admin` bootstrap password changed (forced on first login — do not
      rely on that alone if the URL is public)
- [ ] Backend port not reachable directly from the internet; only via nginx/Vercel
- [ ] A receptionist account cannot reach admin pages (403 server-side, not just
      hidden in the UI)
- [ ] Audit Log records the actions just performed
- [ ] `.env` is `chmod 600`, backed up, and **not** in git (it is gitignored —
      verified: only `.gitkeep` files are tracked under `uploads/` and
      `unknown_faces/`; the 109 biometric JPEGs on disk are correctly ignored)
- [ ] Notification channels tested or explicitly disabled. Failures now log a
      redacted host only — **no bot token or webhook secret should ever appear in
      logs**; grep once to confirm.

---

## 4. Known gaps carried into production

From `CTO_REVIEW_FINAL.md` §7 and §10 — accepted, not blocking:

- [ ] **HTTPS / Let's Encrypt / certbot renewal** was config-validated only.
      Verify the certificate issues and renews on the real domain. **Still open.**
- [x] ~~**No load or soak testing.**~~ Done — `scripts/loadtest.py`, results in
      [`PERFORMANCE.md`](PERFORMANCE.md) §1–§4. **But the published figures come
      from a 2017 dual-core laptop.** Re-run on the target hardware before
      committing to a camera count:
      ```bash
      python scripts/loadtest.py --base-url https://<backend> --all
      ```
      Budget from §1: `≈ 460 ms + 800 ms × faces_per_frame` on that test bed,
      scaled by your CPU. Size on the *busiest* camera, not the average.
- [x] ~~`datetime.utcnow()` deprecated.~~ Migrated to `app/core/clock.py`, with
      a CI guard against reintroduction.
- [x] ~~Backend image is 2.23 GB.~~ Now **1.65 GB** (headless OpenCV, unused
      models dropped). Re-pull rather than reusing a cached tag — see below.
- [ ] **Accessibility assertions are still manual** — no `axe-core` in the E2E
      suite yet.

> ⚠️ **If you have deployed this stack before, force a rebuild.** `docker
> compose up` will happily reuse a stale local `sentinelai-backend` image. That
> bit us during load testing: the stack came up healthy and served traffic while
> running a *pre-v1.1.0* image with no `shared_state.py` in it — so none of B4
> was actually in effect, and nothing in the health check or the logs said so.
> ```bash
> docker compose build backend && docker compose up -d --force-recreate backend
> docker compose logs backend | grep "Shared state backend"   # must say: redis (workers=N)
> ```
> The absence of that log line is the tell. Treat it as a failed deploy.

---

## 5. Rollback

- [ ] Previous image tag recorded before deploy
- [ ] `docker compose down && git checkout <previous-tag> && docker compose up -d`
- [ ] Database: restore latest `pg_dump` from `./backups` (the `backup` service
      writes daily with `RETENTION_DAYS`, default 14)
- [ ] Vercel: `vercel rollback` or promote the previous deployment in the
      dashboard — instant, since the frontend is static
