# Éles (Hetzner) és fejlesztős (Mac mini) környezet

| | Hol | Compose | Elérés |
|---|---|---|---|
| **Éles** | `root@167.233.166.217` → `/root/ocpp-backend` | `docker-compose.hetzner.yml` | `https://ev.energiafelho.hu`, töltők: `wss://ocpp.energiafelho.hu/ocpp/<id>` |
| **Dev/teszt** | Mac mini, ez a repó | `docker-compose.dev.yml` | `http://localhost:5173` (Vite), `http://localhost:8000` (backend) |

Az élest a **Cloudflare tunnel** szolgálja ki (`cloudflared` konténer a stackben), Caddy nélkül – a szerver
80/443 portját másik stack használja. Emiatt DNS-t, töltő-URL-t, Stripe webhookot nem kell állítani.

## Napi munka

```bash
cd deploy
docker compose -f docker-compose.dev.yml up --build     # dev stack: db + backend (--reload) + Vite (HMR)
```
- Backend kód (`app/`, `alembic/`) volume-ról jön, mentésre újratölt. Frontend HMR-rel frissül.
- Az éles kulcsok a `.env.dev`-ben szándékosan üresek (nincs valódi terhelés/számla/e-mail).
  Stripe **teszt** kulcsot tehetsz bele. Admin: `admin` / `admin`.
- Töltőszimulátor a dev backendre:
  ```bash
  docker compose -f docker-compose.dev.yml exec backend python ocpp_simulator.py ws://localhost:8000/ocpp/VLTHU_SIM01
  ```
- Tesztek: `docker compose -f docker-compose.dev.yml run --rm --no-deps backend pytest`
- Dev DB feltöltése éles adatokkal: `./dev-seed-db.sh` (tegnapi mentés) vagy `./dev-seed-db.sh --fresh`
- Dev DB kívülről: `psql postgresql://ocppuser:dev@127.0.0.1:5433/ocpp`

## Élesbe küldés

```bash
git commit ...            # a szerver a GitHub master-t húzza
./deploy.sh               # pytest → git push → szerveren pull + build + restart → ellenőrzés
```
`./deploy.sh --skip-tests` ha sietsz. Az `entrypoint.sh` induláskor `alembic upgrade head`-et futtat,
így az új migrációk maguktól felmennek. Egy újraindítás ~10 mp, a töltők visszakapcsolódnak;
ha lehet, ne aktív töltés közben (`select * from charge_sessions where finished_at is null`).

## Éles szerver kézzel

```bash
ssh root@167.233.166.217
cd /root/ocpp-backend/deploy && export COMPOSE_FILE=docker-compose.hetzner.yml
docker compose logs -f backend                # logok
docker compose ps                             # állapot
docker compose exec -T db psql -U ocppuser -d ocpp
docker compose restart backend
curl -sI http://127.0.0.1:8010/               # backend csak localhoston, publikusan a tunnel adja
```
- Titkok a szerveren: `deploy/.env`, `deploy/cloudflared/credentials.json` (egyik sincs gitben).
- Napi mentés: cron 03:00 → `deploy/backups/` (14 nap), `backup-db.sh`.
- A REST API a `/api` prefix alatt van; OCPP WS `/ocpp/{id}`, OCPI `/ocpi`.

## Ha valaha saját IP-re / Caddy mögé kerülne

A `docker-compose.yml` + `Caddyfile` a tunnel nélküli, közvetlen 80/443-as változat (Let's Encrypt).
A `migrate-db.sh` az egyszeri DB-átköltöztetés segédje.
