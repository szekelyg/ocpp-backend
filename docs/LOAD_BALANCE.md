# Terheléselosztás közös betáplálású töltők között

2026-09-23. Első alkalmazás: **nógrádi vár**, két 22 kW-os Voltie PRO (`nograd_var_1`,
`Nograd-Var-2-uj`) egy 3×32 A-es betápláláson. Cél: egy autónál 22 kW, két autónál 11–11 kW.

## Hogyan működik

- A Voltie **nem tudja az OCPP SmartCharging-profilt** (`SupportedFeatureProfiles = Core,
  LocalAuthListManagement, RemoteTrigger`), viszont van írható saját kulcsa az élő
  áramkorlátra: **`CurrentDynamic`** (amper, fázisonként). Ezt írjuk `ChangeConfiguration`-nel
  (`LOAD_BALANCE_CONFIG_KEY` env, alap `CurrentDynamic`). Visszaolvasható: `CurrentOffered`
  (amit a töltő épp kínál az autónak, töltés közben).
- Beállítás az adminban, töltőnként (Töltők → Beállítás → *Terheléselosztás*): **csoport neve**
  (azonos név = egy betáplálás), **csoport árama** (A/fázis; a tagok közül a legkisebb nem üres
  érték érvényes), **töltő max** (A, alap 32). Üres csoportnév = nincs elosztás.
- Kiosztás (`app/services/load_balance.py`, `allocate()`):
  - *aktív* = nyitott session (`finished_at IS NULL`) **és** elindult tranzakció
    (`ocpp_transaction_id IS NOT NULL`); a fizetés utáni „várakozó" session még nem aktív. Az
    offline, de nyitott sessionű töltőt is aktívnak vesszük (nem tudjuk, hogy nem tölt-e).
  - nincs aktív → mindenki a saját maximumát kapja (22 kW).
  - `n` aktív → aktívak: `csoport_max // n` (min 6 A, max a saját max); tétlenek: a maradék
    (`csoport_max − aktívak`), de legalább **6 A** (IEC 61851-minimum), hogy a következő autó el
    tudjon indulni. Példa 32 A: egy tölt → 32 + 6; kettő tölt → 16 + 16.
  - Rövid túllógás csak a második autó indulásakor: 32 + 6 = 38 A (1,19×In) néhány
    másodpercig, amíg a StartTransaction után kimegy a 16–16. Egy 32 A-es kismegszakító ezt
    tartja (1,13×In tartósan, 1,45×In egy óráig).
- **Betáplálás-védelem a kiküldésnél:** előbb minden *csökkentés*, és csak ha mind sikerült,
  utána a *növelések*. Ha egy csökkentés elbukik (időtúllépés, `Rejected`), a növelés elmarad,
  a percenkénti kör újrapróbálja.
- Mikor fut: `StartTransaction`, `StopTransaction`, `BootNotification` után (ws.py), admin-
  mentés után, és **percenként** ellenőrző körben (`main.py` `_load_balance_loop`) — de csak
  akkor küld, ha az érték eltér az utoljára kiküldöttől (processz-memória; újraindítás/boot
  után újra kimegy).
- Tesztek: `tests/test_load_balance.py` (kiosztás, sorrend, offline, elutasítás, admin, publikus).

## Ügyfél-tájékoztatás

- Publikus `GET /api/charge-points/` → `load_sharing: {group, members, group_max_kw,
  shared_kw, current_limit_kw, shared_now}` (csoporton kívül `null`).
- SPA: a lista-chip („közös betáplálás · együtt 11 kW"), a töltő kártyája és a **fizetés előtti**
  ablak elmondja: egyedül 22 kW, egyidejű töltésnél 11–11 kW; ha a szomszéd épp tölt, „most
  legfeljebb X kW-tal indul".
- Töltés közben `GET /api/sessions/{id}` → `power_limit: {limit_a, limit_kw, cap_kw,
  shared_now}`; a töltés-oldal a teljesítmény alatt kiírja, ha a másik töltő miatt korlátozott.
- ÁSZF 6.9: közös betáplálás, automatikus megosztás, a díj csak a felhasznált kWh.
- A `max_power_kw` (publikus „max. 22 kW" chip, OCPI) a csoportban a **maximum** — a nógrádi
  vár töltőjénél a korábbi 11 kW-os fix korlátot ez váltja ki (22-re állítandó).

## Mérés, számlázás

- A díj kizárólag a `MeterValues` / `StopTransaction` energiaértékeiből számolódik
  (`Energy.Active.Import.Register`), az áramkorlát a mérést nem érinti — a vezető azt fizeti,
  amit az autó felvett. Időalapú díj nincs.
- A Stripe-zárolás / minimum terhelés változatlan.

## Üzemeltetés

- Admin: `GET /api/admin/load-groups` (csoportok, cél/kiküldött amper, hiba),
  `?live=1` → a töltőből visszaolvasva (`CurrentDynamic`, `CurrentOffered`, …);
  `POST /api/admin/load-groups/{név}/rebalance` kézi újraosztás. A Töltők táblában
  „⚖ csoport · kiosztott/max A", hibánál piros `!`.
- Első éles ellenőrzés: két autóval egyszerre; `GET …/load-groups?live=1` → `CurrentOffered`
  16 mindkettőn; a naplóban `terheléselosztás: csoport=… cp=… 32→16 A`.
- Ha a Voltie a `CurrentDynamic`-ra `RebootRequired`-et vagy `Rejected`-et ad, próbáld a
  `LOAD_BALANCE_CONFIG_KEY=CurrentLimitUser` kulcsot (a `.env`-ben) — a napló és a
  `last_error` mutatja.
- A csoport áramát a **tényleges** betáplálás szerint add meg; ha ugyanazon a kismegszakítón más
  fogyasztó is van (világítás, épület), annyival kevesebbet.
