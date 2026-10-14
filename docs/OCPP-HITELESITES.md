# OCPP töltő-hitelesítés (Security Profile 2) – állapot és bevezetési terv

2026-10-14. Kód: `app/ocpp/auth.py`, `app/ocpp/ws.py`, `app/ocpp/registry.py`,
admin végpontok: `app/api/routers/admin.py` („OCPP hitelesítés" blokk). Migráció: `d4e8f1a2b3c5`.

## 1. Kiinduló állapot (audit, 2026-10-14)

**Útvonal:** töltő → Cloudflare edge (`ocpp.energiafelho.hu`) → Cloudflare tunnel (titkosított) →
`cloudflared` konténer → `http://backend:8000` (a compose belső hálóján). A backend portja csak a
szerver localhostján van kint (`127.0.0.1:8010`), publikusan kizárólag a tunnelen érhető el.

| Kérdés | Megállapítás |
|---|---|
| TLS a töltőtől? | **Az 6 publikus töltőből 5 titkosítatlan `ws://ocpp.energiafelho.hu/ocpp`-vel kapcsolódik** (`OCPPBackendJSONURL`, GetConfiguration). Egy (`Nograd-Var-2-uj`) már `wss://`-sel – ez bizonyítja, hogy az edge elfogadja a wss-t és a Voltie firmware (1.3.54-3.75) tudja. A Cloudflare a `http://`-t nem irányítja át, ezért a ws:// is működik. |
| TLS edge → backend? | Cloudflare tunnel (titkosított), a szerveren belül a konténerek közt sima HTTP. |
| Hitelesítés? | **Semmi.** A backend csak az URL-ben lévő ocpp_id-t nézte; nem volt Basic Auth, nem volt jelszó. Aki ismeri egy töltő azonosítóját, a töltő nevében kapcsolódhatott (hamis státusz/mérés, a valódi töltő „lerúgása"). |
| Ismeretlen ocpp_id? | **Nem utasítottuk el**: a kapcsolat létrejön, és egy BootNotification publikálatlan („konfigurálásra vár") töltőt hoz létre. Ez szándékos onboarding-funkció; publikálatlan töltőre nem indítható fizetés, nem látszik a térképen és az OCPI-ban. |
| Második kapcsolat ugyanarra az id-ra? | A régi kapcsolat nyitva maradt, a registry minden üzenetnél átíródott → két élő kapcsolat felváltva „vitte" a töltőt. |
| Töltő-oldali beállítások | `SupportedFeatureProfiles = Core,LocalAuthListManagement,RemoteTrigger` (Security profil nincs listázva); `AuthorizationKey` kulcs létezik (értéke rejtett, lehet üres); `AllowOfflineTxForUnknownId=true`, `LocalAuthorizeOffline=true`, `RFIDEnabled=false`, `FreeChargingMode=0`, `RFIDTagFreeCharging=0A1B2C3D`. |
| Backend Authorize | Az `Authorize` és a `StartTransaction` **minden idTag-et elfogad** (lásd 6. pont). |

## 2. Mi változott a backendben (élesítve `log` módban)

- **Töltőnkénti kulcs** (`charge_points.ocpp_auth_key_hash`): a kulcsot a backend generálja
  (32 hex karakter = 16 véletlen bájt), a DB-ben csak PBKDF2-SHA256 hash van.
- **Basic Auth ellenőrzés a kézfogáskor**: felhasználónév = ocpp_id, jelszó = a kulcs. Mivel a
  1.6-os whitepaper a kulcsot hex-ben adja meg, és a töltők egy része a hex szöveget, más része a
  dekódolt 20 bájtot küldi jelszóként, **mindkét alakot elfogadjuk**.
- **Mód** – `OCPP_AUTH_MODE` env (alap `log`):
  - `off`: semmi ellenőrzés (csak a séma rögzül);
  - `log`: mindenki kapcsolódhat (ws:// is!), de töltőnként rögzül és naplózódik az eredmény:
    `ok` / `missing` (nem küldött jelszót) / `wrong` / `no_key` (nincs kulcs a DB-ben);
    titkosítatlan kapcsolatnál figyelmeztetés a logban;
  - `enforce`: csak **wss**-en, **helyes** Basic Auth-tal, **ismert** töltő kapcsolódhat;
    hiányzó/rossz jelszó → HTTP 401, ws:// vagy ismeretlen id → 403.
- **Rögzítés töltőnként** (`ocpp_auth_last_result`, `ocpp_auth_last_at`, `ocpp_last_scheme`) –
  az admin töltőlistában (`ocpp_auth` mező) látszik. A séma a Cloudflare `CF-Visitor` /
  `X-Forwarded-Proto` fejlécéből jön (a backend csak a tunnelen érhető el, így megbízható).
- **Duplikált kapcsolat szabálya**:
  1. ha a meglévő kapcsolat **hitelesített**, egy **nem hitelesített** új kapcsolatot
     elutasítunk (HTTP 409) – jelszó nélkül senki nem rúghatja le a valódi töltőt (log módban is);
  2. minden más esetben az **új kapcsolat nyer**, a régit a backend lezárja (code 4000). Ez kell
     ahhoz, hogy egy hálózati kiesés után újracsatlakozó töltő ne ragadjon ki egy félig halott
     régi kapcsolat miatt; a lezárással megszűnt a két élő kapcsolat váltakozása is.
  A bevezetés előtt (senkinek nincs kulcsa) ez a régi „legújabb nyer" viselkedés.
- **Ismeretlen ocpp_id**: `off`/`log` módban beengedjük (onboarding, mint eddig, figyelmeztető
  loggal); `enforce` módban elutasítjuk. Enforce mellett új töltő felvétele: előbb a töltő sorát
  kell létrehozni és kulcsot generálni (vagy a felvétel idejére `log` mód).

### Admin végpontok (Keycloak `ev-admin` / vész-Basic)

| Végpont | Mit csinál |
|---|---|
| `POST /api/admin/charge-points/{id}/ocpp-auth-key` | Új kulcs; **egyszer** adja vissza a kulcsot + a kész `ChangeConfiguration` payloadot (`{"key":"AuthorizationKey","value":"…"}`). **Nem küld semmit a töltőnek.** A régi kulcs hash-e felülíródik. |
| `DELETE /api/admin/charge-points/{id}/ocpp-auth-key` | Kulcs törlése (visszaállítás; log módban utána `no_key`). |
| `POST /api/admin/charge-points/{id}/ocpp-auth-key/apply` body `{"key":"…"}` | A `ChangeConfiguration(AuthorizationKey)` kiküldése. **Alapból tiltva** (403), csak `OCPP_AUTH_APPLY_ENABLED=true` mellett működik, és csak a tárolt hash-sel egyező kulccsal (elgépelés ellen). |
| `GET /api/admin/charge-points/{id}/config` | (meglévő) GetConfiguration – csak olvas. |
| `POST /api/admin/charge-points/{id}/config` body `{"key","value"}` | ChangeConfiguration **szűk allowlisttel**: most csak `CurrentLimitUser`, `CurrentLimitDefault` (egész amper, 6..`CurrentLimitHardware`, a töltőből visszaolvasva), valamint `OCPPBackendJSONURL` KIZÁRÓLAG a `wss://ocpp.energiafelho.hu/ocpp` értékkel (jóváhagyva 2026-10-14). A régi→új érték naplózva. Az AuthorizationKey és az offline-kulcsok itt szándékosan nem engedélyezettek. |

Az `OCPPBackendJSONURL` átírására nincs külön végpont; ezt a jóváhagyott bevezetéskor egy
egyszeri, admin-hitelesített hívással (vagy a Voltie saját felületén) kell elvégezni.

## 3. Bevezetési terv – töltőnként (Gellért jóváhagyásával)

Előfeltétel: a backend `OCPP_AUTH_MODE=log`-ban fut (ez már éles), aktív töltés nincs a töltőn.
Az első töltőt olyan helyen válasszuk, ahol baj esetén helyszínen / a Voltie felületén hozzá
lehet férni. Egyszerre **egy** töltő; a következőre csak az előző igazolása után lépünk.

**A. lépés – TLS (wss) – alacsony kockázat** (a `Nograd-Var-2-uj` már így megy):
1. `GET /api/admin/charge-points/{id}/config` → jegyezzük fel az `OCPPBackendJSONURL` mostani értékét.
2. `ChangeConfiguration OCPPBackendJSONURL = wss://ocpp.energiafelho.hu/ocpp` (ha a töltő
   `RebootRequired`-et ad: Soft reset töltés nélküli időben).
3. Ellenőrzés: a töltő visszacsatlakozik; az admin listában `ocpp_auth.last_scheme = "wss"`,
   `last_seen_at` friss, a logban nincs „TITKOSÍTATLAN ws://" sor erre a töltőre.
4. Visszaállítás, ha nem csatlakozik vissza: a töltő nem elérhető OCPP-n, ezért a Voltie felületén
   / helyszínen az URL vissza `ws://ocpp.energiafelho.hu/ocpp`-re. (A backend mindkettőt fogadja.)

**B. lépés – kulcs (Basic Auth) – óvatosan, töltőnként:**
1. `POST …/ocpp-auth-key` → a kulcsot biztonságosan eltesszük (jelszókezelő; a backend később nem adja vissza).
2. Jóváhagyás után `OCPP_AUTH_APPLY_ENABLED=true` (env + backend újraindítás aktív töltés nélkül),
   majd `POST …/ocpp-auth-key/apply` a kulccsal → a töltő válasza `Accepted` (vagy `RebootRequired`).
3. A töltő új kapcsolatánál (újracsatlakozás / reset után) az admin listában
   `ocpp_auth.last_result = "ok"` és `last_scheme = "wss"`. Ha `missing`: a firmware nem küld
   Basic Auth-ot ezzel a beállítással (lásd 4. pont: SecurityProfile) – log módban ez nem baj, a
   töltő megy tovább, de enforce-ra így nem állhatunk át. Ha `wrong`: a kulcs/értelmezés eltér →
   új kulcs, újra.
4. Visszaállítás: `ChangeConfiguration AuthorizationKey = ""` (amíg a töltő kapcsolódik – log
   módban mindig kapcsolódik), és `DELETE …/ocpp-auth-key`.
5. Következő töltő. Az összes töltő végén `OCPP_AUTH_APPLY_ENABLED` vissza `false`.

**C. lépés – enforce:** ha mind a 6 publikus töltő legalább egy napja `ok` + `wss`:
`OCPP_AUTH_MODE=enforce`, backend újraindítás aktív töltés nélkül. Ellenőrzés: mind visszajön,
`last_result = ok`. Visszaállítás: `OCPP_AUTH_MODE=log` + újraindítás (azonnal mindenkit beenged).

### Mit kell Gellértnek jóváhagynia

1. Az `OCPPBackendJSONURL` átírását `wss://`-re (töltőnként, A. lépés).
2. A töltőnkénti `AuthorizationKey` kiküldését (`OCPP_AUTH_APPLY_ENABLED=true` ideiglenesen; B. lépés).
3. Az átállást `OCPP_AUTH_MODE=enforce`-ra (C. lépés).
4. A 5. pont töltő-beállításait.

## 4. Voltie-specifikus tudnivalók és nyitott kérdések

- Firmware: mind a 6 publikus töltő 1.3.54-3.75. A wss működik (bizonyított).
- `AuthorizationKey` létezik a konfigurációban (write-only/rejtett). Nem igazolt még, hogy a
  firmware ennek beállítása után **küld-e** Basic Auth fejlécet, és hogy a hex szöveget vagy a
  dekódolt bájtokat küldi-e – a backend mindkettőt elfogadja, az első töltő (B.3) eldönti.
- A `SupportedFeatureProfiles` nem listázza a Security profilt. Ha a GetConfiguration-ben van
  `SecurityProfile` kulcs, a Basic Auth-hoz annak értéke `2` kell legyen (TLS + Basic) – **a kulcs
  és az URL beállítása után**, mert a 2-es profil wss-t vár. Ha nincs ilyen kulcs, a firmware
  valószínűleg a nem üres `AuthorizationKey` alapján dönt; a Voltie supporttól érdemes megkérdezni.
- **Igazolva (2026-10-14, nadudvar_spar_2):** a Voltie a 40 hex karakteres kulcsot `Rejected`-del
  elutasítja, a 32 hex karakterest (16 bájt) elfogadja. A kulcs beállítása nem bontja a kapcsolatot;
  Soft reset után a töltő Basic Auth-tal jön vissza (`OCPP auth OK`, wss), a hex szöveget küldi jelszóként.
  Külön `SecurityProfile` kulcs nincs: a nem üres `AuthorizationKey` kapcsolja be a Basic Auth-ot.
- Kulcs-formátum: 32 hex karakter (16 bájt) – a whitepaper 16–20 bájtos ajánlásán belül, és csak
  `[0-9a-f]` karaktert tartalmaz, ami minden értelmezésben (hex / ASCII) biztonságos.

## 5. Ajánlott töltő-beállítások (jóváhagyásra – NEM módosítottuk)

| Kulcs | Most | Ajánlott | Miért |
|---|---|---|---|
| `AllowOfflineTxForUnknownId` | true | **false** | Offline állapotban ne induljon töltés ismeretlen azonosítóval (fizetés nélküli töltés). |
| `LocalAuthorizeOffline` | true | **false** (vagy: csak üres helyi listával) | Offline helyi engedélyezés nem kell – nálunk minden töltés online fizetéssel indul. |
| `RFIDTagFreeCharging` | `0A1B2C3D` | **üres** / véletlen érték | Ismert (gyári mintájú) „ingyen töltés" kártya-azonosító; ha az RFID-t valaha bekapcsolják, ez kártyával ingyen töltést adhat. |
| `RFIDEnabled` | false | false | Maradjon. |
| `FreeChargingMode` | 0 | 0 | Maradjon. |

Megjegyzés: a `ChangeConfiguration` ezekre egyesével, töltés nélküli időben, töltőnként
GetConfiguration-ellenőrzéssel; visszaállítás = az előző érték visszaírása.

## 6. További javaslatok (nem ebben a körben)

- A backend `Authorize` / `StartTransaction` válasza minden idTag-re `Accepted`. Mivel a töltés
  a RemoteStart `ANON` tagjével indul, érdemes lenne minden más idTag-et elutasítani (Invalid) –
  ez a helyi (RFID/offline) ingyen-töltés lehetőségét a backend oldaláról is lezárná. A változtatás
  előtt egy töltőn ellenőrizni kell, milyen idTag-gel jön a StartTransaction távoli indításnál.
- Az ocpp_id ma is szerepel a vásárlói e-mailekben („Töltő azonosító") és a bejelentkezett
  ügyfél `/api/me/sessions` válaszában (a portál szerződése). Enforce előtt ez a töltő
  megszemélyesítésének egyik kulcsa; érdemes a helyszín nevére cserélni.
