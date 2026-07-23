# SentinelAI — Architecture

## System overview

```mermaid
flowchart LR
    subgraph Client
        B[Browser<br/>React SPA - 21 pages]
    end

    subgraph Server["Docker host (Ubuntu)"]
        N[nginx<br/>TLS termination, static files,<br/>API + MJPEG proxy]
        subgraph Backend["backend (FastAPI, uvicorn)"]
            API[21 API routers]
            FS[face_service<br/>detect / liveness / embed / match]
            IS[investigation_service<br/>AI estimates + reports]
            NS[notification_service<br/>email / telegram / discord]
        end
        DB[(PostgreSQL 16<br/>19 tables)]
        BK[backup service<br/>daily pg_dump, retention]
        CB[certbot<br/>Let's Encrypt renewal]
    end

    CAM[Cameras<br/>webcam / RTSP]

    B -- HTTPS 443 --> N
    N -- /api --> API
    N -. /.well-known/acme .-> CB
    API --> FS --> IS
    API --> NS
    API --> DB
    FS --> DB
    BK --> DB
    FS -- OpenCV --> CAM
```

## Recognition pipeline

```mermaid
sequenceDiagram
    participant C as Camera / Upload
    participant F as face_service
    participant AI as InsightFace (buffalo_l)
    participant DB as PostgreSQL

    C->>F: frame (BGR)
    F->>AI: detect faces
    AI-->>F: boxes + landmarks + 512-d embeddings
    F->>F: liveness (blink + motion + pose)
    F->>DB: cosine match vs registered embeddings
    alt match ≥ threshold
        F->>DB: RecognitionLog + AccessHistory
        F-->>C: green overlay (name + score)
    else no match
        F->>DB: UnknownFace (UNK-id) + FaceEmbedding + AccessHistory
        F->>DB: Notification ("Unknown person detected")
        F-->>C: red overlay (UNKNOWN)
    end
```

## Data model (core relations)

```mermaid
erDiagram
    departments ||--o{ users : has
    users ||--o{ face_embeddings : "enrolled photos"
    users ||--o{ recognition_logs : "recognized in"
    users ||--o{ access_history : "detected/entry"
    unknown_faces ||--o{ face_embeddings : "sighting embedding"
    unknown_faces ||--o{ cases : "investigated by"
    cameras }o--|| camera_locations : "placed at"
    recognition_logs }o--|| cameras : "seen on"
    unknown_faces }o--|| cameras : "seen on"
    watchlists ||--o{ watchlist_entries : contains
    watchlist_entries }o--|| users : "flags employee"
    watchlist_entries }o--|| unknown_faces : "flags unknown"
    visitors ||--o{ access_history : "check in/out"
    roles }o--o{ permissions : "role_permissions"
```

## Key design decisions

| Decision | Rationale |
|---|---|
| Embeddings cached in memory as one normalized matrix | one vectorized dot product per frame instead of a per-user loop |
| MJPEG over WebSocket/WebRTC | `<img>`-tag simplicity; auth via short-lived token query param |
| Signed media URLs (`/api/media/...?exp&sig`) | biometric images are never served from a public static mount |
| `User.role` string + seeded RBAC catalogue tables | auth checks stay trivial; catalogue is queryable/auditable |
| AI attributes labelled estimates; absent models report `unavailable` | investigation reports never invent identity or attribute data |
| SQLite fallback when `SENTINEL_DATABASE_URL` unset | zero-config dev; production refuses to start without PostgreSQL + real secret |

## Repository layout

```
backend/            FastAPI app (app/api, app/services, app/models, alembic/)
frontend/           React SPA (src/pages, src/components, src/api)
docker/             Dockerfiles, nginx configs
deployment/         install_ubuntu.sh, backups, monitoring, deployment guide
docs/               manuals, API contract, this document
ai/                 model notes / experiments
```
