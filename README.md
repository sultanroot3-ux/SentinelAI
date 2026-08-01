# 🛡 SentinelAI – Intelligent Vision Security Platform

> **See • Recognize • Analyze • Protect**

[![CI](https://github.com/sultanroot3-ux/SentinelAI/actions/workflows/ci.yml/badge.svg)](https://github.com/sultanroot3-ux/SentinelAI/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/sultanroot3-ux/SentinelAI)](https://github.com/sultanroot3-ux/SentinelAI/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

SentinelAI is an AI-powered vision security platform for organizations, universities, offices, labs and research environments. It detects faces from live camera feeds, recognizes registered users, logs events, manages unknown visitors through case management, and provides a secure administrative dashboard.

Unknown people are handled through **case management** rather than automatically revealing private information — the system focuses on authorized recognition and security management.

## ✨ Features

- 📷 **Live Camera Monitoring** — USB / IP / RTSP streams, MJPEG dashboard feed
- 🔍 **Face Detection** — InsightFace (with OpenCV Haar fallback), multiple faces, bounding boxes, confidence scores
- 🧠 **Face Recognition** — ArcFace embeddings, cosine matching with configurable threshold
- 🕵️ **Unknown Visitor Management** — snapshots, review workflow, investigation cases
- 📋 **Visitor Logs** — searchable, filterable recognition history
- 📊 **Analytics** — daily visitors, peak hours, camera stats, recognition accuracy
- 📑 **Reports** — daily / weekly / monthly, CSV export
- 🔔 **Notifications** — in-app alerts (email / Discord / Telegram hooks stubbed)
- 🔐 **Security** — JWT auth, RBAC (admin / security officer / receptionist / IT), bcrypt password hashing, audit logs

## 🧱 Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy, SQLite |
| AI | OpenCV, InsightFace (ArcFace), NumPy |
| Frontend | React (Vite), plain CSS, SVG charts |
| Auth | JWT, bcrypt, RBAC |
| Deployment | Docker, docker-compose |

## 🚀 Quick Start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

API runs at **http://localhost:8000** (interactive docs at `/docs`).

> **Real face recognition:** install the optional AI extras —
> `pip install insightface onnxruntime` — otherwise the system falls back
> to OpenCV Haar detection without identity matching.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard at **http://localhost:5173**.

### 3. Login

Default admin account (change it after first login):

```
username: admin
password: admin123
```

### Docker

```bash
docker compose up --build
```

## 📂 Project Structure

```
├── backend/          FastAPI app (api, models, schemas, services, core)
├── frontend/         React dashboard (Vite)
├── database/         SQLite database file (created on first run)
├── ai/               AI experiments & notebooks
├── uploads/          Registered user photos
├── unknown_faces/    Snapshots of unrecognized visitors
├── logs/             Application logs
├── docker/           Dockerfiles
├── docs/             API contract & documentation
└── deployment/       Deployment guides (Ubuntu, Raspberry Pi, cloud)
```

## 📷 Recognition Workflow

```
Live Camera → Frame Capture → Face Detection → Quality Check → Liveness
     → Face Recognition → Database Match
         ├─ Match     → Authorized profile → Log → Dashboard
         └─ No match  → Snapshot → Unknown Visitor → Case → Admin review
```

## 📖 Documentation

**Start here:** [Project Status](PROJECT_STATUS.md) — current version, what is
verified, and what still needs manual validation before general production.

- **Using it:** [User Manual](docs/USER_MANUAL.md) · [Admin Manual](docs/ADMIN_MANUAL.md)
- **Building on it:** [API Contract](docs/API_CONTRACT.md) — every endpoint, payload and model · [Architecture](docs/ARCHITECTURE.md) · [Testing](docs/TESTING.md)
- **Running it:** [Installation](docs/INSTALL.md) · [Deployment](deployment/DEPLOYMENT.md) · [Go-live checklist (v1.1)](docs/DEPLOYMENT_CHECKLIST_v1.1.md) · [Vercel frontend](docs/VERCEL_DEPLOY.md)
- **Operating it:** [Performance & load](docs/PERFORMANCE.md) · [Backup & restore](docs/BACKUP_RESTORE.md) · [Data retention](docs/DATA_RETENTION.md)
- **Assurance:** [CTO production-readiness review](docs/CTO_REVIEW_FINAL.md)
- **Project:** [Changelog](CHANGELOG.md) · [Release notes](RELEASE_NOTES.md) · [Contributing](CONTRIBUTING.md) · [Security Policy](SECURITY.md) · [Code of Conduct](CODE_OF_CONDUCT.md)

## 🔥 Roadmap

**v1.1.x (next):** real-camera and HTTPS pilot validation · `axe-core`
accessibility assertions in CI · finite default for biometric retention ·
multi-camera support · GPU `onnxruntime` build

**Later:** object detection · license plate recognition · QR / RFID ·
voice recognition · cloud sync · mobile app · AI assistant

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for what is verified today and what
is not.

## ⚖️ Responsible Use

SentinelAI is designed for **authorized** access-control and security management
on premises you operate, with the knowledge and consent required by local law.
Face recognition data is sensitive — keep the database secured, review your
jurisdiction's biometric privacy regulations (GDPR, BIPA, etc.) before deployment,
and use the unknown-visitor case workflow instead of attempting to identify
people who are not registered users.
