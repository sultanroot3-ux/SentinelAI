#!/usr/bin/env python3
"""SentinelAI capacity, soak and limiter load test.

Closes the "no load or soak testing" gap in CTO_REVIEW_FINAL.md §7.4. Quota
*correctness* was already proven by the unit suite; this measures sustained
throughput, finds the saturation point, and checks the limiters still behave
when they are under real concurrent pressure rather than a sequential loop.

Design notes
------------
**Why a bespoke asyncio harness and not k6/Locust.** Every dependency in this
repo is pinned and hash-verified (B2). Introducing a load tool would either add
an unpinned binary to the release process or a large new dependency tree for a
tool used a handful of times a year. This needs only `httpx`, which is already
in requirements-dev.txt.

**Why a pool of users.** `/api/recognition/frame` is quota-limited *per user*
(20 burst, then 1/s — see app/core/rate_limit.py QUOTAS). A single account can
therefore never offer more than ~1 req/s sustained, so a naive load test does
not measure the server at all: it measures the token bucket, and reports the
box as capable of 60 requests a minute. The harness provisions enough distinct
users that the quota is not the binding constraint, and says so in the report.
That is also the honest shape of the production question, which is not "how
fast is the server" but "how many concurrent operators and cameras can it
serve".

**Why the fixture is insightface's own sample photo.** Same reason as the test
suite: real detection and embedding cost is what we want to measure, and no
biometric data should be committed to this repository.

Usage
-----
    # against the production compose stack
    python scripts/loadtest.py --base-url http://localhost:8000 --all

    # just the capacity ramp
    python scripts/loadtest.py --ramp 1,2,4,8,16,32 --requests 60

    # a 10-minute soak at the level the ramp identified
    python scripts/loadtest.py --soak-seconds 600 --soak-concurrency 8

Exit status is non-zero if a limiter assertion fails. Throughput numbers are
reported, never asserted — they are hardware-dependent, and a threshold here
would be a flaky test rather than a capacity measurement.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover - operator-facing message
    sys.exit("httpx is required: pip install -r backend/requirements-dev.txt")


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    status: int
    seconds: float


@dataclass
class PhaseResult:
    name: str
    concurrency: int
    samples: list[Sample] = field(default_factory=list)
    wall_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> list[Sample]:
        return [s for s in self.samples if s.status == 200]

    @property
    def throttled(self) -> int:
        return sum(1 for s in self.samples if s.status == 429)

    @property
    def errors(self) -> int:
        return sum(1 for s in self.samples if s.status >= 500 or s.status == 0)

    def pct(self, q: float) -> float:
        """Latency percentile over successful requests, in milliseconds."""
        lat = sorted(s.seconds for s in self.ok)
        if not lat:
            return float("nan")
        # Nearest-rank: with ~60 samples, interpolation invents precision the
        # sample size does not support.
        idx = min(len(lat) - 1, max(0, round(q / 100 * len(lat)) - 1))
        return lat[idx] * 1000

    def as_dict(self) -> dict:
        return {
            "phase": self.name,
            "concurrency": self.concurrency,
            "requests": len(self.samples),
            "ok": len(self.ok),
            "throttled_429": self.throttled,
            "errors": self.errors,
            "wall_seconds": round(self.wall_seconds, 2),
            "throughput_rps": round(len(self.ok) / self.wall_seconds, 2)
            if self.wall_seconds
            else 0.0,
            "latency_ms": {
                "p50": round(self.pct(50), 1),
                "p95": round(self.pct(95), 1),
                "p99": round(self.pct(99), 1),
                "max": round(max((s.seconds for s in self.ok), default=0) * 1000, 1),
            },
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def frame_bytes() -> bytes:
    """A real multi-face photo, from the installed insightface package.

    Falls back to a synthetic frame only if insightface is absent — and says so
    loudly, because a blank frame skips the embedding stage entirely and would
    overstate throughput by a wide margin.
    """
    try:
        import insightface

        path = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"
        if path.is_file():
            return path.read_bytes()
    except ImportError:
        pass

    print(
        "WARNING: insightface not importable — falling back to a synthetic blank\n"
        "         frame. Detection will find no faces and skip embedding, so the\n"
        "         numbers below are NOT representative of production cost.",
        file=sys.stderr,
    )
    import io
    import struct
    import zlib

    # Minimal 640x640 black PNG, no third-party encoder needed.
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    w = h = 640
    raw = b"".join(b"\x00" + b"\x00" * (w * 3) for _ in range(h))
    buf = io.BytesIO()
    buf.write(b"\x89PNG\r\n\x1a\n")
    buf.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
    buf.write(chunk(b"IDAT", zlib.compress(raw, 6)))
    buf.write(chunk(b"IEND", b""))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Session setup
# ---------------------------------------------------------------------------


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    if resp.status_code != 200:
        raise SystemExit(
            f"login failed for {username!r}: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()["access_token"]


async def provision_users(
    client: httpx.AsyncClient, admin_headers: dict, count: int, prefix: str
) -> list[tuple[str, str]]:
    """Create `count` load-test accounts. Returns (username, password) pairs.

    Existing accounts are reused: a 400/409 means a previous run left them
    behind, which is fine and much faster than recreating them.
    """
    password = "loadtest-pass-8842"
    created = []
    for i in range(count):
        username = f"{prefix}{i:03d}"
        resp = await client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "name": f"Load Test {i:03d}",
                "email": f"{username}@loadtest.invalid",
                "username": username,
                "password": password,
                "role": "security_officer",
                "department_id": 1,
                "employee_id": f"LT-{i:05d}",
                "access_level": "standard",
            },
        )
        if resp.status_code not in (200, 201, 400, 409, 422):
            raise SystemExit(
                f"could not provision {username}: {resp.status_code} {resp.text[:200]}"
            )
        created.append((username, password))
    return created


async def cleanup_users(
    client: httpx.AsyncClient, admin_headers: dict, prefix: str
) -> int:
    # /api/users is capped at MAX_PAGE_LIMIT=1000, so one page is not
    # guaranteed to hold every account. Sweep until a pass deletes nothing;
    # the round cap stops a server-side failure turning this into a spin.
    removed = 0
    for _ in range(20):
        resp = await client.get(
            "/api/users", headers=admin_headers, params={"limit": 1000}
        )
        if resp.status_code != 200:
            break
        targets = [
            u for u in resp.json()
            if str(u.get("username", "")).startswith(prefix)
        ]
        if not targets:
            break
        before = removed
        for user in targets:
            d = await client.delete(f"/api/users/{user['id']}", headers=admin_headers)
            removed += 1 if d.status_code in (200, 204) else 0
        if removed == before:  # nothing deletable — stop rather than loop
            break
    return removed


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------


async def _fire(
    client: httpx.AsyncClient, token: str, payload: bytes, camera: str
) -> Sample:
    start = time.perf_counter()
    try:
        resp = await client.post(
            "/api/recognition/frame",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("frame.jpg", payload, "image/jpeg")},
            params={"camera": camera},
        )
        status = resp.status_code
    except httpx.HTTPError:
        status = 0
    return Sample(status=status, seconds=time.perf_counter() - start)


async def run_level(
    client: httpx.AsyncClient,
    tokens: list[str],
    payload: bytes,
    concurrency: int,
    total: int,
    name: str,
) -> PhaseResult:
    """Fire `total` requests at fixed `concurrency`, round-robin across tokens."""
    result = PhaseResult(name=name, concurrency=concurrency)
    queue: asyncio.Queue[int] = asyncio.Queue()
    for i in range(total):
        queue.put_nowait(i)

    async def worker(slot: int) -> None:
        while True:
            try:
                i = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            token = tokens[i % len(tokens)]
            result.samples.append(
                await _fire(client, token, payload, f"loadtest-{slot}")
            )

    start = time.perf_counter()
    await asyncio.gather(*(worker(s) for s in range(concurrency)))
    result.wall_seconds = time.perf_counter() - start
    return result


async def phase_ramp(
    client: httpx.AsyncClient,
    tokens: list[str],
    payload: bytes,
    levels: list[int],
    per_level: int,
) -> list[PhaseResult]:
    results = []
    for c in levels:
        print(f"  ramp: concurrency={c} requests={per_level} ...", flush=True)
        r = await run_level(client, tokens, payload, c, per_level, "ramp")
        if r.throttled:
            r.notes.append(
                f"{r.throttled} requests were quota-limited; the offered rate "
                f"exceeded 1 req/s for at least one of the {len(tokens)} users. "
                "Throughput here is quota-bound, not server-bound."
            )
        results.append(r)
        print(
            f"    -> {r.as_dict()['throughput_rps']} req/s  "
            f"p50={r.pct(50):.0f}ms p95={r.pct(95):.0f}ms "
            f"429={r.throttled} err={r.errors}",
            flush=True,
        )
        await asyncio.sleep(2)  # let the token buckets refill between levels
    return results


async def phase_soak(
    client: httpx.AsyncClient,
    tokens: list[str],
    payload: bytes,
    concurrency: int,
    seconds: int,
) -> PhaseResult:
    """Sustained load, reporting latency drift between the first and last third.

    Drift is the point: a memory leak, an unbounded cache or a connection pool
    that never recycles shows up as a rising p95 long before it shows up as an
    error, and a test that only reports an average would miss it entirely.
    """
    result = PhaseResult(name="soak", concurrency=concurrency)
    deadline = time.perf_counter() + seconds
    counter = 0
    lock = asyncio.Lock()

    async def worker(slot: int) -> None:
        nonlocal counter
        while time.perf_counter() < deadline:
            async with lock:
                i = counter
                counter += 1
            result.samples.append(
                await _fire(client, tokens[i % len(tokens)], payload, f"soak-{slot}")
            )

    start = time.perf_counter()
    await asyncio.gather(*(worker(s) for s in range(concurrency)))
    result.wall_seconds = time.perf_counter() - start

    if result.throttled:
        result.notes.append(
            f"{result.throttled} of {len(result.samples)} requests were "
            f"quota-limited: the sustained rate exceeded 1 req/s for some of the "
            f"{len(tokens)} users. Re-run with a larger --users to measure the "
            "server rather than the token bucket."
        )

    ok = [s.seconds for s in result.ok]
    if len(ok) >= 30:
        third = len(ok) // 3
        first_p95 = statistics.quantiles(ok[:third], n=20)[18] * 1000
        last_p95 = statistics.quantiles(ok[-third:], n=20)[18] * 1000
        drift = last_p95 - first_p95
        result.notes.append(
            f"p95 drift over the run: {first_p95:.0f}ms -> {last_p95:.0f}ms "
            f"({drift:+.0f}ms). Sustained upward drift indicates a leak or "
            f"unbounded growth; flat is healthy."
        )
    return result


async def phase_quota(
    client: httpx.AsyncClient, token: str, payload: bytes
) -> tuple[PhaseResult, list[str]]:
    """One user, 40 concurrent frames. Expect ~20 through, the rest 429."""
    result = PhaseResult(name="quota", concurrency=40)
    start = time.perf_counter()
    result.samples = list(
        await asyncio.gather(
            *(_fire(client, token, payload, "quota") for _ in range(40))
        )
    )
    result.wall_seconds = time.perf_counter() - start

    failures = []
    if result.throttled == 0:
        failures.append(
            "B3 REGRESSION: 40 concurrent recognition calls from one user "
            "produced no 429. The per-user quota is not being enforced."
        )
    # Burst capacity is 20 with 1/s refill, so a handful more than 20 can pass
    # depending on how long the burst takes to drain. Far more than that means
    # the bucket is not shared across workers.
    if len(result.ok) > 30:
        failures.append(
            f"B4 SUSPECT: {len(result.ok)} of 40 succeeded against a burst "
            "capacity of 20. If the backend runs multiple workers this suggests "
            "per-worker buckets, i.e. SENTINEL_REDIS_URL is not in effect."
        )
    result.notes.append(
        f"{len(result.ok)} allowed / {result.throttled} throttled "
        f"(burst capacity is 20, refill 1/s)"
    )
    return result, failures


async def phase_login_limiter(
    client: httpx.AsyncClient, username: str
) -> tuple[PhaseResult, list[str]]:
    """10 concurrent wrong passwords. Expect 401s then 429s, blocked at 5.

    The existing evidence for B4 was a sequential loop. Concurrency is the
    harder case: a read-modify-write limiter can let all ten through when they
    arrive at once, and that is precisely the shape of a real credential-stuffing
    attempt.
    """
    result = PhaseResult(name="login_limiter", concurrency=10)

    async def attempt() -> Sample:
        start = time.perf_counter()
        try:
            resp = await client.post(
                "/api/auth/login",
                json={"username": username, "password": "definitely-wrong"},
            )
            status = resp.status_code
        except httpx.HTTPError:
            status = 0
        return Sample(status=status, seconds=time.perf_counter() - start)

    start = time.perf_counter()
    result.samples = list(await asyncio.gather(*(attempt() for _ in range(10))))
    result.wall_seconds = time.perf_counter() - start

    unauthorized = sum(1 for s in result.samples if s.status == 401)
    failures = []
    if result.throttled == 0:
        failures.append(
            "B4 REGRESSION: 10 concurrent failed logins produced no 429. "
            "Brute-force protection is not engaging under concurrency."
        )
    elif unauthorized > 7:
        failures.append(
            f"B4 SUSPECT: {unauthorized} of 10 concurrent attempts reached the "
            "password check against a limit of 5. The limiter is probably doing "
            "a non-atomic read-modify-write, or state is per-worker."
        )
    result.notes.append(
        f"{unauthorized}x 401, {result.throttled}x 429 "
        "(MAX_FAILURES=5; a few extra 401s can race in before the 5th is recorded)"
    )
    return result, failures


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(payload: dict) -> str:
    lines = [
        "# SentinelAI load & soak results",
        "",
        f"- Target: `{payload['target']}`",
        f"- Started: {payload['started']}",
        f"- Frame fixture: {payload['fixture_bytes']} bytes",
        f"- Distinct load-test users: {payload['users']}",
        "",
        "Throughput is reported, not asserted — it is hardware-dependent. The",
        "limiter phases are the pass/fail ones.",
        "",
        "## Capacity ramp",
        "",
        "| Concurrency | Requests | OK | 429 | 5xx | req/s | p50 ms | p95 ms | p99 ms |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in payload["ramp"]:
        lat = r["latency_ms"]
        lines.append(
            f"| {r['concurrency']} | {r['requests']} | {r['ok']} | "
            f"{r['throttled_429']} | {r['errors']} | {r['throughput_rps']} | "
            f"{lat['p50']} | {lat['p95']} | {lat['p99']} |"
        )

    if payload.get("soak"):
        s = payload["soak"]
        lines += [
            "",
            "## Soak",
            "",
            f"- Concurrency {s['concurrency']} for {s['wall_seconds']}s",
            f"- {s['ok']} OK, {s['throttled_429']}x 429, {s['errors']}x 5xx",
            f"- {s['throughput_rps']} req/s, p50 {s['latency_ms']['p50']} ms, "
            f"p95 {s['latency_ms']['p95']} ms",
        ]
        lines += [f"- {n}" for n in s["notes"]]

    for key, title in (("quota", "Quota (B3)"), ("login_limiter", "Login limiter (B4)")):
        if payload.get(key):
            p = payload[key]
            lines += ["", f"## {title}", ""]
            lines += [f"- {n}" for n in p["notes"]]

    lines += ["", "## Verdict", ""]
    if payload["failures"]:
        lines += [f"- **FAIL** {f}" for f in payload["failures"]]
    else:
        lines.append("- All limiter assertions passed.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    levels = [int(x) for x in args.ramp.split(",") if x.strip()]
    # Enough distinct users that the per-user quota is not what we are measuring.
    user_count = max(args.users, max(levels + [args.soak_concurrency]) * 2)
    payload = frame_bytes()

    timeout = httpx.Timeout(args.timeout, connect=10.0)
    limits = httpx.Limits(
        max_connections=max(levels + [args.soak_concurrency, 40]) + 10,
        max_keepalive_connections=64,
    )

    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=timeout, limits=limits
    ) as client:
        health = await client.get("/api/health")
        print(f"health: {health.status_code} {health.text[:120]}")
        if health.status_code != 200:
            return 2

        admin_token = await login(client, args.admin_user, args.admin_password)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        print(f"provisioning {user_count} load-test users ...", flush=True)
        creds = await provision_users(client, admin_headers, user_count, args.prefix)
        tokens = [await login(client, u, p) for u, p in creds]
        print(f"  {len(tokens)} tokens", flush=True)

        # First inference loads the ONNX sessions; excluded so the ramp is not
        # skewed by a one-off multi-second model load.
        print("warmup (loads the model) ...", flush=True)
        warm = await _fire(client, tokens[0], payload, "warmup")
        print(f"  warmup: {warm.status} in {warm.seconds * 1000:.0f}ms", flush=True)

        results: dict = {
            "target": args.base_url,
            "started": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "fixture_bytes": len(payload),
            "users": len(tokens),
            "warmup_ms": round(warm.seconds * 1000, 1),
            "failures": [],
        }

        print("phase: capacity ramp", flush=True)
        ramp = await phase_ramp(client, tokens, payload, levels, args.requests)
        results["ramp"] = [r.as_dict() for r in ramp]

        if args.soak_seconds > 0:
            print(
                f"phase: soak ({args.soak_seconds}s @ {args.soak_concurrency})",
                flush=True,
            )
            soak = await phase_soak(
                client, tokens, payload, args.soak_concurrency, args.soak_seconds
            )
            results["soak"] = soak.as_dict()
            for n in soak.notes:
                print(f"  {n}", flush=True)

        print("phase: quota (B3)", flush=True)
        await asyncio.sleep(25)  # let the first user's bucket refill
        quota, quota_fail = await phase_quota(client, tokens[0], payload)
        results["quota"] = quota.as_dict()
        results["failures"] += quota_fail
        print(f"  {quota.notes[0]}", flush=True)

        print("phase: login limiter (B4)", flush=True)
        limiter, limiter_fail = await phase_login_limiter(client, creds[0][0])
        results["login_limiter"] = limiter.as_dict()
        results["failures"] += limiter_fail
        print(f"  {limiter.notes[0]}", flush=True)

        if not args.keep_users:
            print("cleaning up load-test users ...", flush=True)
            removed = await cleanup_users(client, admin_headers, args.prefix)
            print(f"  removed {removed}", flush=True)

    Path(args.json_out).write_text(json.dumps(results, indent=2) + "\n")
    Path(args.md_out).write_text(render_markdown(results))
    print(f"\nwrote {args.json_out} and {args.md_out}")

    for f in results["failures"]:
        print(f"FAIL: {f}", file=sys.stderr)
    return 1 if results["failures"] else 0


def main() -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--admin-user", default="admin")
    p.add_argument("--admin-password", default="admin123")
    p.add_argument("--prefix", default="lt-", help="username prefix for test accounts")
    p.add_argument("--users", type=int, default=8)
    p.add_argument("--ramp", default="1,2,4,8,16")
    p.add_argument("--requests", type=int, default=40, help="requests per ramp level")
    p.add_argument("--soak-seconds", type=int, default=0)
    p.add_argument("--soak-concurrency", type=int, default=8)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--keep-users", action="store_true")
    p.add_argument("--json-out", default="loadtest-results.json")
    p.add_argument("--md-out", default="loadtest-results.md")
    p.add_argument("--all", action="store_true", help="ramp + a 300s soak")
    args = p.parse_args()

    if args.all and args.soak_seconds == 0:
        args.soak_seconds = 300

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
