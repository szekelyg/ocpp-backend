# app/services/load_balance.py
"""
Statikus terheléselosztás egy közös betáplálásra kötött töltők között (2026-09-23).

Példa: a nógrádi várnál két 22 kW-os töltő van, de a betáplálás összesen 3×32 A. Alapból
mindkettő 32 A-t (22 kW) kaphat; ha mindkettő tölt, 16–16 A-re (11 kW) kell fogni őket.

Hogyan: a Voltie töltők NEM tudják az OCPP SmartCharging-profilt (SupportedFeatureProfiles:
Core, LocalAuthListManagement, RemoteTrigger), viszont van saját, írható konfigurációs
kulcsuk az élő áramkorlátra (`CurrentDynamic`, amper, 3 fázisra értve). Ezt írjuk
ChangeConfiguration-nel (LOAD_BALANCE_CONFIG_KEY env, alap `CurrentDynamic`).

Adatmodell (charge_points): `load_group` (csoport neve), `load_group_max_a` (a csoport
összes árama fázisonként; a tagoknál megadott értékek közül a legkisebb nem-üres érvényes),
`max_current_a` (a töltő saját maximuma, alap 32).

Kiosztás egy csoportban (fázisonkénti amper):
  - aktív töltő = nyitott session (finished_at IS NULL) ÉS elindult tranzakció
    (ocpp_transaction_id IS NOT NULL). Az offline, de nyitott sessionű töltőt is aktívnak
    vesszük (konzervatív: nem tudjuk, hogy nem tölt-e).
  - nincs aktív → mindenki a saját maximumát kapja (alapból 22 kW).
  - n aktív → aktívak: min(saját max, max(MIN_A, csoport_max // n)); a tétlenek a maradékot
    (csoport_max − aktívak összege), de legalább MIN_A-t, legfeljebb a saját maxot —
    így a második autó legfeljebb rövid ideig lóg túl (32 + 6 A), majd StartTransaction-ra
    16–16 A lesz.
  - a MIN_A (6 A, az IEC 61851 minimuma) alá nem megyünk; ha a csoport ennyire sem elég,
    figyelmeztetünk.

Mikor: StartTransaction / StopTransaction / BootNotification után (ws.py), admin-beállítás
után, és percenként ellenőrző körben (main.py). Csak akkor küldünk, ha az érték eltér az
utoljára kiküldöttől (processz-memória; boot/újraindítás után újra kiküldjük).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger("loadbalance")

MIN_A = 6
DEFAULT_MAX_A = 32


def config_key() -> str:
    return (os.environ.get("LOAD_BALANCE_CONFIG_KEY") or "CurrentDynamic").strip() or "CurrentDynamic"


@dataclass
class MemberState:
    ocpp_id: str
    cap_a: int
    active: bool
    online: bool
    target_a: int
    applied_a: Optional[int] = None      # utoljára sikeresen kiküldött érték
    applied_at: Optional[float] = None   # time.time()
    last_error: Optional[str] = None


# ocpp_id → MemberState (a legutóbbi kiosztás eredménye; admin-kijelzéshez és a „csak ha
# változott" küldéshez)
_STATE: dict[str, MemberState] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _lock(group: str) -> asyncio.Lock:
    lk = _LOCKS.get(group)
    if lk is None:
        lk = _LOCKS[group] = asyncio.Lock()
    return lk


def reset_state() -> None:
    """Tesztekhez."""
    _STATE.clear()
    _LOCKS.clear()
    _GROUP_OF.clear()


def snapshot() -> dict[str, dict]:
    """Admin-kijelzés: ocpp_id → {target_a, applied_a, applied_at, active, online, last_error}."""
    return {
        k: {
            "cap_a": v.cap_a, "target_a": v.target_a, "applied_a": v.applied_a,
            "applied_at": v.applied_at, "active": v.active, "online": v.online,
            "last_error": v.last_error,
        }
        for k, v in _STATE.items()
    }


# ---------------------------------------------------------------------------
# Tiszta kiosztás (tesztelhető, DB nélkül)
# ---------------------------------------------------------------------------

def allocate(group_max_a: int, members: list[tuple[str, int, bool]]) -> dict[str, int]:
    """members: [(ocpp_id, cap_a, active)] → {ocpp_id: amper}."""
    caps = {m[0]: max(MIN_A, int(m[1] or DEFAULT_MAX_A)) for m in members}
    active = [m[0] for m in members if m[2]]
    out: dict[str, int] = {}
    if not active:
        for oid in caps:
            out[oid] = caps[oid]
        return out
    share = group_max_a // len(active)
    if share < MIN_A:
        logger.warning("terheléselosztás: a csoport (%s A) %s aktív töltőre nem elég (min %s A/töltő) – %s A-t adunk",
                       group_max_a, len(active), MIN_A, MIN_A)
    for oid in active:
        out[oid] = min(caps[oid], max(MIN_A, share))
    used = sum(out[oid] for oid in active)
    remaining = max(MIN_A, group_max_a - used)
    for oid in caps:
        if oid not in out:
            out[oid] = min(caps[oid], remaining)
    return out


# ---------------------------------------------------------------------------
# DB + OCPP
# ---------------------------------------------------------------------------

async def _group_of(ocpp_id: str) -> Optional[str]:
    from app.db.models import ChargePoint
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            select(ChargePoint.load_group).where(ChargePoint.ocpp_id == ocpp_id)
        )).first()
    g = row[0] if row else None
    return g.strip() if isinstance(g, str) and g.strip() else None


async def _load_members(group: str) -> tuple[Optional[int], list[tuple[str, int, bool]]]:
    """(csoport_max_a, [(ocpp_id, cap_a, active)])."""
    from app.db.models import ChargePoint, ChargeSession
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        cps = (await s.execute(
            select(ChargePoint).where(ChargePoint.load_group == group).order_by(ChargePoint.id)
        )).scalars().all()
        if not cps:
            return None, []
        ids = [cp.id for cp in cps]
        active_ids = set(
            r[0] for r in (await s.execute(
                select(ChargeSession.charge_point_id).where(
                    ChargeSession.charge_point_id.in_(ids),
                    ChargeSession.finished_at.is_(None),
                    ChargeSession.ocpp_transaction_id.isnot(None),
                )
            )).all()
        )
        limits = [int(cp.load_group_max_a) for cp in cps if cp.load_group_max_a]
        group_max = min(limits) if limits else None
        members = [(cp.ocpp_id, int(cp.max_current_a or DEFAULT_MAX_A), cp.id in active_ids) for cp in cps]
        for cp in cps:
            _GROUP_OF[cp.ocpp_id] = group
        return group_max, members


async def _apply(ocpp_id: str, amps: int) -> tuple[bool, Optional[str]]:
    """ChangeConfiguration a töltőnek. (siker, hiba-szöveg)."""
    from app.ocpp.registry import change_configuration

    try:
        res = await change_configuration(ocpp_id, config_key(), str(amps))
    except Exception as e:
        return False, str(e)
    status = (res or {}).get("status")
    if status in ("Accepted", "RebootRequired"):
        if status == "RebootRequired":
            logger.warning("terheléselosztás: %s=%s A elfogadva, de a töltő újraindítást kér: cp=%s", config_key(), amps, ocpp_id)
        return True, None
    return False, f"status={status} {res}"


async def rebalance_group(group: str, reason: str = "") -> dict[str, int]:
    """Egy csoport újraosztása és kiküldése. Visszaad: {ocpp_id: cél-amper}."""
    from app.ocpp.registry import get_ws

    async with _lock(group):
        group_max, members = await _load_members(group)
        if not members:
            return {}
        if not group_max:
            logger.warning("terheléselosztás: a(z) '%s' csoportnak nincs load_group_max_a értéke – kihagyva", group)
            return {}
        targets = allocate(group_max, members)
        n_active = sum(1 for m in members if m[2])
        todo: list[MemberState] = []
        for ocpp_id, cap, active in members:
            target = targets[ocpp_id]
            online = (await get_ws(ocpp_id)) is not None
            st = _STATE.get(ocpp_id)
            if st is None:
                st = _STATE[ocpp_id] = MemberState(ocpp_id=ocpp_id, cap_a=cap, active=active, online=online, target_a=target)
            st.cap_a, st.active, st.online, st.target_a = cap, active, online, target
            if not online:
                # offline: a következő boot után újra kiosztunk (applied_a nullázva)
                st.applied_a = None
                continue
            if st.applied_a != target:
                todo.append(st)

        # A betáplálás védelme: ELŐBB minden csökkentés, és csak ha mind sikerült, jönnek a
        # növelések. (Ismeretlen előző értéknél – applied_a None, pl. boot után – a küldést
        # csökkentésnek vesszük: az is előbb menjen ki.)
        decreases = [st for st in todo if st.applied_a is None or st.target_a < st.applied_a]
        increases = [st for st in todo if st not in decreases]
        dec_failed = False
        for st in decreases + increases:
            if st in increases and dec_failed:
                logger.warning("terheléselosztás: csoport=%s cp=%s növelés (%s A) ELHALASZTVA, mert egy csökkentés nem sikerült",
                               group, st.ocpp_id, st.target_a)
                continue
            ok, err = await _apply(st.ocpp_id, st.target_a)
            if ok:
                logger.info("terheléselosztás: csoport=%s cp=%s %s→%s A (aktív=%s/%s, ok: %s)",
                            group, st.ocpp_id, st.applied_a, st.target_a, n_active, len(members), reason or "-")
                st.applied_a, st.applied_at, st.last_error = st.target_a, time.time(), None
            else:
                logger.warning("terheléselosztás: csoport=%s cp=%s %s A kiküldése SIKERTELEN: %s", group, st.ocpp_id, st.target_a, err)
                st.applied_a, st.last_error = None, err
                if st in decreases:
                    dec_failed = True
        return targets


async def rebalance_for_cp(ocpp_id: str, reason: str = "") -> None:
    """Hook: StartTransaction / StopTransaction / Boot után. Csoport nélküli töltőnél nincs teendő."""
    try:
        group = await _group_of(ocpp_id)
        if group:
            await rebalance_group(group, reason=f"{reason} {ocpp_id}".strip())
    except Exception:
        logger.exception("terheléselosztás hiba cp=%s", ocpp_id)


async def rebalance_all(reason: str = "") -> None:
    from app.db.models import ChargePoint
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as s:
            groups = [g for (g,) in (await s.execute(
                select(ChargePoint.load_group).where(ChargePoint.load_group.isnot(None)).distinct()
            )).all() if isinstance(g, str) and g.strip()]
        for g in groups:
            await rebalance_group(g.strip(), reason=reason)
    except Exception:
        logger.exception("terheléselosztás hiba (all)")


# ---------------------------------------------------------------------------
# Ügyfél-tájékoztatás (publikus API-hoz): amper → kW, aktuális korlát, csoport-adatok
# ---------------------------------------------------------------------------

PHASE_VOLTAGE = 230


def kw_for_amps(amps: int, phases: int = 3) -> int:
    """3 fázisú AC: P ≈ 3 × 230 V × I. 32 A → 22 kW, 16 A → 11 kW, 10 A → 7 kW, 6 A → 4 kW."""
    return int(round(phases * PHASE_VOLTAGE * int(amps) / 1000.0))


def limit_info(ocpp_id: str) -> Optional[dict]:
    """Az adott töltő mostani korlátja a legutóbbi kiosztásból (memória; None, ha nincs csoportban
    vagy még nem futott kiosztás). shared_now: a csoport másik tagja is tölt éppen."""
    st = _STATE.get(ocpp_id)
    if st is None:
        return None
    limit = st.applied_a if st.applied_a is not None else st.target_a
    return {
        "limit_a": limit,
        "limit_kw": kw_for_amps(limit),
        "cap_kw": kw_for_amps(st.cap_a),
        "shared_now": any(o.active for k, o in _STATE.items() if k != ocpp_id and _same_group(k, ocpp_id)),
    }


# ocpp_id → csoportnév (a legutóbbi _load_members töltötte)
_GROUP_OF: dict[str, str] = {}


def _same_group(a: str, b: str) -> bool:
    return _GROUP_OF.get(a) is not None and _GROUP_OF.get(a) == _GROUP_OF.get(b)


async def public_sharing_info(cps) -> dict[int, dict]:
    """Publikus töltő-listához: cp.id → {"members", "group_max_kw", "shared_kw", "current_limit_kw"}
    a csoportban lévő töltőkre (a többire nincs kulcs). Egy lekérdezés a csoport-tagságokhoz."""
    from app.db.models import ChargePoint
    from app.db.session import AsyncSessionLocal

    groups = {cp.load_group for cp in cps if getattr(cp, "load_group", None)}
    if not groups:
        return {}
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(ChargePoint.id, ChargePoint.ocpp_id, ChargePoint.load_group, ChargePoint.load_group_max_a, ChargePoint.max_current_a)
            .where(ChargePoint.load_group.in_(groups))
        )).all()
    by_group: dict[str, list] = {}
    for r in rows:
        by_group.setdefault(r[2], []).append(r)
        _GROUP_OF[r[1]] = r[2]
    out: dict[int, dict] = {}
    for g, members in by_group.items():
        limits = [int(m[3]) for m in members if m[3]]
        if not limits:
            continue
        gmax = min(limits)
        n = len(members)
        for m in members:
            cap = int(m[4] or DEFAULT_MAX_A)
            li = limit_info(m[1])
            out[m[0]] = {
                "group": g,
                "members": n,
                "group_max_kw": kw_for_amps(min(gmax, cap)),
                "shared_kw": kw_for_amps(min(cap, max(MIN_A, gmax // max(1, n)))),
                "current_limit_kw": li["limit_kw"] if li else None,
                "shared_now": bool(li and li["shared_now"]),
            }
    return out
