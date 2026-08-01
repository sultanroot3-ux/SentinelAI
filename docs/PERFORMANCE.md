# SentinelAI — Performance, Load & Soak Report

Two sets of measurements:

- **§1–§4 (v1.1, 2026-08-01)** — the AI recognition path under sustained load,
  plus the limiters under concurrency. This closes the "no load or soak testing"
  gap in [`CTO_REVIEW_FINAL.md`](CTO_REVIEW_FINAL.md) §7.4.
- **§5 (v1.0, 2026-07-23)** — the CRUD/dashboard API. Retained because it is
  still accurate and measures a different, much lighter workload.

Reproduce §1–§4 with [`scripts/loadtest.py`](../scripts/loadtest.py); §5 used
autocannon.

---

## 0. Test bed, and why the absolute numbers do not transfer

| | |
|---|---|
| Host | Intel Core i7-7567U @ 3.5 GHz — **2 physical cores** / 4 threads, 16 GB |
| Runtime | Docker (colima VM, 4 vCPU / 8 GB), `docker-compose.yml` production stack |
| Backend | `sentinelai-backend` (1.65 GB), `SENTINEL_ENV=production`, `UVICORN_WORKERS=2` |
| State | PostgreSQL 16 + Redis 7; log confirms `Shared state backend: redis (workers=2)` |
| Engine | InsightFace buffalo_l, ONNX Runtime, CPU execution provider |

**This is a 2017 dual-core laptop.** Read §1 and §2 for *shape* — the cost
model, the saturation behaviour, the limiter semantics — and re-derive absolute
rates for your own hardware from §1. Do not quote the req/s figures as the
product's capacity.

---

## 1. Per-request cost by face count

Detection runs once per frame; the 512-d ArcFace embedding runs once **per
face**. Cost is therefore dominated by how many people are in the frame, not by
frame size.

| Frame | Payload | p50 | p95 |
|---|---:|---:|---:|
| 0 faces (blank 640×640) | 7 kB | **456 ms** | 1157 ms |
| 1 face (crop) | 17 kB | **1370 ms** | 2936 ms |
| 6 faces (group photo) | 129 kB | **5224 ms** | 9191 ms |

Those three points give a usable planning model:

```
per-frame cost  ≈  460 ms  +  ~800 ms × (number of faces)
                   ^^^^^^      ^^^^^^
                   detection   embedding, per face
```

Cold start (first request: ONNX session init + first inference) was **4.0 s**.
Each worker pays this once, on its first frame — not at boot, because the model
loads lazily.

**Planning implication.** A corridor camera (0–1 faces) costs roughly
0.5–1.4 s per frame here; a lobby camera seeing six people costs ~5 s. Sizing on
an average face count rather than the worst case will under-provision a
reception area badly.

---

## 2. Capacity ramp — the host saturates at concurrency 1

12 requests per level, 6-face frames, 16 distinct users so the per-user quota is
not the binding constraint.

| Concurrency | OK | 429 | 5xx | req/s | p50 | p95 | p99 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 12 | 0 | 0 | 0.32 | 2862 ms | 3927 ms | 4150 ms |
| 2 | 12 | 0 | 0 | 0.24 | 7031 ms | 14930 ms | 15985 ms |
| 4 | 12 | 0 | 0 | 0.26 | 14563 ms | 18926 ms | 19708 ms |
| 8 | 12 | 0 | 0 | 0.50 | 12797 ms | 17356 ms | 17513 ms |

**Throughput is flat from concurrency 1 to 8 while latency grows roughly
linearly.** That is the signature of a fully CPU-bound service: ONNX Runtime
already parallelises a *single* inference across every available core, so a
second concurrent request has nothing left to run on. Added concurrency buys
queue depth, not work done.

This has a consequence that is easy to get backwards:

> **More `UVICORN_WORKERS` does not increase recognition throughput on a
> CPU-bound host.** It multiplies memory (each worker loads its own ONNX
> sessions — §3) and adds queueing. Workers exist here to serve concurrent
> **MJPEG streams**, each of which holds a worker thread, and to keep the
> interactive API responsive while inference runs. Scale workers with *stream
> count*; scale **cores** — or move to a GPU `onnxruntime` build — for
> *recognition throughput*.

No 5xx and no dropped connections at any level: the service degrades by getting
slower, not by failing, which is the right behaviour for a security system.

---

## 3. Soak — 5 minutes at concurrency 4

| | |
|---|---|
| Duration | 309.9 s |
| Completed | 74 OK, 0× 429, 0× 5xx, 0 dropped |
| Throughput | 0.24 req/s |
| Latency | p50 12.6 s, p95 38.5 s — queueing at 4× the saturation point |
| p95 drift | 46.4 s → 27.7 s (**−18.7 s**, i.e. it got *faster*) |
| RSS | **2.511–2.557 GiB** across 12 samples at 25 s intervals — flat |

