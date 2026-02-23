# app/ocpp/registry.py
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Tuple, Any, Optional

from fastapi import WebSocket

logger = logging.getLogger("ocpp")

# cp_id -> websocket
_ACTIVE_WS: Dict[str, WebSocket] = {}

# cp_id -> counter (uniqueId generálás)
_CP_MSG_COUNTER: Dict[str, int] = {}

# (cp_id, unique_id) -> future (CALLRESULT/CALLERROR várás)
_PENDING_CALLS: Dict[Tuple[str, str], asyncio.Future] = {}

_REGISTRY_LOCK = asyncio.Lock()


async def register_ws(cp_id: str, ws: WebSocket) -> None:
    async with _REGISTRY_LOCK:
        _ACTIVE_WS[cp_id] = ws


async def unregister_ws_if_same(cp_id: str, ws: WebSocket) -> None:
    async with _REGISTRY_LOCK:
        if _ACTIVE_WS.get(cp_id) is ws:
            _ACTIVE_WS.pop(cp_id, None)


async def get_ws(cp_id: str) -> Optional[WebSocket]:
    async with _REGISTRY_LOCK:
        return _ACTIVE_WS.get(cp_id)


async def _next_unique_id(cp_id: str) -> str:
    async with _REGISTRY_LOCK:
        cur = _CP_MSG_COUNTER.get(cp_id, 900_000_000)
        cur += 1
        _CP_MSG_COUNTER[cp_id] = cur
        return str(cur)


async def pending_set_future(cp_id: str, unique_id: str, fut: asyncio.Future) -> None:
    async with _REGISTRY_LOCK:
        _PENDING_CALLS[(cp_id, unique_id)] = fut


async def pending_pop(cp_id: str, unique_id: str) -> None:
    async with _REGISTRY_LOCK:
        _PENDING_CALLS.pop((cp_id, unique_id), None)


async def pending_get(cp_id: str, unique_id: str) -> Optional[asyncio.Future]:
    async with _REGISTRY_LOCK:
        return _PENDING_CALLS.get((cp_id, unique_id))


async def send_call_and_wait(cp_id: str, action: str, payload: dict, timeout_s: float = 12.0) -> dict:
    """
    OCPP CALL (2) küldése a töltőnek és CALLRESULT (3) / CALLERROR (4) megvárása.
    """
    ws = await get_ws(cp_id)
    if ws is None:
        raise RuntimeError(f"Nincs aktív WS kapcsolat ehhez a töltőhöz: {cp_id}")

    uid = await _next_unique_id(cp_id)
    frame = [2, uid, action, payload]

    fut = asyncio.get_running_loop().create_future()
    await pending_set_future(cp_id, uid, fut)

    try:
        await ws.send_text(json.dumps(frame))
        logger.info(f"CSMS->CP CALL elküldve: cp={cp_id} action={action} uid={uid}")

        res = await asyncio.wait_for(fut, timeout=timeout_s)
        return res if isinstance(res, dict) else {}
    finally:
        await pending_pop(cp_id, uid)


async def remote_start_transaction(cp_id: str, connector_id: int = 1, id_tag: str = "ANON") -> dict:
    """
    RemoteStartTransaction (OCPP 1.6): { connectorId?, idTag, chargingProfile? }
    """
    payload = {"connectorId": int(connector_id), "idTag": str(id_tag)}
    return await send_call_and_wait(cp_id, "RemoteStartTransaction", payload, timeout_s=12.0)


async def remote_stop_transaction(cp_id: str, transaction_id: Any) -> dict:
    """
    RemoteStopTransaction (OCPP 1.6): { transactionId }
    """
    if transaction_id is None:
        return {"status": "Rejected", "reason": "missing_transaction_id"}
    try:
        tx = int(transaction_id)
    except Exception:
        tx = transaction_id
    payload = {"transactionId": tx}
    return await send_call_and_wait(cp_id, "RemoteStopTransaction", payload, timeout_s=12.0)