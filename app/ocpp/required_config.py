# app/ocpp/required_config.py
"""
Kötelező töltő-beállítások – minden töltőre, automatikusan (2026-10-30, Gellért döntése).

- ConnectionTimeOut: a töltő ennyi mp-ig vár az autó bedugására egy engedélyezett indítás
  után – egyezik a függő munkamenet lejáratával (pending_start.WAITING_TIMEOUT_MINUTES).
- LocalAuthorizeOffline / AllowOfflineTxForUnknownId = false: nincs offline töltés – a töltő
  ne engedjen tölteni, amikor nincs kapcsolata a szerverrel.

Mikor: minden BootNotification után (ws.py) egyszer, ill. kézzel az adminból
(„Kötelező beállítások alkalmazása most”, egy töltőre vagy az összes csatlakozottra).
Menet: GetConfiguration → ami eltér, arra ChangeConfiguration → visszaolvasás. Az eredmény
naplózva és töltőnként a charge_points.required_config_state JSON-oszlopban (admin-kijelzés).
Elutasításnál nincs újrapróbálás: jelezzük, és legközelebb csak a következő bootnál vagy kézi
indításra próbáljuk újra. Újraindítást (RebootRequired) sem kérünk magunktól.

Ez a lista NEM bővíti az admin ChangeConfiguration-allowlistjét (admin.py) – csak ezt a
három, rögzített értéket küldjük ki.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import update

import app.db.session as db_session
from app.db.models import ChargePoint
from app.ocpp import registry
from app.ocpp.handlers.pending_start import WAITING_TIMEOUT_MINUTES
from app.ocpp.time_utils import utcnow

logger = logging.getLogger("ocpp")

REQUIRED_CONFIG: dict[str, str] = {
    "ConnectionTimeOut": str(WAITING_TIMEOUT_MINUTES * 60),
    "LocalAuthorizeOffline": "false",
    "AllowOfflineTxForUnknownId": "false",
}

# A ChangeConfiguration válaszai közül ezek nem elutasítások
_OK_STATUSES = {"ok", "Accepted", "RebootRequired"}

# Töltők, amelyeken épp fut az alkalmazás (két egyidejű trigger ne küldjön kétszer)
_IN_PROGRESS: set[str] = set()


def _same(value: Optional[str], want: str) -> bool:
    return value is not None and str(value).strip().lower() == want.lower()


async def _read(cp_id: str) -> tuple[dict, set]:
    """A kötelező kulcsok aktuális értéke a töltőből, és amit a töltő nem ismer."""
    res = await registry.send_call_and_wait(
        cp_id, "GetConfiguration", {"key": list(REQUIRED_CONFIG)}, timeout_s=15)
    values = {k.get("key"): k.get("value") for k in (res or {}).get("configurationKey", []) if isinstance(k, dict)}
    return values, set((res or {}).get("unknownKey") or [])


async def _apply(cp_id: str) -> dict:
    before, unknown = await _read(cp_id)
    keys: dict[str, dict] = {}
    for key, want in REQUIRED_CONFIG.items():
        old = before.get(key)
        if key in unknown:
            status = "NotSupported"
        elif _same(old, want):
            status = "ok"
        else:
            try:
                status = (await registry.change_configuration(cp_id, key, want) or {}).get("status", "Unknown")
            except Exception as e:
                status = f"Error: {e or type(e).__name__}"
        keys[key] = {"old": old, "want": want, "status": status}

    after = before
    if any(k["status"] not in ("ok", "NotSupported") for k in keys.values()):
        try:
            after = (await _read(cp_id))[0]
        except Exception as e:
            logger.warning(f"Kötelező beállítások: visszaolvasás sikertelen cp={cp_id} err={e}")
            after = {}
    for key, k in keys.items():
        k["new"] = after.get(key)

    if any(k["status"] not in _OK_STATUSES for k in keys.values()):
        summary = "rejected"
    elif all(_same(k["new"], k["want"]) for k in keys.values()):
        summary = "ok"
    else:
        summary = "differs"   # pl. RebootRequired: a töltő újraindítás után veszi át
    return {"summary": summary, "keys": keys}


async def apply_required_config(cp_id: str, reason: str) -> dict:
    """Kötelező beállítások ellenőrzése + kiküldése egy töltőre. Kivételt nem dob.
    Visszaad: {"summary": ok|differs|rejected|error|busy, "keys": {...}, "reason", "checked_at"}."""
    if cp_id in _IN_PROGRESS:
        return {"summary": "busy", "reason": reason}
    _IN_PROGRESS.add(cp_id)
    try:
        try:
            state = await _apply(cp_id)
        except Exception as e:
            state = {"summary": "error", "error": str(e) or type(e).__name__, "keys": {}}
        state.update(reason=reason, checked_at=utcnow().isoformat())

        for key, k in state["keys"].items():
            level = logging.INFO if k["status"] == "ok" or k["status"] == "Accepted" else logging.WARNING
            logger.log(level, f"Kötelező beállítás [{reason}]: cp={cp_id} {key} "
                              f"{k['old']} -> {k['want']} status={k['status']} visszaolvasva={k['new']}")
        logger.log(logging.INFO if state["summary"] == "ok" else logging.WARNING,
                   f"Kötelező beállítások [{reason}]: cp={cp_id} eredmény={state['summary']}"
                   + (f" hiba={state['error']}" if state.get("error") else ""))

        try:
            async with db_session.AsyncSessionLocal() as s:
                await s.execute(update(ChargePoint).where(ChargePoint.ocpp_id == cp_id)
                                .values(required_config_state=state))
                await s.commit()
        except Exception:
            logger.exception(f"Kötelező beállítások: mentés sikertelen cp={cp_id}")
        return state
    finally:
        _IN_PROGRESS.discard(cp_id)