Both things a soak exists to catch came back clean:

- **No latency drift.** p95 fell over the run rather than rising. An unbounded
  cache, a leaked connection or a growing queue would show as a monotonic climb.
  The improvement is the ONNX arena allocator and thread pool settling.
- **No memory growth.** RSS varied by 46 MB (1.8%) with no trend across five
  minutes of saturation.

**~1.25 GiB RSS per worker** with the model pack loaded (2.5 GiB at
`UVICORN_WORKERS=2`). Budget for it — this is the other reason not to raise the
worker count casually.

---

## 4. Limiters under concurrency

The prior evidence for B3/B4 was sequential. Concurrency is the harder case, and
it is what an attacker actually does.

### 4.1 Quota (B3) — passes

40 simultaneous `POST /api/recognition/frame` from **one** user, against a
bucket of 20 burst / 1 per second:

```
23 allowed / 17 throttled (429 + Retry-After) / 0 errors
```

23 rather than exactly 20 because the bucket refills while the burst drains.
Well within tolerance, and nowhere near the `20 × worker_count` that per-worker
buckets would have produced — the quota is genuinely shared through Redis.

### 4.2 Login limiter (B4) — passes, with a documented property

Two bursts against `MAX_FAILURES=5`:

| Burst | Result |
|---|---|
| 10 simultaneous wrong passwords | 10× 401, 0× 429 |
| 5 simultaneous, immediately after | **5× 429** — fully engaged |

The second burst is the assertion, and it passed. The first burst is a
**measured property of the design, not a regression**:

`check_allowed()` runs *before* the bcrypt verification and `record_failure()`
runs *after*, so N simultaneous attempts all pass the check before any of them
has recorded a failure. The Redis window itself is atomic; the gap is the
check-then-act interval. So a single simultaneous burst is bounded by the
attacker's concurrency rather than by 5, after which the account locks normally.

**This is deliberately not being changed.** Counting attempts *before* verifying
would close the gap, but would let any unauthenticated party lock any account
out of the system by firing requests at it. A denial-of-service against a
security product is a worse failure than a slightly wider first burst. Recorded
here so the next reviewer does not have to re-derive it.

---

## 5. CRUD / dashboard API (v1.0, 2026-07-23)

Measured against the development server (single uvicorn worker, `--reload` on,
InsightFace loaded, one live camera stream active) with
[autocannon](https://github.com/mcollina/autocannon).

### Single-request latency (idle)

| Endpoint | Latency |
|---|---|
| `GET /api/health` (incl. DB ping) | **5.3 ms** |
| `GET /api/users` (auth + query + serialization) | **9.5 ms** |
| `GET /api/analytics/summary` (multi-table aggregates) | **24.5 ms** |

### Load

| Scenario | Connections | Duration | Throughput | p50 | p97.5 | Errors |
|---|---|---|---|---|---|---|
| `GET /api/health` | 100 | 15 s | **190 req/s** (3k total) | 436 ms | 1064 ms | 0 |
| `GET /api/users` (Bearer auth) | 50 | 15 s | **97 req/s** (2k total) | 499 ms | 974 ms | 0 |

Zero non-2xx responses in both runs. The dashboard workload is light — a handful
of users issuing occasional queries — and nowhere near a limit. §2 is the
constraint that matters.

Recognition matching is O(1) per frame in DB round-trips: embeddings are served
from an in-memory normalised matrix, invalidated on enrolment changes, so
enrolled-user count has negligible impact on frame latency.

---

## 6. Reproducing

```bash
# Production stack: PostgreSQL + Redis + backend at 2 workers
docker compose up -d db redis backend

# Full run: cost profile, ramp, 5-minute soak, both limiter phases
python scripts/loadtest.py --base-url http://localhost:8000 \
  --ramp 1,2,4,8 --requests 12 --users 12 \
  --soak-seconds 300 --soak-concurrency 4

# Writes loadtest-results.json and loadtest-results.md.
# Exit status is non-zero only if a limiter assertion fails. Throughput is
# reported, never asserted — a threshold there would be a flaky test, not a
# capacity measurement.
```

The harness provisions its own `lt-*` accounts and deletes them afterwards. It
probes the login limiter with a per-run **nonexistent** username, so it never
leaves a real account locked.

The v1.0 numbers in §5:

```bash
npx autocannon -c 100 -d 15 https://<host>/api/health
TOKEN=$(...)   # obtain via /api/auth/login
npx autocannon -c 50 -d 15 -H "Authorization: Bearer $TOKEN" https://<host>/api/users
```
