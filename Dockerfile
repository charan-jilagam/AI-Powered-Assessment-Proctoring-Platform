# syntax=docker/dockerfile:1
# ORVEXA as ONE service (API + built frontend). This is what render.yaml deploys.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Node runtime for candidate JavaScript/TypeScript (same Debian family as the final image).
FROM node:22-slim AS noderuntime

FROM python:3.12-slim
# Set WITH_AI=true to bundle OpenCV/MediaPipe/YOLO (large image; needs more RAM than Render's free tier).
ARG WITH_AI=false
# Languages candidates can use in the coding IDE when no Judge0 server is connected (CODE_RUNNER=local/auto):
#   none     - Python only (smallest image)
#   standard - Python, JavaScript, TypeScript, C, C++, Java, Go, Ruby, PHP, Perl, Lua, Bash, SQLite   (default)
#   full     - standard plus Rust, C#, Kotlin, Scala, R, Octave, Haskell, OCaml, Lisp, Fortran, Pascal, COBOL, NASM, D, Elixir, Erlang, Prolog, Groovy
# Each package is installed on its own and a failure is skipped, so one missing package never breaks the build;
# the app only offers languages whose compiler/interpreter is really installed (see /health/ready -> code_runner).
ARG LANGS=standard
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 APP_ENV=production STATIC_DIR=/app/static
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && if [ "$WITH_AI" = "true" ]; then apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libegl1 libgles2; fi \
    && rm -rf /var/lib/apt/lists/*
RUN set -e; \
    STD="gcc g++ libc6-dev default-jdk-headless golang-go ruby php-cli lua5.4 sqlite3 perl"; \
    FULL="rustc mono-mcs mono-runtime kotlin scala r-base-core octave ghc ocaml-nox sbcl gfortran fp-compiler gnucobol nasm gdc elixir erlang-base gprolog groovy"; \
    case "$LANGS" in none) PKGS="";; full) PKGS="$STD $FULL";; *) PKGS="$STD";; esac; \
    if [ -n "$PKGS" ]; then apt-get update; for p in $PKGS; do apt-get install -y --no-install-recommends "$p" || echo "skipping unavailable package $p"; done; rm -rf /var/lib/apt/lists/*; fi
COPY --from=noderuntime /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/requirements.txt backend/requirements-ai.txt ./
RUN pip install -r requirements.txt && if [ "$WITH_AI" = "true" ]; then pip install -r requirements-ai.txt; fi
COPY backend/ ./
COPY --from=web /web/dist /app/static
# The server runs as root ON PURPOSE: candidate code is executed by switching to the unprivileged user RUNNER_UID
# (with no capabilities), so it cannot read the server's environment/secrets, /data, or other candidates' files.
# Set RUNNER_UID= (empty) to disable that and run candidate code as the server user.
RUN useradd --no-create-home --uid 10002 --shell /usr/sbin/nologin runner \
    && mkdir -p /data/evidence && chmod 700 /data && chmod -R go-rwx /data
ENV EVIDENCE_DIR=/data/evidence PORT=10000 RUNNER_UID=10002 RUNNER_GID=10002
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD curl -fsS http://localhost:${PORT}/health/live || exit 1
# Indexes are created by the app on start (MongoDB needs no migrations).
CMD ["sh", "-c", "exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-1} -b 0.0.0.0:${PORT} --forwarded-allow-ips='*' --timeout 60 --graceful-timeout 20 --access-logfile -"]
