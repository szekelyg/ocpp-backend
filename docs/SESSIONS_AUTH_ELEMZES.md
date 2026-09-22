# Session- és intent-végpontok hozzáférés-elemzése

Ág: `fix/sessions-auth`. Kiindulópont: audit-jelzés, hogy a `GET /api/sessions/` lista és a
`POST /api/sessions/{id}/stop` hitelesítés nélkül elérhető az internetről, és a
`POST /api/intents/` auth nélkül ír a `users` táblába.

## Mi volt tényleg nyitva (a kód alapján, javítás előtt)

- **`POST /api/sessions/{session_id}/stop` – az audit igaz.** A docstring is "Publikus stop – kód
  nélkül". Semmilyen ellenőrzés nem volt: bárki, aki kitalál egy session-id-t (sorszámos egész),
  leállíthatta bármelyik futó töltést. A `charge_sessions.stop_code_hash` oszlop létezik
  (migráció `42af0485197b`), de a kód **soha nem tölti ki** (`payments_stripe.py` explicit
  `stop_code_hash=None`-nal hozza létre a sessiont) és sehol nem ellenőrzi – a "stop-kód"
  mechanizmus csak séma-szinten létezett.
- **`GET /api/sessions/` – az audit igaz.** Teljes session-lista szűrőkkel, auth nélkül.
  A frontend egyik oldala sem használja (az admin a `/api/admin/sessions`-t hívja Basic auth-tal),
  vagyis védeni nem-törő.
- **`GET /api/sessions/active/by-charge-point/{cp_id}`** – szintén nyitott, szűrt lista
  (töltőnkénti aktív session). Sehonnan nincs hívva. A stop-lyukkal együtt ez adta a
  "melyik session-t állítsam le" információt is.
- **`POST /api/intents/`** – szándékosan nyilvános (ez a vendég-fizetés belépője), de a
  `save_profile=true` esetén **azonnal, fizetés előtt** upsertelt a `users` táblába tetszőleges
  e-mail-címre. Rate-limit nem volt semmilyen végponton (nincs slowapi/middleware; az egyetlen
  meglévő anti-spam minta az `/auth/request-code` DB-alapú cooldownja).

Nem volt lyuk: `POST /api/sessions/start` és `POST /api/sessions/stop` (body-s, admin) már
`verify_admin`-nal védett; az `/api/admin/*` végpontok mind `verify_admin`-t használnak.

## Hitelesítési mechanizmusok

| Mechanizmus | Hol | Mire |
|---|---|---|
| **Admin Basic auth** – `verify_admin` (`admin.py`): `ADMIN_USERNAME`/`ADMIN_PASSWORD` env, `secrets.compare_digest`, `ADMIN_PASSWORD` nélkül 503 (fail-closed) | `/api/admin/*`, `/api/sessions/start`, `/api/sessions/stop`, **most már** `/api/sessions/` és `/active/by-charge-point` | AdminPage (`sessionStorage.admin_token`, Basic) |
| **E-mail OTP → Bearer HMAC-token** – `auth_tokens.issue_token/verify_token`, `get_current_email` (`auth.py`); titok: `AUTH_SECRET` (fallback `STRIPE_WEBHOOK_SECRET`) | `/api/auth/profile`; **most már** a publikus stop tartalék útja | Számlázási profil autofill (LoginAutofill, `localStorage.ef_auth_token`) |
| **Intent-token (új)** – `auth_tokens.issue_intent_token/verify_intent_token`: ugyanaz az aláírt formátum, de külön típus-prefix (`v1i`, az aláírt payload része – e-mail-tokenné nem címkézhető át és fordítva), alany `intent:<id>`, 7 nap TTL | `POST /api/intents/` adja ki a Stripe `success_url`-ben (`&t=`), a "töltés elindult" e-mail linkjében; `POST /api/sessions/{id}/stop` ellenőrzi | Vendég-folyamat, regisztráció nélkül |
| **Stripe webhook aláírás** – `_verify_stripe_signature` | `/api/payments/stripe/webhook` | Stripe |
| OCPI Token A/C | `/ocpi/*` | roaming partnerek |

## Vendég-folyamat (regisztráció nélkül) – ez nem törhet el

1. Home → `GET /api/charge-points/` (publikus, csak publikált töltők).
2. SelectedChargerCard → `POST /api/intents/` (e-mail + számlázási adatok) → `checkout_url`
   → Stripe. A backend a `success_url`-t `…/pay/success?intent_id=N&t=<intent-token>`-re állítja.
3. Stripe visszairányít → PaySuccess pollozza `GET /api/sessions/by-intent/{intent_id}` (publikus),
   majd `navigate('/charging/{session_id}?t=<intent-token>')`.
4. ChargingPage pollozza `GET /api/sessions/{id}` (publikus), a tokent `sessionStorage`-ba menti és
   `history.replaceState`-tel kiveszi az URL-ből (ne kerüljön Refererbe / előzménybe).
   Stop gomb → `POST /api/sessions/{id}/stop` body `{ token }` (+ `Authorization: Bearer`, ha
   az OTP-s belépés tokenje megvan a `localStorage`-ban).
