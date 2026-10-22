# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Set WITH_AI=true to bundle OpenCV/MediaPipe/YOLO (large image). Without it the API runs fine and
# AI frame analysis reports "unavailable" while browser-side proctoring keeps working.
ARG WITH_AI=false

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 APP_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && if [ "$WITH_AI" = "true" ]; then apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libegl1 libgles2; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-ai.txt ./
RUN pip install -r requirements.txt && if [ "$WITH_AI" = "true" ]; then pip install -r requirements-ai.txt; fi

COPY . .
RUN useradd --create-home --uid 10001 app && mkdir -p /data/evidence && chown -R app:app /app /data
USER app
ENV EVIDENCE_DIR=/data/evidence

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD curl -fsS http://localhost:8000/health/live || exit 1

# Migrate, then serve. Several workers are fine: migrations run once per container start and are idempotent.
CMD ["sh", "-c", "alembic upgrade head && exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:8000 --forwarded-allow-ips='*' --timeout 60 --graceful-timeout 20 --access-logfile -"]
