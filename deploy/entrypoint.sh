#!/bin/sh
set -e

echo "[entrypoint] Waiting for DB + running alembic migrations..."
alembic upgrade head

echo "[entrypoint] Starting uvicorn on 0.0.0.0:8000"
# --proxy-headers + forwarded-allow-ips: a Caddy mögött helyes scheme/host
# (PUBLIC_BASE_URL, Stripe redirectek, webhook URL-ek miatt fontos)
exec uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips '*'
