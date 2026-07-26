#!/usr/bin/env python3
"""Regenerate docs/openapi.json from the live FastAPI app.

The committed schema had drifted from the code — it still advertised
`recognition_accuracy` months after the field was renamed to `match_rate` —
which is exactly the failure mode a hand-maintained snapshot invites. Run this
after any change to a router or response model:

    backend/.venv/bin/python scripts/export-openapi.py

CI runs it with --check, so a drifted schema fails the build instead of
misleading integrators.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "openapi.json"


def build_schema() -> dict:
    """Import the app against a throwaway DB and return its OpenAPI schema."""
    tmp = Path(tempfile.mkdtemp(prefix="sentinel_openapi_"))
    os.environ.setdefault("SENTINEL_DATABASE_URL", f"sqlite:///{tmp}/schema.db")
    os.environ.setdefault("SENTINEL_UPLOADS_DIR", str(tmp / "uploads"))
    os.environ.setdefault("SENTINEL_UNKNOWN_FACES_DIR", str(tmp / "unknown"))
    os.environ.setdefault("SENTINEL_LOGS_DIR", str(tmp / "logs"))
    os.environ.setdefault("SENTINEL_DATABASE_DIR", str(tmp))
    os.environ.setdefault("SENTINEL_SECRET_KEY", "openapi-export-only")

    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import app  # noqa: E402  (import needs the env above)

    return app.openapi()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed schema is stale (used by CI)",
    )
    args = parser.parse_args()

    schema = json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"

    if args.check:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if current != schema:
            print(
                f"::error::{OUTPUT.relative_to(ROOT)} is out of date with the code.\n"
                "Regenerate with: backend/.venv/bin/python scripts/export-openapi.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} is up to date.")
        return 0

    OUTPUT.write_text(schema)
    print(f"Wrote {OUTPUT.relative_to(ROOT)} ({len(schema):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
