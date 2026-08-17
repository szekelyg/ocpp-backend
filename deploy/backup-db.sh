#!/usr/bin/env bash
# Napi DB mentés a helyi Postgres konténerből. Tedd cronba az új szerveren:
#   0 3 * * *  cd /home/<user>/ocpp-backend/deploy && ./backup-db.sh >> backup.log 2>&1
# 14 napnál régebbi mentéseket törli.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backups
TS=$(date +%Y%m%d_%H%M%S)
OUT="backups/ocpp_${TS}.sql.gz"
docker compose exec -T db pg_dump --no-owner --no-privileges -U ocppuser ocpp | gzip > "$OUT"
echo "$(date -Is) backup -> $OUT ($(du -h "$OUT" | cut -f1))"
find backups -name 'ocpp_*.sql.gz' -mtime +14 -delete
