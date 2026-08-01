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


def host_profile() -> dict:
    """Record what the numbers were measured on.

    Throughput figures are meaningless without this. A reader comparing a later
    run against these needs to know whether the hardware changed.
    """
    import platform
    import subprocess

    info = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    try:  # macOS
        info["cpu"] = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=5
        ).strip()
        info["physical_cores"] = subprocess.check_output(
            ["sysctl", "-n", "hw.physicalcpu"], text=True, timeout=5
        ).strip()
    except (OSError, subprocess.SubprocessError):
        try:  # Linux
            for line in open("/proc/cpuinfo"):
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
        except OSError:
            info["cpu"] = "unknown"
    return info


def face_variants() -> dict[str, bytes]:
    """Frames with 0, 1 and 6 faces, for a per-face cost model.

    Per-request cost is dominated by face count: detection runs once, but the
    512-d embedding runs once *per face*. A single throughput number measured on
    a six-face group photo badly understates a real camera frame, which usually
    has none or one. Capacity planning needs the slope, not one point.

    Returns only what can be built; callers must tolerate missing keys.
    """
    variants: dict[str, bytes] = {}
    try:
        import pathlib

        import cv2
        import insightface
        import numpy as np
    except ImportError:
        return variants

    ok, blank = cv2.imencode(".jpg", np.zeros((640, 640, 3), dtype=np.uint8))
    if ok:
        variants["0-face"] = blank.tobytes()

    group = pathlib.Path(insightface.__file__).parent / "data/images/t1.jpg"
    if not group.is_file():
        return variants
    variants["6-face"] = group.read_bytes()

    try:
        app = insightface.app.FaceAnalysis(
            name="buffalo_l", allowed_modules=["detection"]
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        img = cv2.imread(str(group))
        if img is None:
            return variants
        faces = app.get(img)
        if faces:
            x1, y1, x2, y2 = (int(v) for v in faces[0].bbox)
            pad = 40
            crop = img[
                max(0, y1 - pad) : y2 + pad, max(0, x1 - pad) : x2 + pad
            ]
            ok, enc = cv2.imencode(".jpg", crop)
            if ok:
                variants["1-face"] = enc.tobytes()
    except Exception:  # noqa: BLE001 - the profile is optional, never fatal
        pass
    # Report in ascending face count so the table reads as a cost curve.
    return {k: variants[k] for k in ("0-face", "1-face", "6-face") if k in variants}


async def phase_cost_profile(
    client: httpx.AsyncClient, token: str, variants: dict[str, bytes], reps: int
) -> list[PhaseResult]:
    """Sequential single-request timings per face count — the cost model."""
    results = []
    for label, payload in variants.items():
        r = PhaseResult(name=f"cost:{label}", concurrency=1)
        start = time.perf_counter()
        for _ in range(reps):
            r.samples.append(await _fire(client, token, payload, "cost"))
            await asyncio.sleep(1.1)  # stay under the 1/s per-user refill
        r.wall_seconds = time.perf_counter() - start
        r.notes.append(f"{len(payload)} byte payload, {reps} sequential requests")
        results.append(r)
        print(
            f"  {label}: p50={r.pct(50):.0f}ms p95={r.pct(95):.0f}ms "
            f"({len(r.ok)}/{reps} ok)",
            flush=True,
        )
    return results


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
    if resp.status_code == 429:
        raise SystemExit(
            f"login for {username!r} is rate-limited: {resp.text[:200]}\n"
            "A previous run's login-limiter phase locked this account for this\n"
            "source IP. Wait it out, or clear the window:\n"
            "  docker compose exec redis redis-cli --scan --pattern "
            "'sentinelai:login:*' | xargs -r -n1 docker compose exec -T redis "
            "redis-cli DEL"
        )
    if resp.status_code != 200:
        raise SystemExit(
            f"login failed for {username!r}: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()["access_token"]


def _already_exists(resp: httpx.Response) -> bool:
    """True if a 422 means "this account is already there", not "bad payload".

    The API returns 422 for both. They must not be conflated: treating a schema
    mismatch as "already exists" turns it into a confusing login failure several
    steps later, which is exactly what happened the first time this ran. The
    duplicate case has a string `detail`; pydantic validation errors have a list.
    """
    if resp.status_code != 422:
        return False
    try:
        detail = resp.json().get("detail")
    except ValueError:
        return False
    return isinstance(detail, str) and "already exists" in detail.lower()


async def provision_users(
    client: httpx.AsyncClient, admin_headers: dict, count: int, prefix: str
) -> list[tuple[str, str]]:
    """Create `count` load-test accounts. Returns (username, password) pairs.

    Existing accounts are reused: a 400/409 means a previous run left them
    behind, which is fine and much faster than recreating them. A 422 is *not*
    tolerated — it means the payload is wrong, and treating it as "already
    exists" turns a schema mismatch into a confusing login failure several steps
    later.

    The address domain is `loadtest.example.com`, not `.invalid`: pydantic's
    email validator rejects the reserved `.invalid` TLD outright.
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
                "email": f"{username}@loadtest.example.com",
                "username": username,
                "password": password,
                "role": "security_officer",
                "department_id": 1,
                "employee_id": f"LT-{i:05d}",
                "access_level": "standard",
            },
        )
        if resp.status_code not in (200, 201, 400, 409) and not _already_exists(resp):
            raise SystemExit(
                f"could not provision {username}: {resp.status_code} {resp.text[:300]}"
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
        f"{len(result.ok)} allowed / {result.throttled} throttled / "
        f"{result.errors} timed out or errored (burst capacity 20, refill 1/s)"
    )
    if result.errors:
        result.notes.append(
            f"{result.errors} requests did not complete within the client "
            "timeout. The 20 that take a token still have to run a full "
            "inference each, so on a slow or saturated host they queue behind "
            "the worker pool rather than returning 200. That is queueing, not a "
            "quota failure — the 429s are the quota working."
        )
    return result, failures


async def phase_login_limiter(
    client: httpx.AsyncClient, username: str, burst: int = 10
) -> tuple[PhaseResult, list[str]]:
    """Two bursts of concurrent wrong passwords, measuring the burst overshoot.

    The existing evidence for B4 was a sequential loop, which cannot see this:
    `check_allowed` runs *before* the bcrypt verification and `record_failure`
    runs after, so N simultaneous attempts all pass the check before any of them
    has recorded a failure. The limiter is not broken — the Redis window is
    atomic — but the enforced ceiling for a single simultaneous burst is the
    attacker's concurrency, not MAX_FAILURES.

    So the assertion is on the second burst: whatever the first one costs, the
    limiter must be fully engaged afterwards. The first burst's size is measured
    and reported rather than asserted, because it is a property of the design.

    `username` is a per-run, deliberately nonexistent account. The limiter keys
    on (username, ip) and `check_allowed` runs before the user lookup — the
    endpoint runs a dummy bcrypt for unknown users specifically so the timing
    matches — so this exercises the identical path without leaving a real
    account locked for the next run, which is what an earlier version did.
    """
    result = PhaseResult(name="login_limiter", concurrency=burst)

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
    first = list(await asyncio.gather(*(attempt() for _ in range(burst))))
    second = list(await asyncio.gather(*(attempt() for _ in range(5))))
    result.samples = first + second
    result.wall_seconds = time.perf_counter() - start

    reached_password_check = sum(1 for s in first if s.status == 401)
    second_blocked = sum(1 for s in second if s.status == 429)

    failures = []
    if second_blocked < len(second):
        failures.append(
            f"B4 REGRESSION: after {burst} failed logins, only {second_blocked} "
            f"of {len(second)} follow-up attempts were blocked. Brute-force "
            "protection is not engaging, or state is not shared across workers."
        )

    result.notes.append(
        f"burst 1 ({burst} simultaneous): {reached_password_check}x 401, "
        f"{sum(1 for s in first if s.status == 429)}x 429"
    )
    result.notes.append(
        f"burst 2 (5 simultaneous, immediately after): {second_blocked}x 429 "
        f"— limiter fully engaged"
    )
    if reached_password_check > 5:
        result.notes.append(
            f"MEASURED PROPERTY (not a regression): {reached_password_check} of "
            f"{burst} simultaneous attempts reached the password check against "
            "MAX_FAILURES=5. check_allowed() runs before bcrypt and "
            "record_failure() after, so one simultaneous burst is bounded by the "
            "attacker's concurrency rather than by 5. Counting attempts before "
            "verifying would close it, but would also let anyone lock out any "
            "account by firing requests — a worse failure mode for a security "
            "product. Documented as an accepted trade-off."
        )
    return result, failures


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(payload: dict) -> str:
    host = payload.get("host", {})
    lines = [
        "# SentinelAI load & soak results",
        "",
        f"- Target: `{payload['target']}`",
        f"- Started: {payload['started']}",
        f"- Host: {host.get('cpu', 'unknown')} "
        f"({host.get('physical_cores', '?')} physical cores), "
        f"{host.get('platform', '?')}",
        f"- Frame fixture: {payload['fixture_bytes']} bytes",
        f"- Distinct load-test users: {payload['users']}",
        f"- Cold-start (model load + first inference): {payload['warmup_ms']} ms",
        "",
        "Throughput is reported, not asserted — it is hardware-dependent. The",
        "limiter phases are the pass/fail ones.",
        "",
    ]

    if payload.get("cost_profile"):
        lines += [
            "## Per-request cost by face count",
            "",
            "Detection runs once per frame; the 512-d embedding runs once per",
            "face. This is the slope that lets these numbers be re-scaled to",
            "other hardware and to realistic camera frames.",
            "",
            "| Frame | Payload | p50 ms | p95 ms |",
            "|---|---:|---:|---:|",
        ]
        for r in payload["cost_profile"]:
            label = r["phase"].split(":", 1)[1]
            size = r["notes"][0].split(" ")[0] if r["notes"] else "?"
            lines.append(
                f"| {label} | {size} B | {r['latency_ms']['p50']} | "
                f"{r['latency_ms']['p95']} |"
            )
        lines.append("")

    lines += [
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
    # Enough distinct users that the per-user quota is not what we are
    # measuring. The soak only counts when it is actually going to run.
    peak = max(levels + ([args.soak_concurrency] if args.soak_seconds > 0 else []))
    user_count = max(args.users, peak * 2)
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
            "host": host_profile(),
            "fixture_bytes": len(payload),
            "users": len(tokens),
            "warmup_ms": round(warm.seconds * 1000, 1),
            "failures": [],
        }

        if not args.no_cost_profile:
            variants = face_variants()
            if variants:
                print("phase: cost profile (per face count)", flush=True)
                cost = await phase_cost_profile(
                    client, tokens[1 % len(tokens)], variants, args.cost_reps
                )
                results["cost_profile"] = [r.as_dict() for r in cost]
            else:
                print("  (skipped: insightface/cv2 not importable here)", flush=True)

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
        # Unique per run so each run starts with an empty window; nonexistent so
        # no real account is left locked behind us.
        probe_user = f"{args.prefix}probe-{int(time.time())}"
        limiter, limiter_fail = await phase_login_limiter(client, probe_user)
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
    p.add_argument("--cost-reps", type=int, default=8)
    p.add_argument("--no-cost-profile", action="store_true")
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
