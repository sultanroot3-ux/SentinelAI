# Contributing to SentinelAI

Thanks for your interest in improving SentinelAI! This guide covers setup,
workflow, and expectations for contributions.

## Development setup

```bash
git clone https://github.com/sultanroot3-ux/SentinelAI.git
cd SentinelAI

# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt      # includes pytest + httpx
python run.py                            # http://localhost:8000 (docs at /docs)

# Frontend (second terminal)
cd frontend
npm install
npm run dev                              # http://localhost:5173
```

Optional extras: `pip install insightface onnxruntime` enables real face
recognition (otherwise the OpenCV fallback runs detection only). PostgreSQL is
optional in development — without `SENTINEL_DATABASE_URL` the backend uses a
local SQLite file. See `docs/INSTALL.md` for details (including the macOS
camera notes).

## Running tests

```bash
cd backend
python -m pytest tests/ -v
```

- Tests run against a throwaway SQLite database by default and never touch
  your dev data. To run them against PostgreSQL (as CI does):
  `SENTINEL_TEST_DATABASE_URL=postgresql+psycopg2://user@localhost/dbname pytest tests/`
- **Every PR must keep the suite green** — CI runs it on SQLite and
  PostgreSQL, plus a frontend production build.

## Making changes

1. Fork and create a topic branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. Keep changes focused — one logical change per PR.
3. Add or update tests for any behavior change; add a CHANGELOG entry under
   an `Unreleased` heading for user-visible changes.
4. Database schema changes need an Alembic migration
   (`alembic revision --autogenerate -m "…"`) — never edit an applied
   migration; verify `alembic upgrade head` works on both SQLite and
   PostgreSQL.
5. API changes must be reflected in `docs/API_CONTRACT.md` — the frontend is
   built against that contract.

### Style

- **Python**: follow the existing code — type hints, docstrings on modules
  and non-obvious functions, `logging` (never `print`).
- **React**: functional components, plain CSS via the variables in
  `src/styles/global.css` (no UI frameworks), reuse the shared components in
  `src/components/`.
- Match the comment density and naming of the surrounding code.

## Reporting issues

Use GitHub Issues for bugs and feature requests. Include reproduction steps,
expected vs. actual behavior, and environment (OS, Python/Node versions,
SQLite or PostgreSQL). **Do not report security vulnerabilities in public
issues** — see [SECURITY.md](SECURITY.md).

## Responsible development

SentinelAI processes biometric data. Contributions must preserve the
project's privacy posture: unknown visitors are handled through case
management (never auto-identified), secrets stay masked in API responses, and
audit logging must cover new sensitive operations. Features designed for
covert surveillance of private individuals will not be accepted.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
