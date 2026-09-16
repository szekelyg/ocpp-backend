#!/usr/bin/env bash
# Élesbe küldés a Mac miniről a Hetzner szerverre.
#
#   ./deploy.sh                # tesztek a dev konténerben → git push → szerveren pull + build → ellenőrzés
#   ./deploy.sh --skip-tests   # tesztek nélkül
#
# Feltétel: a változások commitolva vannak (a szerver a GitHub master-t húzza).
set -euo pipefail
cd "$(dirname "$0")"

SERVER=root@167.233.166.217
REMOTE_DIR=/root/ocpp-backend/deploy
COMPOSE="docker compose -f docker-compose.hetzner.yml"
PUBLIC_URL=https://ev.energiafelho.hu

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "!! Van nem commitolt változás. Commitold (vagy stash-eld), aztán ./deploy.sh" >&2
  git status --short --untracked-files=no >&2
  exit 1
fi

if [ "${1:-}" != "--skip-tests" ]; then
  echo ">> Tesztek a dev konténerben..."
  docker compose -f docker-compose.dev.yml run --rm --no-deps backend pytest -q
fi

echo ">> git push..."
git push origin master
LOCAL_SHA=$(git rev-parse --short HEAD)

echo ">> Szerver: git pull + build + restart ($LOCAL_SHA)..."
ssh "$SERVER" "cd $REMOTE_DIR && git pull --ff-only -q && git rev-parse --short HEAD && $COMPOSE up -d --build 2>&1 | tail -4"

echo ">> Várakozás a backendre..."
for i in $(seq 1 30); do
  if ssh "$SERVER" "curl -sf -o /dev/null http://127.0.0.1:8010/"; then break; fi
  sleep 2
  [ "$i" = 30 ] && { echo "!! A backend nem válaszol, nézd a logot: ssh $SERVER 'cd $REMOTE_DIR && $COMPOSE logs backend --tail 50'" >&2; exit 1; }
done

echo ">> Ellenőrzés..."
echo "   publikus: $(curl -s -o /dev/null -w '%{http_code}' "$PUBLIC_URL/") $PUBLIC_URL"
ssh "$SERVER" "cd $REMOTE_DIR && $COMPOSE ps --format '   {{.Name}} {{.Status}}' && \
  $COMPOSE exec -T db psql -U ocppuser -d ocpp -tAc \"select '   online töltők (2 percen belül): ' || count(*) from charge_points where last_seen_at > now() - interval '2 minutes'\""
echo ">> Kész. Logok: ssh $SERVER 'cd $REMOTE_DIR && $COMPOSE logs -f backend'"
