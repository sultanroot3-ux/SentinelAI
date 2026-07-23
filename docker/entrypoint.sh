#!/bin/sh
# SentinelAI backend entrypoint: apply database migrations, then start the app.
# `set -e` makes the container exit immediately if migrations fail — the
# application never starts against a half-migrated schema.
set -e

# Adoption path for databases created by v1.0.1 (schema built by create_all,
# no alembic_version table): the v1.0.1 schema is exactly migration head at
# that release, so stamp it before upgrading. Fresh/empty databases and
# already-stamped databases are left for `alembic upgrade head` to handle.
echo "[entrypoint] Checking migration state..."
python - <<'PY'
from sqlalchemy import create_engine, inspect
from app.core.config import settings

engine = create_engine(settings.database_url)
insp = inspect(engine)
tables = set(insp.get_table_names())
if "alembic_version" not in tables and "users" in tables:
    # Pre-alembic v1.0.1 deployment: adopt it at the revision matching its schema.
    # 'roles' arrived with 09dfff37227f; its absence means adfe449d4708.
    rev = "09dfff37227f" if "roles" in tables else "adfe449d4708"
    print(f"[entrypoint] Existing unversioned schema detected - stamping {rev}")
    from alembic import command
    from alembic.config import Config
    command.stamp(Config("alembic.ini"), rev)
else:
    print("[entrypoint] Migration state OK "
          f"(alembic_version present: {'alembic_version' in tables})")
PY

echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
alembic upgrade head
echo "[entrypoint] Migrations OK."

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --workers "${UVICORN_WORKERS:-2}" --timeout-graceful-shutdown 10
