# SentinelAI — Testing Guide

How to verify every subsystem. All commands assume the backend is running on
`http://127.0.0.1:8000` (use `127.0.0.1`, not `localhost` — on some macOS
setups `localhost` resolves to IPv6 first and curl fails with exit code 7).

## 1. Get a token

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

Expected: a JWT. Wrong password → `401 {"detail": ...}`.

## 2. Endpoint smoke test

```bash
for ep in users departments logs unknown cases analytics/summary \
          analytics/daily analytics/peak-hours analytics/cameras \
          notifications settings camera/status auth/me; do
  printf '%-24s %s\n' "$ep" \
    "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" \
        http://127.0.0.1:8000/api/$ep)"
done
```

Expected: all `200`. Without the header everything must return `401`.

## 3. Face registration + recognition

1. Create a user (Users page or `POST /api/users`).
2. Upload a clear frontal photo: `POST /api/users/{id}/photo` (multipart `file`).
   Response must show `"face_registered": true`.
3. Send a test frame:

```bash
curl -s -X POST http://127.0.0.1:8000/api/recognition/frame \
  -H "Authorization: Bearer $TOKEN" -F "file=@photo.jpg"
```

Expected with insightface installed: each face gets `box`, `confidence`,
`score`, and `match` (the registered user, cosine score ≳ 0.5 for the same
person; unrelated faces score ≈ 0). Without insightface: faces are detected
with a `note` explaining recognition is unavailable.

Verified result on the insightface sample image (6 faces, 1 registered):
registered person matched at **0.983**, all others correctly unknown (< 0.08).

4. Side effects: `GET /api/logs` gains a row for the match; `GET /api/unknown`
   gains snapshots for unmatched faces (rate-limited to 1 per 10 s);
   an alert notification appears if `notify_on_unknown` is on.

## 4. Unknown → Case workflow

```bash
curl -s -X POST http://127.0.0.1:8000/api/cases \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"unknown_face_id":1,"priority":"high","notes":"...","assigned_to":1}'
```

Expected: `CASE-0001` with snapshot inherited from the unknown face.
Then close it with `PUT /api/cases/1` `{"status":"closed","resolution":"..."}`.

## 5. Camera

- `GET /api/camera/status` → `{"available": true|false, "source": "0"}`
- Stream (raw): open `http://127.0.0.1:8000/api/camera/stream?token=$TOKEN`
- Stream (AI overlay): append `&analyze=1` — recognized faces get green
  boxes/names, unknowns red, liveness-pending amber.
- macOS: `available: false` + log line *"not authorized to capture video"*
  means the terminal app lacks camera permission (see INSTALL.md §3).

## 6. Liveness (blink + motion + head pose)

The `LivenessMonitor` combines three temporal signals on the AI-overlay
stream: blink detection (eye-openness from the 106-point landmarks — left eye
contour indices 33–42, right 87–96, verified empirically), non-rigid keypoint
motion, and head-pose micro-variation (pitch/yaw/roll std). Verdict = live if
a blink is seen OR both motion signals exceed threshold.

Automated check (synthetic sequences — static photo, handheld photo, live
face with blink):

```bash
backend/.venv/bin/python <scratch>/test_liveness.py   # all 3 scenarios PASS
```

Manual check: enable `liveness_enabled` in Settings, open the AI-overlay
stream, hold a printed photo in front of the camera — it is flagged within
~2 s (no blink, rigid motion). A live face passes on the first blink.
Single-frame API calls report `method: "single-frame"` (no temporal context).

## 6b. Notifications (SMTP / Telegram / Discord)

Verified end-to-end with local sinks (aiosmtpd on :1025, HTTP sink on :9797):
configure the channels in Settings, trigger an unknown-face alert, and all
three deliver — email with subject `[SentinelAI ALERT] ...`, Telegram
`sendMessage` with chat_id, Discord embed payload. Secrets (`smtp_password`,
`telegram_bot_token`, `discord_webhook_url`) come back masked as `********`
from GET /api/settings, and sending the mask back leaves the stored value
unchanged. Failures are logged and never block the recognition pipeline.

## 6c. Reports (4 formats)

`GET /api/reports/visitors?period=daily|weekly|monthly&format=csv|json|pdf|xlsx`
— PDF validates as `PDF document 1.4`, XLSX opens in openpyxl with a frozen
header row. All four download buttons are on the Reports page.

## 7. Reports & analytics

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8000/api/reports/visitors?period=daily&format=csv'
```

Expected: CSV with one row per recognition in the period (UTC windows).
`analytics/summary` counts must match the tables.

## 8. Database (PostgreSQL)

```bash
psql -d sentinelai -c "SELECT count(*) FROM recognition_logs;"
alembic -c backend/alembic.ini current      # → e9044b89d74c (head)
```

## 9. Frontend

```bash
cd frontend && npm run build     # must pass with zero errors
npm run dev                      # login at http://localhost:5173 with admin/admin123
```

Walk through: Dashboard stats → Live Camera (+ AI overlay toggle) → snapshot
test upload → Users (create, photo upload) → Unknown Visitors → open case →
Cases → close case → Reports CSV download → Settings threshold slider.

## 10. Docker deployment

Verified with colima on this machine: `docker compose up -d` brings up
postgres:16 (healthcheck), the backend (connects to the containerized DB,
seeds admin), and the frontend behind nginx. Checks: backend root 200,
containerized login 200, `/api/users` returns the seeded admin, frontend 200
on :5173, and login proxied through nginx 200. Host webcams are not reachable
from macOS containers — use an RTSP `camera_source`.

## Known environment caveats

- OpenCV must stay `< 5` (5.x removed `CascadeClassifier`, used by the
  no-insightface fallback); the requirement is pinned.
- macOS: start the backend with `python run.py` / `python -m uvicorn`, never
  the bare `uvicorn` console script (camera permission is silently lost —
  see INSTALL.md §3).
