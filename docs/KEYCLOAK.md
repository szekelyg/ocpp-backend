# Egységes Energiafelhő-fiók (Keycloak) az ev.energiafelho.hu-n

Ág: `w4-keycloak`. A töltő-backend a meglévő e-mail-kódos belépés **mellett** elfogadja a
`https://id.energiafelho.hu` (realm `ugyfelek`) access tokenjeit, a SPA-ban van
„Belépés Energiafelhő-fiókkal" gomb, és van egy `GET /api/me/sessions` végpont, amit a
portál (my.energiafelho.hu) is hív. A vendég (regisztráció nélküli) út változatlan.

## 1. Keycloak-beállítás (realm `ugyfelek`)

### Kliens `ev` (a SPA)

| Beállítás | Érték |
|---|---|
| Client ID | `ev` |
| Client type | OpenID Connect, **public** (Client authentication: **Off**) |
| Standard flow | **On** (Authorization Code) |
| Direct access grants, Implicit flow, Service accounts | **Off** |
| PKCE | Advanced → *Proof Key for Code Exchange Code Challenge Method*: **S256** |
| Valid redirect URIs | `https://ev.energiafelho.hu/auth/keycloak/callback` |
| Valid post logout redirect URIs | `https://ev.energiafelho.hu/*` (a kijelentkezés `/` vagy `/toltesek` alá tér vissza) |
| Web origins | `https://ev.energiafelho.hu` (a token endpoint CORS-a ettől függ – enélkül a code→token csere elbukik a böngészőben) |
| Front channel logout | On (alapértelmezés jó) |

Fejlesztéshez (Vite dev szerver) plusz redirect URI: `http://localhost:5173/auth/keycloak/callback`,
web origin: `http://localhost:5173`. A PKCE-hez `crypto.subtle` kell, ami `localhost`-on is elérhető.

**Audience.** A backend a tokent akkor fogadja el, ha az `aud` tartalmazza az `ev`-t **VAGY**
az `azp` (a tokent kérő kliens) az `ev` **vagy** az engedélyezett listában van
(`KEYCLOAK_ALLOWED_AZP`). Az `ev` kliens saját tokenjében az `azp` = `ev`, az `aud`-ban a
Keycloak alapból csak `account` van – ez így is elfogadott, **nem kell audience-mapper az `ev`
klienshez**. (Ha mégis raktok: Client scopes → `ev-dedicated` → Add mapper → *Audience*,
Included Client Audience: `ev`, Add to access token: On – nem árt, de nem szükséges.)

Kötelező claimek az access tokenben: `sub`, `iss`, `exp`, `iat`, `email`, `email_verified`
(az `email` és `profile` scope alapból hozza; `name`/`preferred_username` a kijelzéshez).
A backend **csak `email_verified=true`** mellett köti össze a fiókot – Keycloakban a
*Verify email* legyen bekapcsolva a realmben, különben minden Keycloak-belépés 403-at kap.

### Portál (my.energiafelho.hu) tokenje

A portál a saját Keycloak-kliensével (pl. `portal`) kér tokent, és azt küldi a
`GET https://ev.energiafelho.hu/api/me/sessions`-nek. Két lehetőség:

- `KEYCLOAK_ALLOWED_AZP=portal` a szerver `.env`-jében (a portál kliens-ID-jével), **vagy**
- Audience mapper a portál kliensén, ami az `ev`-t is beleteszi az `aud`-ba (a jelenlegi mapper
  csak az `ek`-t adja). Ha ezt választjátok, nem kell `KEYCLOAK_ALLOWED_AZP`.

Az `azp`-alapú elfogadás egyenértékű biztonságilag (az aláírás és az `iss` ugyanúgy ellenőrzött),
csak azt mondja ki, hogy melyik saját klienseink tokenjét fogadjuk el.

## 2. Backend env (`deploy/.env` a szerveren)

```
KEYCLOAK_ISSUER=https://id.energiafelho.hu/realms/ugyfelek
KEYCLOAK_AUDIENCE=ev
KEYCLOAK_ALLOWED_AZP=portal          # a portál Keycloak-kliensének ID-ja (az `ev` mindig elfogadott)
# opcionális:
# KEYCLOAK_JWKS_URL=https://id.energiafelho.hu/realms/ugyfelek/protocol/openid-connect/certs
# KEYCLOAK_JWKS_TTL_S=3600
# KEYCLOAK_SPA_CLIENT_ID=ev          # ha a SPA kliens-ID-ja eltérne az audience-től
# PORTAL_ORIGINS=https://my.energiafelho.hu   # CORS a /api/me/* útvonalon (alapból ez)
```

- **Fail-closed:** `KEYCLOAK_ISSUER` nélkül minden JWT-nek kinéző token 401
  (`keycloak_keycloak_disabled`), a SPA-ban a gomb nem jelenik meg
  (`GET /api/auth/keycloak/config` → `{"enabled": false}`). Az e-mail-kódos belépés és a
  vendég-folyamat ettől függetlenül működik.
