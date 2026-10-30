# app/ocpp/handlers/pending_start.py
"""
Kifizetett, de még el nem indult (függő) munkamenet RemoteStartTransaction-je.

Függő munkamenet: a Stripe-webhook létrehozta (intent = paid), de StartTransaction még
nem jött (ocpp_transaction_id IS NULL, finished_at IS NULL), és a lejárati ablakon belül
van (a main.py waiting-timeoutja WAITING_TIMEOUT_MINUTES után lezárja és feloldja a zárolást).

Mikor küldünk (újra) RemoteStartot – mind ugyanazon a függvényen át, egységes naplóval:
  - fizetés után (payments_stripe) – az első küldés, csak az időpontját jegyezzük;
  - a töltő újracsatlakozásakor (BootNotification) – a töltő elveszíthette az engedélyt;
  - a töltő a csatlakozón `Preparing`-et jelez – bedugták az autót / újrapróbálják, de a
    töltő ConnectionTimeOut-ja közben lejárt (2026-10-28, norg_onk_2: 60 mp után
    visszaváltott Available-re, a később bedugott autóhoz már nem volt engedély);
  - kézzel az adminból (POST /api/admin/sessions/{id}/remote-start).

Elsődleges megoldás: a töltő ConnectionTimeOut-ja a teljes függő ablak (kötelező beállítás,
app/ocpp/required_config.py). Az automatikus újraküldés tartalék arra az esetre, ha egy
töltő nem fogadja el a nagy értéket, vagy közben újraindul.

Védelmek az automatikus újraküldésre (a kézi küldésre nem):
  - munkamenetenként legfeljebb MAX_AUTO_RETRIES újraküldés;
  - két küldés között legalább MIN_GAP_S (a fizetés utáni első küldést is beleértve, így a
    RemoteStart után szokásos Preparing nem vált ki azonnali újraküldést).
A számlálók processz-memóriában vannak (a munkamenet úgyis legfeljebb WAITING_TIMEOUT_MINUTES-ig függő;
backend-újraindítás után a töltő újracsatlakozik, és a boot-ág újraküld).

Offline töltőre várás (2026-10-30, Gellért döntése: „várjuk meg, amíg a töltő visszajön”):
ha a töltő az engedély után elveszti a netet, a töltést helyben ettől még elindíthatja, a
StartTransaction-t pedig csak visszacsatlakozáskor küldi el. Ezért ha az ablak úgy jár le, hogy
a töltő offline, a main.py lejárati köre nem zár, hanem `offline_wait_since`-t állít, és:
  - visszajön + megérkezik a sorba állított StartTransaction (időbélyege az ablakon belül,
    ugyanarra a csatlakozóra) → transactions.start_transaction hozzáköti, a többi a szokásos;
  - visszajön, de RECONNECT_GRACE_S alatt nem jön StartTransaction → lezárás + feloldás;
  - OFFLINE_WAIT_MAX_HOURS a fizetéstől → lezárás + feloldás.
Offline-ra váró munkamenetre RemoteStart nem megy (ablakon túl van: _not_pending_reason).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

import app.db.session as db_session
from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.ocpp import registry
from app.ocpp.time_utils import utcnow

logger = logging.getLogger("ocpp")

# Függő munkamenet lejárata a sikeres fizetéstől (a session a webhookban, a fizetéskor jön
# létre; started_at = akkor): ennyi perc után a main.py waiting-timeoutja lezárja és feloldja
# a Stripe-zárolást. Közös forrás: main.py, és a töltő kötelező ConnectionTimeOut-ja
# (required_config.py) is ebből jön (5 perc = 300 mp).
WAITING_TIMEOUT_MINUTES = 5

# Offline töltőre várás felső határa a fizetéstől. A Stripe manual-capture zárolás 7 napig
# érvényes, a 24 óra ezen belül van: a capture a várakozás végén is sikerül.
OFFLINE_WAIT_MAX_HOURS = 24
# Visszacsatlakozás után ennyi ideig várunk a sorba állított StartTransaction-re.
RECONNECT_GRACE_S = 120
# A töltő órájának eltérése, amit a StartTransaction időbélyegénél még elfogadunk.
OFFLINE_START_SKEW_S = 60

MAX_AUTO_RETRIES = 3       # automatikus újraküldés munkamenetenként
MIN_GAP_S = 20.0           # legalább ennyi mp két küldés között
_RECONNECT_DELAY_S = 2.0   # boot után ennyi idő a töltőnek, hogy stabilizálódjon
_SESSION_MAX_AGE_MIN = WAITING_TIMEOUT_MINUTES - 1  # a waiting timeout előtt 1 perccel adjuk fel
_STATE_TTL_S = 3600.0      # ennél régebbi számlálókat eldobjuk


@dataclass
class _Attempts:
    retries: int = 0       # automatikus újraküldések száma
    last_sent: float = 0.0  # utolsó küldés (monotonic)


# session_id → küldési állapot
_ATTEMPTS: dict[int, _Attempts] = {}


def _clock() -> float:
    return time.monotonic()


def reset_state() -> None:
    """Tesztekhez: számlálók törlése."""
    _ATTEMPTS.clear()


def _state(session_id: int) -> _Attempts:
    now = _clock()
    for sid in [k for k, v in _ATTEMPTS.items() if now - v.last_sent > _STATE_TTL_S]:
        _ATTEMPTS.pop(sid, None)
    return _ATTEMPTS.setdefault(session_id, _Attempts())


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def offline_wait_deadline(cs: ChargeSession):
    """Offline töltőre váró munkamenet végső határa (a fizetéstől OFFLINE_WAIT_MAX_HOURS).
    A függő munkamenet started_at-ja a fizetés ideje (a StartTransaction írja át)."""
    return _aware(cs.started_at) + timedelta(hours=OFFLINE_WAIT_MAX_HOURS)


def is_offline_waiting(cs: ChargeSession) -> bool:
    """Offline töltőre vár: lejárt az ablak a töltő offline állapotában, és még nem dőlt el."""
    return cs.offline_wait_since is not None and cs.finished_at is None and cs.ocpp_transaction_id is None


def offline_wait_info(cs: ChargeSession) -> dict:
    """API-mezők (ügyfél-oldal, admin): offline-ra vár-e, és legkésőbb meddig tartjuk a zárolást."""
    waiting = is_offline_waiting(cs)
    return {"offline_wait": waiting,
            "offline_wait_until": offline_wait_deadline(cs).isoformat() if waiting else None}


def offline_start_in_window(cs: ChargeSession, ts) -> bool:
    """Köthető-e egy (sorba állított) StartTransaction az offline-ra váró munkamenethez:
    az időbélyege a fizetés és az ablak vége közé esik (kis óraeltéréssel). Egy később, helyben
    indított tranzakció valaki másé lehet – azt nem számlázhatjuk az ügyfélnek."""
    paid_at = _aware(cs.started_at)
    skew = timedelta(seconds=OFFLINE_START_SKEW_S)
    return paid_at - skew <= _aware(ts) <= paid_at + timedelta(minutes=WAITING_TIMEOUT_MINUTES) + skew


async def charger_offline(cp: ChargePoint) -> bool:
    """Offline a töltő: nincs WS-kapcsolata a registryben, vagy a compute_status szerint offline."""
    from app.api.routers.charge_points import compute_status
    return await registry.get_ws(cp.ocpp_id) is None or compute_status(cp) == "offline"


def _not_pending_reason(cs: Optional[ChargeSession]) -> Optional[str]:
    """None, ha a munkamenet függő és kifizetett; különben a kihagyás oka."""
    if cs is None:
        return "not_found"
    if cs.finished_at is not None:
        return "finished"
    if cs.ocpp_transaction_id is not None:
        return "already_started"
    if cs.intent is None or cs.intent.status != "paid":
        return "not_paid"
    if cs.offline_wait_since is not None:
        return "offline_wait"  # az ablakon túl: RemoteStart már nem megy, a töltő jelentkezését várjuk
    if _aware(cs.started_at) < utcnow() - timedelta(minutes=_SESSION_MAX_AGE_MIN):
        return "expired"
    return None


async def send_remote_start(
    cp_ocpp_id: str, session_id: int, intent_id: Optional[int], connector_id: int, reason: str,
) -> dict:
    """RemoteStartTransaction egy függő munkamenetre – naplózva, kivételt nem dob.
    Visszaadja a töltő válaszát (hibánál {"status": "Error", "reason": ...})."""
    st = _state(session_id)
    st.last_sent = _clock()
    try:
        res = await registry.remote_start_transaction(
            cp_id=cp_ocpp_id, connector_id=int(connector_id or 1), id_tag="ANON",
        )
    except Exception as e:
        res = {"status": "Error", "reason": str(e) or type(e).__name__}
    level = logging.INFO if (res or {}).get("status") == "Accepted" else logging.WARNING
    logger.log(
        level,
        f"RemoteStart [{reason}]: cp={cp_ocpp_id} connector={connector_id} intent={intent_id} "
        f"session={session_id} újrapróbálás={st.retries}/{MAX_AUTO_RETRIES} → {res}",
    )
    return res


async def retry_remote_start(session_id: int, reason: str, manual: bool = False) -> dict:
    """RemoteStart újraküldése egy függő, kifizetett munkamenetre.

    Visszaad: {"sent": bool, "skipped": ok|None, "ocpp": töltő-válasz|None, ...}.
    Automatikus hívásnál (manual=False) a MAX_AUTO_RETRIES / MIN_GAP_S korlát érvényes.
    """
    async with db_session.AsyncSessionLocal() as db:
        cs = (await db.execute(
            select(ChargeSession)
            .options(selectinload(ChargeSession.intent), selectinload(ChargeSession.charge_point))
            .where(ChargeSession.id == session_id)
        )).scalar_one_or_none()

    out = {"sent": False, "skipped": None, "ocpp": None, "session_id": session_id,
           "intent_id": cs.intent_id if cs else None,
           "cp": cs.charge_point.ocpp_id if cs and cs.charge_point else None}

    skip = _not_pending_reason(cs)
    if skip is None and not manual:
        # A korlát-ellenőrzés és a küldés-jelölés között nincs await → két egyidejű
        # trigger (pl. boot + Preparing) közül csak az egyik küld.
        st = _state(session_id)
        if st.retries >= MAX_AUTO_RETRIES:
            skip = "max_retries"
        elif _clock() - st.last_sent < MIN_GAP_S:
            skip = "too_soon"
        else:
            st.retries += 1
    if skip is not None:
        out["skipped"] = skip
        logger.info(f"RemoteStart [{reason}] kihagyva: cp={out['cp']} intent={out['intent_id']} "
                    f"session={session_id} ok={skip}")
        return out

    out["ocpp"] = await send_remote_start(
        out["cp"], cs.id, cs.intent_id, cs.connector_id or 1, reason)
    out["sent"] = True
    return out


async def _pending_session_id(cp_ocpp_id: str, connector_id: Optional[int] = None) -> Optional[int]:
    """A töltő (adott csatlakozójának) legfrissebb függő, kifizetett munkamenete."""
    cutoff = utcnow() - timedelta(minutes=_SESSION_MAX_AGE_MIN)
    conds = [
        ChargePoint.ocpp_id == cp_ocpp_id,
        ChargeSession.finished_at.is_(None),
        ChargeSession.ocpp_transaction_id.is_(None),
        ChargeSession.started_at > cutoff,
        ChargingIntent.status == "paid",
    ]
    if connector_id is not None:
        conds.append(ChargeSession.connector_id == connector_id)
    async with db_session.AsyncSessionLocal() as db:
        return (await db.execute(
            select(ChargeSession.id)
            .join(ChargePoint, ChargeSession.charge_point_id == ChargePoint.id)
            .join(ChargingIntent, ChargeSession.intent_id == ChargingIntent.id)
            .where(and_(*conds))
            .order_by(ChargeSession.started_at.desc())
            .limit(1)
        )).scalar_one_or_none()


async def retry_pending_remote_start(cp_id: str) -> None:
    """BootNotification után: ha a töltőn van függő munkamenet, újraküldjük a RemoteStartot."""
    await asyncio.sleep(_RECONNECT_DELAY_S)
    try:
        sid = await _pending_session_id(cp_id)
        if sid is None:
            logger.debug(f"Reconnect: nincs függő munkamenet, cp={cp_id}")
            return
        await retry_remote_start(sid, reason="reconnect")
    except Exception as e:
        logger.exception(f"retry_pending_remote_start hiba: cp={cp_id} err={e}")


async def retry_on_preparing(cp_id: str, connector_id: Optional[int]) -> None:
    """StatusNotification(Preparing) után: függő munkamenet esetén RemoteStart újra."""
    if not connector_id:
        return  # connector 0 = állomás-szintű állapot, nem a bedugott csatlakozó
    try:
        sid = await _pending_session_id(cp_id, connector_id)
        if sid is None:
            return
        await retry_remote_start(sid, reason="preparing")
    except Exception as e:
        logger.exception(f"retry_on_preparing hiba: cp={cp_id} connector={connector_id} err={e}")
