# SentinelAI — Performance & Load Test Report (v1.0)

Measured 2026-07-23 against the development server (single uvicorn worker,
`--reload` on, InsightFace loaded, one live camera stream active, macOS dev
machine). Production (2+ workers, no reload, Linux) will exceed these numbers.
Tool: [autocannon](https://github.com/mcollina/autocannon).

## Single-request latency (idle)

| Endpoint | Latency |
|---|---|
| `GET /api/health` (incl. DB ping) | **5.3 ms** |
| `GET /api/users` (auth + query + serialization) | **9.5 ms** |
| `GET /api/analytics/summary` (multi-table aggregates) | **24.5 ms** |

## Load test results

| Scenario | Connections | Duration | Throughput | p50 | p97.5 | Errors |
|---|---|---|---|---|---|---|
| `GET /api/health` | 100 | 15 s | **190 req/s** (3k total) | 436 ms | 1064 ms | 0 |
| `GET /api/users` (Bearer auth) | 50 | 15 s | **97 req/s** (2k total) | 499 ms | 974 ms | 0 |

Zero non-2xx responses in both runs.

## Interpretation & capacity notes

- The dashboard workload is light: a handful of users issuing occasional
  queries. At 190 req/s sustained on one worker, interactive use is far from
  any limit.
- **The real capacity constraint is MJPEG streaming + AI inference**, not the
  API: each live stream occupies a worker thread; the AI-overlay stream runs
  CPU inference at ~1 fps/camera. Scale `UVICORN_WORKERS` with camera count
  and prefer a machine with AVX2 (or a GPU build of onnxruntime) for many
  cameras.
- Recognition matching is O(1) per frame in DB round-trips: embeddings are
  served from an in-memory normalized matrix (invalidated on enrollment
  changes), so registered-user count has negligible impact on frame latency.

## Reproducing

```bash
npx autocannon -c 100 -d 15 https://<host>/api/health
TOKEN=$(...)   # obtain via /api/auth/login
npx autocannon -c 50 -d 15 -H "Authorization: Bearer $TOKEN" https://<host>/api/users
```
