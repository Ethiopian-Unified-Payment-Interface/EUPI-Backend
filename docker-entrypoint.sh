#!/bin/sh
# EUPI backend container entrypoint.
#
# Applies schema migrations before serving. Doing it here rather than in
# application startup means a failed migration stops the container instead of
# leaving a process running against a half-migrated schema — and the failure is
# visible in `docker compose up` rather than buried in request errors.
set -e

echo "Waiting for the database to accept connections..."
python - <<'PY'
import os
import sys
import time

from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]

# Postgres in compose is usually still initialising when this container starts.
# `depends_on: service_healthy` covers the common case, but a restarting
# database can still refuse the first connection, so retry rather than crash.
deadline = time.monotonic() + 60
last_error = None
while time.monotonic() < deadline:
    try:
        create_engine(url).connect().execute(text("SELECT 1"))
        print("Database is accepting connections.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 — any connection failure is a retry
        last_error = exc
        time.sleep(1)

print(f"Database unreachable after 60s: {last_error}", file=sys.stderr)
sys.exit(1)
PY

echo "Applying migrations..."
alembic upgrade head

echo "Starting EUPI gateway..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
