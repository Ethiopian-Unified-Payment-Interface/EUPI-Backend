# EUPI Backend — FastAPI gateway
#
# Build:  docker build -t eupi-backend .
# Run:    docker run -p 8000:8000 --env-file .env eupi-backend
#
# Normally driven by ../docker-compose.yml.

FROM python:3.12-slim AS base

# - PYTHONUNBUFFERED so logs reach `docker logs` immediately rather than
#   sitting in a buffer when the container is killed.
# - PYTHONIOENCODING because the gateway logs non-ASCII; without it a
#   non-UTF-8 default encoding raises UnicodeEncodeError mid-startup.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used by the compose healthcheck. Package lists are removed in the
# same layer so they never reach the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Requirements first: this layer is cached until requirements.txt itself
# changes, so an application edit does not reinstall the dependency tree.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# Migrations ship with the image: the container applies them on startup, so the
# schema and the code that expects it are always deployed together.
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY docker-entrypoint.sh ./

# Normalise line endings and set the execute bit. Without this the container
# fails with "exec format error" whenever the file was checked out on Windows,
# where git may have rewritten LF to CRLF.
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

# Non-root. A container process that can write its own application code is a
# much larger blast radius than it needs to be.
RUN useradd --create-home --uid 1000 eupi \
    && mkdir -p /app/data \
    && chown -R eupi:eupi /app
USER eupi

# Default kept for a standalone `docker run` with no database alongside.
# docker-compose.yml overrides this with the Postgres URL.
ENV DATABASE_URL=sqlite:////app/data/kifiya_gateway.db

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
