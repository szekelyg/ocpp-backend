#!/usr/bin/env bash
# A dev DB feltöltése az éles legfrissebb mentésével (Hetzner deploy/backups/, napi 03:00).
# A dev stack fusson (docker compose -f docker-compose.dev.yml up). A dev DB-t FELÜLÍRJA.
#
#   ./dev-seed-db.sh          # legfrissebb napi mentés
#   ./dev-seed-db.sh --fresh  # friss pg_dump az élesből most
set -euo pipefail
cd "$(dirname "$0")"

SERVER=root@167.233.166.217
REMOTE_DIR=/root/ocpp-backend/deploy
DEV="docker compose -f docker-compose.dev.yml"
mkdir -p backups
DUMP=backups/ocpp_seed.sql.gz

if [ "${1:-}" = "--fresh" ]; then
  echo ">> Friss dump az élesből..."
  ssh "$SERVER" "cd $REMOTE_DIR && docker compose -f docker-compose.hetzner.yml exec -T db pg_dump --no-owner --no-privileges -U ocppuser ocpp | gzip" > "$DUMP"
else
  LATEST=$(ssh "$SERVER" "ls -t $REMOTE_DIR/backups/ocpp_*.sql.gz | head -1")
  echo ">> Letöltés: $LATEST"
  scp -q "$SERVER:$LATEST" "$DUMP"
fi

echo ">> Dev DB újraépítése ($(du -h "$DUMP" | cut -f1))..."
$DEV stop backend >/dev/null
$DEV exec -T db psql -q -U ocppuser -d postgres -c "DROP DATABASE IF EXISTS ocpp;" -c "CREATE DATABASE ocpp OWNER ocppuser;"
gunzip -c "$DUMP" | $DEV exec -T db psql -q -U ocppuser -d ocpp -v ON_ERROR_STOP=1 >/dev/null
$DEV up -d backend >/dev/null
$DEV exec -T db psql -U ocppuser -d ocpp -tAc "select 'töltők: '||(select count(*) from charge_points)||', munkamenetek: '||(select count(*) from charge_sessions)||', felhasználók: '||(select count(*) from users)"
echo ">> Kész."
