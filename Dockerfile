# syntax=docker/dockerfile:1
# ORVEXA as ONE service (API + built frontend). This is what render.yaml deploys.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
# Set WITH_AI=true to bundle OpenCV/MediaPipe/YOLO (large image; needs more RAM than Render's free tier).
ARG WITH_AI=false
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 APP_ENV=production STATIC_DIR=/app/static
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && if [ "$WITH_AI" = "true" ]; then apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libegl1 libgles2; fi \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements-ai.txt ./
RUN pip install -r requirements.txt && if [ "$WITH_AI" = "true" ]; then pip install -r requirements-ai.txt; fi
COPY backend/ ./
COPY --from=web /web/dist /app/static
RUN useradd --create-home --uid 10001 app && mkdir -p /data/evidence && chown -R app:app /app /data
USER app
ENV EVIDENCE_DIR=/data/evidence PORT=10000
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD curl -fsS http://localhost:${PORT}/health/live || exit 1
# Indexes are created by the app on start (MongoDB needs no migrations).
CMD ["sh", "-c", "exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-1} -b 0.0.0.0:${PORT} --forwarded-allow-ips='*' --timeout 60 --graceful-timeout 20 --access-logfile -"]
