# SentinelAI backend — production image.
# Multi-stage: wheels are built once, the runtime stage stays slim and runs
# as a non-root user.

# ---------- build stage ----------
FROM python:3.11-slim AS build

WORKDIR /wheels
COPY backend/requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---------- runtime stage ----------
FROM python:3.11-slim

# OpenCV runtime libs + curl for container healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=build /wheels /wheels
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY backend/ .

# Non-root runtime user; /data holds DB fallback, uploads, snapshots, models
RUN useradd --create-home --uid 10001 sentinel \
    && mkdir -p /data/database /data/uploads /data/unknown_faces /data/logs \
    && chown -R sentinel:sentinel /data /app
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
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS} --timeout-graceful-shutdown 10"]
