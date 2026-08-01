#!/usr/bin/env bash
# Regenerate the pinned, hash-verified backend lock files (B2).
#
# Runs pip-compile inside a linux/amd64 python:3.11-slim container — the same
# base image the production backend is built from — so the resolved versions
# and wheel hashes match what actually ships. Compiling on a developer laptop
# (macOS/arm64) can resolve different versions and different wheels.
#
# Usage:  ./scripts/lock-requirements.sh
# Then commit the regenerated requirements*.txt files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Compiling backend requirements in linux/amd64 python:3.11-slim"
docker run --rm --platform linux/amd64 \
  -v "${REPO_ROOT}/backend:/work" \
  -w /work \
  python:3.11-slim \
  bash -euo pipefail -c '
    apt-get update -qq >/dev/null
    apt-get install -y -qq --no-install-recommends build-essential >/dev/null
    pip install --quiet --no-cache-dir pip-tools

    # Runtime first: the others constrain against it (-c requirements.txt), so
    # every layer resolves to the same version of any shared package.
    pip-compile --quiet --generate-hashes --strip-extras \
      --output-file requirements.txt requirements.in

    pip-compile --quiet --generate-hashes --strip-extras \
      --output-file requirements-dev.txt requirements-dev.in

    pip-compile --quiet --generate-hashes --strip-extras \
      --output-file requirements-ai.txt requirements-ai.in

    # Headless OpenCV for the production image; see requirements-headless.in.
    pip-compile --quiet --generate-hashes --strip-extras \
      --output-file requirements-headless.txt requirements-headless.in

    chmod 0644 requirements.txt requirements-dev.txt requirements-ai.txt \
               requirements-headless.txt
  '

echo "==> Done. Regenerated:"
for f in requirements.txt requirements-dev.txt requirements-ai.txt requirements-headless.txt; do
  printf '    backend/%-24s %s pinned packages\n' "$f" \
    "$(grep -cE '^[a-zA-Z0-9]' "${REPO_ROOT}/backend/${f}" || true)"
done
echo "Review the diff and commit."