5. Webhook (`checkout.session.completed`) → ChargeSession + RemoteStart + "töltés elindult"
   e-mail, a linkje `…/charging/{id}?t=<intent-token>`.

Az admin teszt-töltés (`/api/admin/charge-points/{id}/test-charge`) ugyanezen az úton megy,
ezért ott is bekerült a token a `success_url`-be.

## Végpont-táblázat

| Végpont | Ki hívja | Védelem eddig | Védelem most / javasolt |
|---|---|---|---|
| `GET /api/sessions/` | senki (admin a `/api/admin/sessions`-t használja) | **nincs** | **admin Basic** (`verify_admin`) |
| `GET /api/sessions/active/by-charge-point/{cp_id}` | senki | **nincs** | **admin Basic** |
| `GET /api/sessions/by-intent/{intent_id}` | PaySuccess (vendég) | nincs | változatlanul publikus (session-id + állapot; e-mailt nem ad vissza) – later: token-kötés |
| `GET /api/sessions/{id}` | ChargingPage (vendég), polling 3 mp | nincs | változatlanul publikus (fogyasztás/ár/státusz, e-mail nélkül) – later: token-kötés |
| `POST /api/sessions/{id}/stop` | ChargingPage (vendég), admin teszt-töltés | **nincs** | **intent-token a body-ban VAGY a session e-mailjéhez tartozó Bearer-token; különben 403** |
| `POST /api/sessions/start` | senki (admin eszköz) | admin Basic | változatlan |
| `POST /api/sessions/stop` | senki (admin eszköz) | admin Basic | változatlan |
| `POST /api/intents/` | SelectedChargerCard (vendég), | nincs; `save_profile` → azonnali `users` upsert | publikus marad; **`users`-írás átkerült a fizetett webhookba** (Stripe metadata `save_profile`); **e-mail-enkénti throttle**: max 10 intent / 15 perc / e-mail (429) |
| `POST /api/payments/stripe/webhook` | Stripe | aláírás | változatlan (+ profil mentése `save_profile=="1"` esetén) |
| `POST /api/auth/request-code`, `verify-code` | LoginAutofill | DB-cooldown 45 s, max 5 próbálkozás | változatlan *(2026-09-22 óta: megszűnt, 410 – a fiókos belépés csak Keycloak, lásd `KEYCLOAK.md` 0.)* |
| `GET /api/auth/profile` | SelectedChargerCard | Bearer | változatlan |
| `/api/admin/*` | AdminPage | admin Basic | változatlan |

## Mit csinál a javítás (diff: 9 fájl + 1 új teszt, ~170 sor)

- `app/services/auth_tokens.py`: `issue_intent_token`, `verify_intent_token` (a meglévő HMAC
  tokenre építve; nincs új titok, nincs migráció, nincs új függőség).
- `app/api/routers/sessions.py`: lista és by-charge-point `verify_admin`; publikus stop
  `_may_stop_session` – intent-token vagy saját e-mail Bearer; 403 `stop_not_authorized` + hint.
- `app/api/routers/intents.py`: token a `success_url`-ben; `save_profile` a Stripe metadatába;
  `users`-írás törölve innen; e-mail-enkénti throttle (DB-count, mint a request-code cooldown).
- `app/api/routers/payments_stripe.py`: `_save_billing_profile` a webhookban, token az e-mailbe.
- `app/api/routers/admin.py`: token a teszt-töltés `success_url`-jébe.
- `app/services/email.py`: `send_charging_started_email(..., intent_token)`.
- Frontend: PaySuccess továbbadja a `t`-t; ChargingPage sessionStorage-ba menti és a stop
  body-jában küldi (+ Bearer tartalék); SelectedChargerCard a `detail.hint`-et mutatja 429-nél.

## Ismert kompromisszumok / javaslatok (nem került bele)

- **Átmenet deploykor**: a deploy pillanatában futó töltések vendégei token nélküli
  `/charging/{id}` oldalon vannak → a web-stop 403-at ad nekik (a hint elmondja, hogy a
  töltőn/autóban állíthatják le; vagy e-mail-kóddal belépve a Home-on, majd vissza). Ezért
  érdemes akkor deployolni, amikor nincs aktív session (`finished_at is null`).
- **IP-alapú rate limit** nincs (nincs ilyen infrastruktúra; a `slowapi` vagy egy kis
  in-memory ablak bevezethető). Mivel az éles backend csak a Cloudflare tunnelen át érhető el,
  a `CF-Connecting-IP` fejléc megbízható lenne kulcsként; alternatíva a Cloudflare WAF
  rate-limiting szabály a `/api/intents/` és `/api/auth/request-code` útvonalakra – ehhez kód
  sem kell.
- `GET /api/sessions/{id}` és `by-intent` továbbra is publikus, mert a vendég-oldal
  pollozza; e-mail-t nem ad ki, de fogyasztást/költséget igen. Következő lépés lehet a
  `?t=` token kötelezővé tétele ezekre is (a frontend már birtokolja a tokent).
- A token URL-ben utazik (Stripe success_url, e-mail link) → hozzáférési logokban látszhat;
  csak a saját töltés leállítására jó, 7 nap után lejár.