- Új Python-függőség: `PyJWT[crypto]` (`requirements.txt`, `deploy/requirements.txt` pinned).
  A Docker build magától felrakja.
- Migráció: `e5c1a7b3d9f2` – `users.keycloak_sub` (nullable, unique). Additív; az
  `entrypoint.sh` `alembic upgrade head`-je viszi fel. A `deploy.sh` változatlan.

## 3. Hogyan ellenőrzi a backend a tokent (`app/services/keycloak.py`)

1. `Authorization: Bearer <token>`. Ha a token `v1.`/`v1i.` prefixű (4 szegmens) → a régi
   HMAC-ellenőrzés (`auth_tokens.verify_token`), különben Keycloak-JWT.
2. Fejléc: `alg` ∈ RS256/384/512, ES256/384/512 (`none`, HS* tiltva – a nyilvános kulccsal
   „aláírt" HS-token nem játszik), `kid` kötelező.
3. JWKS a `{issuer}/protocol/openid-connect/certs`-ről, processzenként cache-elve
   (`KEYCLOAK_JWKS_TTL_S`, alap 1 óra). Ismeretlen `kid` → egyszeri újratöltés (kulcsforgatás),
   de legfeljebb percenként egyszer (hamis kid-del nem lehet a Keycloakot terhelni).
4. `jwt.decode`: aláírás, `iss` pontos egyezés, `exp`/`iat`/`sub` kötelező, 30 mp leeway.
5. `aud` tartalmazza `KEYCLOAK_AUDIENCE`-t **vagy** `azp` = `KEYCLOAK_AUDIENCE` **vagy** `azp` ∈ `KEYCLOAK_ALLOWED_AZP`.
6. `typ` (Keycloak payload-claim) ha van, csak `Bearer` – ID- és refresh-token nem jó.
7. `email` kötelező (kisbetűsítve), `email_verified` **true** kell az összekötéshez;
   különben 403 `keycloak_email_not_verified`, semmi nem íródik.
8. Összekötés: `users` sor e-mail alapján; ha nincs, létrejön `keycloak_sub`-bal; ha van és
   `keycloak_sub` üres, kitöltődik. A kulcs továbbra is az e-mail (a `charge_sessions` és a
   számlázási profil is e-mailhez kötött).

Közös függőség: `app.api.deps.get_current_identity` → `Identity(email, source, keycloak_sub, name)`;
`get_optional_identity` (header nélkül `None`, rossz tokennel 401 – nem esik vissza csendben
vendég-módba); `email_from_authorization` (nem dob) ott, ahol a Bearer csak egy a bizonyítékok
közül (`POST /api/sessions/{id}/stop`).

Az admin Basic auth (`verify_admin`) és az `/api/admin/*` végpontok érintetlenek.

## 4. Végpontok

### `GET /api/auth/keycloak/config` (publikus)

```json
{ "enabled": true, "client_id": "ev", "issuer": "…/realms/ugyfelek",
  "authorization_endpoint": "…/protocol/openid-connect/auth",
  "token_endpoint": "…/protocol/openid-connect/token",
  "end_session_endpoint": "…/protocol/openid-connect/logout" }
```
A SPA ebből indítja a PKCE-folyamatot; discovery-t a backend olvassa (6 órás cache).

### `GET /api/me` (Bearer)

```json
{ "ok": true, "email": "ugyfel@example.hu", "name": "Ügyfél Ubul",
  "auth_source": "keycloak" | "email_token", "keycloak_linked": true,
  "profile": { "email", "billing_type", "billing_name", "billing_street", "billing_zip",
               "billing_city", "billing_country", "billing_company", "billing_tax_number" } | null }
```

### `GET /api/me/sessions?limit=20&offset=0` (Bearer) – **a portál szerződése**

```json
{
  "ok": true, "email": "ugyfel@example.hu",
  "sessions": [
    {
      "id": 123,
      "charge_point": { "id": 4, "ocpp_id": "VLTHU_NOGRAD01",
                        "name": "Nógrádi vár parkoló", "address": "3132 Nógrád, Vár út 1." },
      "connector_id": 1,
      "started_at": "2026-09-21T10:12:00+00:00", "finished_at": "2026-09-21T12:03:41+00:00",
      "duration_s": 6701,
      "energy_kwh": 12.34, "cost_huf": 2098, "currency": "HUF",
      "status": "finished",            // active | waiting | finished | timed_out
      "invoice_number": "EV-2026-0042",
      "invoice_url": "/api/me/sessions/123/invoice"   // null, ha nincs számla
    }
  ],
  "total": 3, "limit": 20, "offset": 0,
  "total_kwh": 15.54, "total_huf": 2642, "currency": "HUF"
}
```

- Csak a bejelentkezett e-mail (`lower(charge_sessions.anonymous_email)`) töltései; más
  e-mail sohasem. Ismeretlen e-mail → üres lista, `total: 0` (nem 403).
- `total_kwh` / `total_huf` az **összes** saját töltésre vonatkozik, nem csak a lapra.
- `limit` 1–100, `offset` ≥ 0; rendezés: kezdés szerint csökkenő.
- `invoice_url` relatív az ev backendhez (`https://ev.energiafelho.hu` + url), **Bearer kell
  hozzá** – nem közvetlen Számlázz.hu-link. `GET` → `application/pdf`
  (`Content-Disposition: inline`), idegen/számlátlan session → 404, Számlázz.hu-hiba → 502.
- Hibák: 401 `missing_bearer_token` / `invalid_or_expired_token` / `keycloak_<ok>`,
  403 `keycloak_email_not_verified`.

CORS: a `/api/me/*` útvonalon a `PORTAL_ORIGINS` (alap `https://my.energiafelho.hu`) originre,
`GET`/`OPTIONS`, `Authorization` header engedve, **`allow_credentials=false`** (no-cookie, csak
Bearer). Más útvonalon nincs CORS – a portál csak a `/api/me/*`-t hívja.

Portál-oldali hívás:
```js
const r = await fetch("https://ev.energiafelho.hu/api/me/sessions?limit=20", {
  headers: { Authorization: `Bearer ${accessToken}`, Accept: "application/json" },
});
const { sessions, total_kwh, total_huf } = await r.json();
```

### Meglévő végpontok, amelyek tudnak a bejelentkezésről

- `POST /api/intents/` – Bearerrel a **fiók e-mailje** kerül az intentre (a body `email`
  figyelmen kívül), így a session a fiókhoz kötődik; a hiányzó számlázási mezők a `users`
  mentett profiljából egészülnek ki. Vendégként minden marad, ahogy volt (`email` + számlázás
  kötelező). Rossz/lejárt Bearer → 401 (a SPA ilyenkor törli a helyi belépést és a felhasználó
  vendégként folytathatja).
- `POST /api/sessions/{id}/stop` – intent-token **vagy** a tulajdonos Bearer-je (mindkét fajta).
- `GET /api/auth/profile` – változatlan (csak e-mail-token); a SPA már a `/api/me`-t használja.

## 5. SPA (frontend)

- `src/utils/auth.js`: token-tárolás (`localStorage.ef_auth_token` = e-mail-token, ahogy eddig;
  `localStorage.ef_kc_session` = Keycloak access/refresh/id token + lejárat), PKCE indítás
  (`startKeycloakLogin({ returnTo })`), callback (`completeKeycloakLogin`), access token
  frissítés refresh tokennel 30 mp-cel a lejárat előtt, `apiFetch` (Bearer + 401-re törlés),
  `logout()` → Keycloak end-session `id_token_hint`-tel, majd vissza.
- Útvonalak: `/auth/keycloak/callback`, `/toltesek` („Töltéseim"). Fejlécben „Belépés /
  Töltéseim", belépve az e-mail + „Kilépés".
- Töltő fizetési űrlap: belépve a `/api/me` profilja előtöltve, az e-mail mező csak olvasható,
  „Vendégként" gombbal elengedhető. A „Belépés Energiafelhő-fiókkal" gomb a `?cp=<id>`
  útvonalra hoz vissza, ami újra megnyitja a fizetési ablakot.
- A Keycloak access token alapból 5 perces – ezért kell a refresh; az SSO session idle
  (alap 30 perc) / max (10 óra) lejártakor a SPA „kijelentkezett" állapotba esik, a vendég-út
  akkor is működik.

## 6. Tesztek

`tests/test_keycloak_auth.py` (30 teszt, Dockerben: `docker compose -f docker-compose.dev.yml
run --rm --no-deps backend pytest`): saját RSA-kulcspár + mockolt JWKS/discovery
(`httpx.AsyncClient` helyettesítve); elutasított tokenek: lejárt, rossz `iss`, rossz
`aud`/`azp`, `none`, HS256 a nyilvános kulccsal, idegen kulcs, ismeretlen `kid` (+ újratöltés
throttle), ID/refresh `typ`, hiányzó `exp`/`email`; `email_verified=false` → 403 és nincs
összekötés; kikapcsolt Keycloak → 401, e-mail-token továbbra is jó; `/api/me/sessions` csak
saját e-mail (kis/nagybetű független), lapozás, összesítés, számla-PDF csak sajátra; CORS csak
`/api/me/*` + portál origin; stop Keycloak-tokennel; intents SSO (fiók e-mail + profil), vendég
kötelező mezők, rossz Bearer → 401. A korábbi 78 teszt változatlanul zöld (összesen 108).

## 7. Élesítés

1. Keycloak: `ev` kliens bekapcsolása a fenti beállításokkal; `KEYCLOAK_ALLOWED_AZP`-hez a
   portál kliens-ID-ja (vagy audience-mapper).
2. Szerver `.env`: a 2. pont sorai.
3. `./deploy.sh` (változatlan) – build felrakja a PyJWT-t, a migráció felmegy.
4. Ellenőrzés: `curl https://ev.energiafelho.hu/api/auth/keycloak/config` → `enabled: true`;
   böngészőben `/toltesek` → „Belépés Energiafelhő-fiókkal" → Keycloak → vissza → lista.
