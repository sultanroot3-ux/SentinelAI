# SentinelAI — API Contract (v1)

Backend base URL: `http://localhost:8000`. All endpoints are prefixed with `/api`.
Auth: JWT Bearer token in `Authorization: Bearer <token>` header (except login and camera stream).

## Auth
| Method | Path | Body / Params | Response |
|---|---|---|---|
| POST | `/api/auth/login` | JSON `{username, password}` | `{access_token, refresh_token, token_type, user}` — 429 + `Retry-After` after 5 failed attempts per username+IP in 15 min |
| POST | `/api/auth/refresh` | `{refresh_token}` | new `{access_token, refresh_token, ...}` — refresh tokens are single-use (rotation); reuse → 401 |
| POST | `/api/auth/logout` | `{refresh_token}` (+ Bearer) | revokes the refresh token |
| POST | `/api/auth/change-password` | `{current_password, new_password}` (+ Bearer) | updated `User`; revokes all refresh tokens. 401 wrong current, 422 `new_password` < 8 chars |
| GET | `/api/auth/me` | — | `User` |

Access tokens expire in 30 min (`type: "access"`); refresh tokens in 7 days
(`type: "refresh"`, jti tracked server-side). `User.must_change_password=true`
means the client must force a password change before using the app (seeded
admin starts with it set).

## Health
| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | unauthenticated; `{status, database}`, 503 if DB down |

## Users
| Method | Path | Notes |
|---|---|---|
| GET | `/api/users` | list, query: `search`, `department_id`, `role` |
| POST | `/api/users` | JSON `{name, email, username, password, role, department_id, employee_id, access_level}` |
| GET | `/api/users/{id}` | |
| PUT | `/api/users/{id}` | partial update |
| DELETE | `/api/users/{id}` | |
| POST | `/api/users/{id}/photo` | multipart `file` — registers face embedding, stores photo |

`User`: `{id, name, email, username, role, department_id, department_name, employee_id, access_level, photo_url, face_registered, must_change_password, created_at}`

Passwords: minimum 8 characters (create, update, change-password).

Roles: `admin`, `security_officer`, `receptionist`, `it`.

## Departments
CRUD at `/api/departments` — `{id, name, description, user_count}`

## Recognition
| Method | Path | Notes |
|---|---|---|
| POST | `/api/recognition/frame` | multipart `file` (image) → `{faces: [{box, confidence, match: User|null, score, liveness}]}`; also writes a RecognitionLog / UnknownFace |
| GET | `/api/camera/stream` | MJPEG stream (`multipart/x-mixed-replace`) from local webcam; query `?token=` for auth |
| GET | `/api/camera/status` | `{available, source}` |

## Visitor Logs
| Method | Path | Notes |
|---|---|---|
| GET | `/api/logs` | query: `date_from`, `date_to`, `user_id`, `camera`, `page`, `page_size` → `{items, total, page}` |

`RecognitionLog`: `{id, user_id, user_name, camera, score, snapshot_url, timestamp}`

## Unknown Visitors
| Method | Path | Notes |
|---|---|---|
| GET | `/api/unknown` | query: `status` (`new`,`reviewed`,`case_opened`), `page` |
| PUT | `/api/unknown/{id}` | `{status}` |
| DELETE | `/api/unknown/{id}` | |

`UnknownFace`: `{id, snapshot_url, camera, status, case_id, timestamp}`

## Cases (Investigation)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/cases` | query: `status`, `priority`, `page` |
| POST | `/api/cases` | `{unknown_face_id, priority, notes, assigned_to}` |
| GET | `/api/cases/{id}` | |
| PUT | `/api/cases/{id}` | `{status, priority, notes, assigned_to, resolution}` |

`Case`: `{id, case_number, unknown_face_id, snapshot_url, camera, status, priority, notes, assigned_to, assigned_to_name, resolution, created_at, updated_at}`
Status: `open`, `investigating`, `closed`. Priority: `low`, `medium`, `high`, `critical`.

## Analytics
| Method | Path | Response |
|---|---|---|
| GET | `/api/analytics/summary` | `{total_users, today_visitors, today_unknown, open_cases, recognition_accuracy}` |
| GET | `/api/analytics/daily?days=7` | `[{date, recognized, unknown}]` |
| GET | `/api/analytics/peak-hours` | `[{hour, count}]` |
| GET | `/api/analytics/cameras` | `[{camera, count}]` |

## Reports
| Method | Path | Notes |
|---|---|---|
| GET | `/api/reports/visitors?period=daily|weekly|monthly&format=csv|json` | CSV download or JSON |

## Notifications
| Method | Path | Notes |
|---|---|---|
| GET | `/api/notifications` | query `unread_only` |
| PUT | `/api/notifications/{id}/read` | |
| PUT | `/api/notifications/read-all` | |

`Notification`: `{id, title, message, level, read, created_at}` — level: `info`, `warning`, `alert`.

## Settings
| Method | Path | Notes |
|---|---|---|
| GET | `/api/settings` | `{key: value}` map |
| PUT | `/api/settings` | partial `{key: value}` map |

Keys: `recognition_threshold` (float 0–1, default 0.45), `liveness_enabled` (bool), `camera_source` (str, default "0"), `notify_on_unknown` (bool).

## Static
- `/static/uploads/...` — user photos
- `/static/unknown_faces/...` — unknown snapshots

## Seed data
On first startup the backend seeds: admin user `admin` / `admin123` (role `admin`), and departments `Security`, `IT`, `Reception`.

## Errors
Errors return `{detail: string}` with proper HTTP status (401 unauthorized, 404 not found, 422 validation).
