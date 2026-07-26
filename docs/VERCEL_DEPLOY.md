# Deploying the SentinelAI frontend to Vercel

## What Vercel can and cannot host

**Vercel hosts the React frontend only.** The backend must run on a container
platform. This is not a tuning problem — it is structural:

| Backend requirement | Vercel limit |
|---|---|
| 2.23 GB image (InsightFace + ONNX Runtime + OpenCV + `buffalo_l`) | 250 MB unzipped per function |
| Persistent disk for uploads, snapshots, `unknown_faces` | Ephemeral filesystem |
| Long-lived MJPEG stream connections | Function max duration |
| PostgreSQL + Redis (Redis is mandatory when `UVICORN_WORKERS > 1`) | Not provided; external only |
| Alembic migrations at container start | No entrypoint hook |

Run the backend with the existing `docker-compose.prod.yml` on a VM, or on
Railway / Render / Fly.io. Then point Vercel at it.

## Architecture

```
Browser ──▶ Vercel (static React bundle)
               │  /api/*  and  /static/*  rewritten server-side
               ▼
          Backend (container host)  ──▶  PostgreSQL + Redis
```

Rewrites are used rather than calling the backend directly from the browser, so
requests stay **same-origin**. That keeps CORS out of the picture and lets the
CSP stay at `connect-src 'self'`.

## One-time setup

1. **Set the backend URL.** In `frontend/vercel.json`, replace both occurrences
   of `https://REPLACE-ME.example.com` with your backend origin (no trailing
   slash), e.g. `https://api.sentinelai.example.com`:

   ```bash
   cd frontend
   sed -i '' 's|https://REPLACE-ME.example.com|https://YOUR-BACKEND-URL|g' vercel.json
   ```

2. **Log in and link the project.** These are interactive — run them yourself:

   ```bash
   vercel login
   cd frontend
   vercel link
   ```

   When prompted for the **Root Directory**, choose `frontend`. The repo root is
   not a Vite project, so a root-level link will fail to build.

3. **Deploy.**

   ```bash
   vercel          # preview URL, safe to discard
   vercel --prod   # production domain — publicly reachable
   ```

## Backend configuration required for this to work

The backend must accept the Vercel origin and see real client IPs:

- `SENTINEL_TRUSTED_PROXY_IPS` — Vercel's rewrite makes the backend see Vercel's
  egress IP, not the end user's. Login rate limiting keys on client IP, so
  leaving this unset means **every user shares one rate-limit bucket**. Set it to
  the proxy range in front of your backend.
- `SENTINEL_REDIS_URL` — mandatory whenever `UVICORN_WORKERS > 1`. The app
  refuses to start in production without it.
- `SENTINEL_SECRET_KEY` — unique, ≥32 chars (`openssl rand -hex 32`).
- `SENTINEL_DATABASE_URL` — PostgreSQL. SQLite is refused in production.

## Security notes

- `vercel.json` replicates the security headers from `docker/nginx.prod.conf.template`
  (HSTS, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy`, CSP). Keep the two in sync if either changes.
- `camera=()` in `Permissions-Policy` is correct: the browser never calls
  `getUserMedia`. Camera frames are produced by the backend and delivered as an
  MJPEG stream.
- This is a biometric system. Putting the UI on a public URL means the login page
  is publicly reachable — make sure the seeded `admin` bootstrap password has
  been changed before the first production deploy. The backend forces a change on
  first login, but do not rely on that alone.

## Note on `deploy.json`

The `deploy.json` at the repo root uses a different platform's schema
(`services` + typed `destination` objects). Vercel does not read it. It is kept
as-is; `frontend/vercel.json` is the file Vercel uses.
