#!/usr/bin/env bash
# DB átköltöztetése a Raspiról az új szerverre.
# A Raspi adatbázisa kicsi (~12 MB), ez másodpercek alatt lemegy.
#
# Használat a RASPIN:
#   ./migrate-db.sh dump            # -> ocpp_dump.sql.gz a mostani mappába
# Másold át az új szerverre (scp ocpp_dump.sql.gz user@uj-szerver:~/), majd ott:
#   ./migrate-db.sh restore-local   # a docker compose `db` konténerébe tölti
#   ./migrate-db.sh restore-neon "<NEON_DATABASE_URL_psql_alak>"   # Neonba tölti
set -euo pipefail

DUMP=ocpp_dump.sql.gz

case "${1:-}" in
  dump)
    echo ">> pg_dump a 'ocpp' adatbázisról..."
    sudo -u postgres pg_dump --no-owner --no-privileges ocpp | gzip > "$DUMP"
    echo ">> Kész: $DUMP ($(du -h "$DUMP" | cut -f1))"
    echo ">> Másold át: scp $DUMP user@uj-szerver:~/"
    ;;

  restore-local)
    # Az új szerveren, a deploy/ mappából, a `db` konténerbe tölt.
    echo ">> Visszatöltés a docker compose 'db' konténerbe..."
    gunzip -c "$DUMP" | docker compose exec -T db psql -U ocppuser -d ocpp
    echo ">> Kész."
    ;;

  restore-neon)
    URL="${2:?Adj meg egy Neon psql connection stringet: postgresql://user:pass@host/ocpp?sslmode=require}"
    echo ">> Visszatöltés Neonba..."
    gunzip -c "$DUMP" | psql "$URL"
    echo ">> Kész."
    ;;

  *)
    echo "Használat: $0 {dump|restore-local|restore-neon <NEON_URL>}"
    exit 1
    ;;
esac
