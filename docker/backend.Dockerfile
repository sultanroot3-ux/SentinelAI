# SentinelAI backend — production image.
#
# Multi-stage: dependencies are installed into a virtualenv in the build stage
# (which has the compilers insightface needs), and only the finished venv is
# copied into the slim runtime stage, which runs as a non-root user.
#
# Every dependency is installed with --require-hashes from the generated lock
# files (B2), so a build either reproduces the audited dependency set exactly
# or fails. Regenerate the locks with ./scripts/lock-requirements.sh.
#
# The AI engine (insightface + onnxruntime) and the buffalo_l model pack are
# baked in with checksum verification, so the container never downloads a model
# at runtime and works fully offline.

# ---------- build stage ----------
FROM python:3.11-slim AS build

# insightface builds a C++ extension; unzip for the model pack
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential unzip curl && rm -rf /var/lib/apt/lists/*

# A venv keeps the installed tree in one relocatable directory. Installing
# directly with --require-hashes (rather than building wheels and reinstalling
# them) is what makes the hash check meaningful: locally-built wheels have
# different digests than the audited PyPI artifacts, so a wheel round-trip
# would silently defeat the verification.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /deps
COPY backend/requirements.txt backend/requirements-ai.txt backend/requirements-headless.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --require-hashes -r requirements.txt \
    && pip install --no-cache-dir --require-hashes -r requirements-ai.txt

# Swap the GUI OpenCV build for the headless one. insightface hard-declares
# `opencv-python`, so the audited lock resolves the GUI build, which links
# libGL.so.1 — and libgl1 hard-depends on libglx-mesa0 -> mesa-libgallium ->
# libllvm19. That was 192 MB of software OpenGL renderer in a server image for
# a highgui module nothing calls.
#
# Sequential (uninstall, then install) rather than resolved together, because
# both distributions own the same cv2/ directory and letting pip install both
# makes the winner depend on install order. Headless is hash-verified from its
# own lock, so nothing enters the image outside an audited set — see
# backend/requirements-headless.in.
#
# Asserted, not assumed: the build fails if cv2 still pulls libGL afterwards.
RUN pip uninstall -y opencv-python \
    && pip install --no-cache-dir --require-hashes -r requirements-headless.txt \
    && python -c "import cv2; print('cv2', cv2.__version__, 'headless OK')" \
    && if ldd "$(python -c 'import cv2,os;print(cv2.__file__)' | sed 's/__init__.py//')"*.so \
         2>/dev/null | grep -q libGL; then \
         echo "cv2 still links libGL — the headless swap did not take"; exit 1; \
       fi \
    && echo "verified: cv2 does not link libGL"

# buffalo_l model pack, pinned by sha256 (official insightface v0.7 release).
# A vendored copy in docker/models/ (gitignored) is used when present —
# otherwise the pack is downloaded. Checksum is enforced in both cases.
ARG BUFFALO_L_SHA256=80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f
COPY docker/models/ /tmp/vendored/
RUN if [ -f /tmp/vendored/buffalo_l.zip ]; then \
      cp /tmp/vendored/buffalo_l.zip /tmp/buffalo_l.zip; \
    else \
      curl -fsSL --retry 5 -o /tmp/buffalo_l.zip \
        https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip; \
    fi \
    && echo "${BUFFALO_L_SHA256}  /tmp/buffalo_l.zip" | sha256sum -c - \
    && mkdir -p /models/buffalo_l \
    && unzip -q /tmp/buffalo_l.zip -d /models/buffalo_l \
    && rm -rf /tmp/buffalo_l.zip /tmp/vendored

# buffalo_l ships five models; the app loads three (INSIGHTFACE_MODULES in
# app/services/face_service.py). Dropping landmark_3d_68 (1k3d68.onnx, 144 MB)
# and genderage (1.3 MB) removes 145 MB — 43% of the pack — plus two ONNX
# sessions' worth of RAM and init time per worker. Nothing reads
# face.landmark_3d_68, face.sex or face.age.
#
# The checksum above is verified against the *complete* pack before anything is
# removed, so provenance is still proven for what remains.
#
# Both lists are asserted rather than applied best-effort. A silent no-op here
# would be the worst outcome: if a future pack renamed w600k_r50.onnx, a
# `rm -f` of the unused names would succeed, the image would build clean, and
# the missing recognition model would surface as "nothing ever matches" in
# production rather than as a build failure.
RUN cd /models/buffalo_l \
    && for m in 1k3d68.onnx genderage.onnx; do \
         [ -f "$m" ] || { echo "expected to remove $m but it is absent"; exit 1; }; \
         rm -f "$m"; \
       done \
    && for m in det_10g.onnx 2d106det.onnx w600k_r50.onnx; do \
         [ -f "$m" ] || { echo "required model $m missing after prune"; exit 1; }; \
       done \
    && echo "model pack pruned to: $(ls)" && du -sh /models/buffalo_l

# ---------- runtime stage ----------
FROM python:3.11-slim

# OpenCV runtime libs + curl for container healthchecks.
#
# libgl1 is deliberately absent: the venv ships headless OpenCV, which does not
# link libGL. Adding it back would drag in libglx-mesa0, mesa-libgallium and
# libllvm19 — 192 MB, and an entire software GL renderer's worth of attack
# surface. If `import cv2` ever fails with "libGL.so.1: cannot open shared
# object file", the headless swap in the build stage regressed; fix that rather
# than reinstating libgl1.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The finished venv only — no compilers or build caches in the final image.
COPY --from=build /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY backend/ .
COPY docker/entrypoint.sh /entrypoint.sh

# Non-root runtime user; /data holds DB fallback, uploads, snapshots
RUN useradd --create-home --uid 10001 sentinel \
    && chmod +x /entrypoint.sh \
    && mkdir -p /data/database /data/uploads /data/unknown_faces /data/logs \
    && chown -R sentinel:sentinel /data /app

# Baked model where insightface looks for it (~/.insightface/models)
COPY --from=build --chown=sentinel:sentinel /models /home/sentinel/.insightface/models

# Explicit data locations on the persistent volume (the config's defaults
# resolve relative to the source tree, which is / inside the image).
ENV SENTINEL_DATABASE_DIR=/data/database \
    SENTINEL_UPLOADS_DIR=/data/uploads \
    SENTINEL_UNKNOWN_FACES_DIR=/data/unknown_faces \
    SENTINEL_LOGS_DIR=/data/logs \
    HOME=/home/sentinel \
    PYTHONUNBUFFERED=1

USER sentinel

EXPOSE 8000
# WORKERS: MJPEG streams occupy a worker thread each; scale with camera count.
# NOTE: >1 worker requires SENTINEL_REDIS_URL — the app refuses to start in
# production without it, because rate limits and pipeline cooldowns would
# otherwise be per-worker (B4). docker-compose.yml provides a redis service.
ENV UVICORN_WORKERS=2
# Entrypoint applies alembic migrations and refuses to start on failure (C1).
ENTRYPOINT ["/entrypoint.sh"]
