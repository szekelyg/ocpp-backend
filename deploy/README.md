# OCPP backend költöztetése Raspiról online szerverre (Docker)

Teljes stack egy VPS-en: **backend (FastAPI/uvicorn) + Postgres + Caddy (TLS+proxy)**.
A backend maga szolgálja ki a frontendet is. Minden az `energiafelho.hu` alatt fut
(a `napos.hu` megszűnik). A költözés: ugyanez a stack az új gépen, DNS az új IP-re, majd
a töltőkben átírod az OCPP URL-t `ocpp.energiafelho.hu`-ra.

---

## 0. Milyen szervert vegyek?

Az OCPP **tartós WebSocket** kapcsolatot igényel a töltőkkel → **Vercel/serverless NEM jó**.
Kell egy mindig futó gép (VPS) nyilvános IP-vel, nyitott 80/443 porttal.

Bőven elég a legkisebb méret (a DB 12 MB, a terhelés pici):

| Szolgáltató | Csomag | Kb. ár |
|---|---|---|
| **Hetzner** (ajánlott) | CX22 – 2 vCPU / 4 GB | ~4–5 €/hó |
| DigitalOcean | Basic Droplet 1–2 GB | ~6–12 $/hó |
| Magyar (Rackforest/ITLand) | kis VPS | ~2–4 e Ft/hó |

OS: **Ubuntu 24.04 LTS**. (Neon: a DB-t kiteheted Neonra is, de 24/7-hez a fizetős csomag
kell, mert a free tier compute-órái nem fedik a non-stop futást – lásd 6/B.)

---

## 1. Szerver előkészítés (egyszer)

SSH-zz be az új VPS-re root-ként, majd:

```bash
# Docker telepítés
curl -fsSL https://get.docker.com | sh

# (ajánlott) sima felhasználó docker joggal
adduser deploy && usermod -aG docker deploy
# innentől: su - deploy

# Tűzfal: SSH + HTTP + HTTPS
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## 2. Kód feltöltése

A repó `deploy/` mappája tartalmaz mindent. A teljes repót vidd fel (a build a repo
gyökeréből dolgozik). Pl. a Raspiról:

```bash
cd /home/admin
rsync -av --exclude node_modules --exclude venv --exclude .git \
      ocpp-backend/ deploy@<UJ_IP>:~/ocpp-backend/
```
(vagy `git clone`, ha van távoli repó.)

## 3. Titkok beállítása (.env)

```bash
cd ~/ocpp-backend/deploy
cp .env.example .env
nano .env
```
A legegyszerűbb: a Raspiról a valós értékeket emeld át. A Raspin:
```bash
sudo cat /etc/ocpp-backend.env
```
Másold be az értékeket a `.env`-be. **Csak a `DATABASE_URL`-t és `POSTGRES_PASSWORD`-öt**
állítsd a helyi konténerhez (lásd `.env.example` A) opció), a többi titok változatlan.

## 4. DB átköltöztetés

A **Raspin**:
```bash
cd ~/ocpp-backend/deploy && ./migrate-db.sh dump
scp ocpp_dump.sql.gz deploy@<UJ_IP>:~/ocpp-backend/deploy/
```

## 5. Indítás

Az **új szerveren**, a `deploy/` mappából:
```bash
docker compose up -d --build        # backend image build + stack indítás
docker compose ps                   # minden "running"/"healthy"?
```
A `backend` az induláskor lefuttatja az `alembic upgrade head`-et (üres DB-n felépíti a sémát).
Most töltsd be az adatokat:
```bash
./migrate-db.sh restore-local
docker compose restart backend
```

## 6. (Opció) Neon DB használata helyi Postgres helyett

- `docker-compose.yml`: kommenteld ki a `db` service-t és a backend `depends_on` blokkját.
- `.env`: `DATABASE_URL=postgresql+asyncpg://USER:PASS@ep-xxx.neon.tech/ocpp?ssl=require`
- DB betöltés: `./migrate-db.sh restore-neon "postgresql://USER:PASS@ep-xxx.neon.tech/ocpp?sslmode=require"`
- ⚠️ Neon free tier ~191 compute-óra/hó < 730 (non-stop) → felfüggeszt. 24/7-hez fizetős csomag.

## 7. DNS beállítás

A `napos.hu` megszűnik – minden az `energiafelho.hu` alatt fut. Hozz létre / állíts át
**A rekordokat az új VPS IP-jére**:

| Domain | Hova | Cloudflare felhő |
|---|---|---|
| `ocpp.energiafelho.hu` | új VPS IP | **szürke (DNS only)** – kötelező, a töltők ws/wss-e miatt |
| `ev.energiafelho.hu` | új VPS IP | szürke = auto Let's Encrypt; vagy narancs (lásd lent) |

- **Ha `ev.energiafelho.hu` Cloudflare proxy (narancs) mögött marad:** a `Caddyfile`-ban
  cseréld a `reverse_proxy backend:8000` előtti sort `tls internal`-ra (a komment leírja),
  és a Cloudflare SSL módja legyen **Full**.

## 7b. Töltők átállítása

Mivel az endpoint hosztneve változik (`napos.hu` → `energiafelho.hu`), **minden töltőben
át kell írni az OCPP backend URL-t**. Csináld AZUTÁN, hogy a 8. lépésben látod, hogy az új
szerver fogadja a kapcsolatokat:

```
wss://ocpp.energiafelho.hu/ocpp/<charge_point_id>      (ajánlott, TLS)
ws://ocpp.energiafelho.hu/ocpp/<charge_point_id>       (ha a töltő nem tud wss-t)
```
A `<charge_point_id>` az, amit eddig is használt az adott töltő. Egyesével átállítod őket,
és a logban (8. lépés) látszik, ahogy bejönnek.

## 8. Ellenőrzés és Raspi leállítása

Először a frontend/API (DNS propagálás után):
```bash
curl -sI https://ev.energiafelho.hu        # 200 + a frontend
docker compose logs -f backend             # itt figyeld a töltőket
```
Most állítsd át a töltőket egyesével (7b. lépés). Ahogy átírod a ws URL-t egy töltőn,
a logban meg kell jelennie a `BootNotification` / `Heartbeat`-jének, és a DB-ben /
admin felületen frissülnie kell a `last_seen_at`-jének.

Ha **minden töltő online** az új szerveren és a fizetés is megy, a **Raspin** állítsd le a régit:
```bash
sudo systemctl disable --now ocpp-backend.service caddy.service
```
(A Postgres-t a Raspin egy darabig hagyd meg, amíg biztos nem vagy a költözésben.)

## 9. Napi mentés (ajánlott)

```bash
crontab -e
# 0 3 * * *  cd /home/deploy/ocpp-backend/deploy && ./backup-db.sh >> backup.log 2>&1
```

---

### Hasznos parancsok
```bash
docker compose logs -f backend      # backend logok
docker compose restart backend      # újraindítás
docker compose up -d --build        # kód frissítés után újrabuild
docker compose down                 # leállítás (adat marad a volume-ban)
```
