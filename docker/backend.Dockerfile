# SentinelAI backend — production image.
# Multi-stage: wheels are built once, the runtime stage stays slim and runs
# as a non-root user. Includes the full AI engine (insightface + onnxruntime)
# and the buffalo_l model baked in with checksum verification (C4) — the
# container never downloads models at runtime and works fully offline.

# ---------- build stage ----------
FROM python:3.11-slim AS build

# insightface builds a C++ extension; unzip for the model pack
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential unzip curl && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY backend/requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && pip wheel --no-cache-dir --wheel-dir /wheels insightface onnxruntime

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

# ---------- runtime stage ----------
FROM python:3.11-slim

# OpenCV runtime libs + curl for container healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=build /wheels /wheels
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
      -r requirements.txt insightface onnxruntime \
    && rm -rf /wheels

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
ENV UVICORN_WORKERS=2
# Entrypoint applies alembic migrations and refuses to start on failure (C1).
ENTRYPOINT ["/entrypoint.sh"]
