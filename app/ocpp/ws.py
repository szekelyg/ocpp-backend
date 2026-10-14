# app/ocpp/ws.py
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.ocpp.parsers import extract_cp_id_from_boot
from app.ocpp.time_utils import iso_utc_now_z
from app.ocpp.registry import (
    admit_ws,
    register_ws,
    unregister_ws_if_same,
    pending_get,
    change_configuration,
)
from app.ocpp import auth as ocpp_auth
from app.ocpp.handlers.boot import upsert_charge_point_from_boot
from app.ocpp.handlers.heartbeat import touch_last_seen
from app.ocpp.handlers.status import save_status_notification
from app.ocpp.handlers.transactions import start_transaction, stop_transaction
from app.ocpp.handlers.meter import save_meter_values
from app.ocpp.handlers.reconnect import retry_pending_remote_start
from app.services.load_balance import rebalance_for_cp

logger = logging.getLogger("ocpp")


async def _lookup_cp_auth(cp_id: str) -> tuple[bool, Optional[str], bool]:
    """(ismert-e a töltő, tárolt kulcs-hash, publikált-e)."""
    from sqlalchemy import select
    import app.db.session as db_session
    from app.db.models import ChargePoint

    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(ChargePoint.id, ChargePoint.ocpp_auth_key_hash, ChargePoint.is_published)
            .where(ChargePoint.ocpp_id == cp_id)
        )).first()
    if row is None:
        return False, None, False
    return True, row[1], bool(row[2])


async def _record_auth(cp_id: str, result: Optional[str], scheme: str) -> None:
    """Töltőnként az utolsó kapcsolódás hitelesítési eredménye + séma (admin felület, audit)."""
    from sqlalchemy import update
    import app.db.session as db_session
    from app.db.models import ChargePoint
    from app.ocpp.time_utils import utcnow

    values = {"ocpp_last_scheme": scheme}
    if result is not None:
        values.update(ocpp_auth_last_result=result, ocpp_auth_last_at=utcnow())
    try:
        async with db_session.AsyncSessionLocal() as s:
            await s.execute(update(ChargePoint).where(ChargePoint.ocpp_id == cp_id).values(**values))
            await s.commit()
    except Exception:
        logger.exception(f"OCPP auth-eredmény mentése sikertelen cp={cp_id}")


async def _deny(ws: WebSocket, status_code: int, reason: str) -> None:
    """Kézfogás elutasítása accept előtt: HTTP 401/403 (ha a szerver támogatja), különben 1008."""
    from starlette.responses import PlainTextResponse

    headers = {"WWW-Authenticate": 'Basic realm="OCPP"'} if status_code == 401 else None
    try:
        await ws.send_denial_response(PlainTextResponse(reason, status_code=status_code, headers=headers))
    except Exception:
        await ws.close(code=1008)


async def _close_replaced(old: WebSocket, cp_id: str) -> None:
    try:
        await old.close(code=4000, reason="replaced by a new connection")
    except Exception:
        pass
    logger.warning(f"OCPP: cp={cp_id} új kapcsolat érkezett, a régit lezártuk")


async def _admit(ws: WebSocket, cp_id: Optional[str]) -> Optional[bool]:
    """Hitelesítés + duplikált kapcsolat szabály. None = elutasítva (a választ már elküldtük),
    különben: hitelesített-e a kapcsolat."""
    mode = ocpp_auth.auth_mode()
    scheme = ocpp_auth.transport_scheme(ws.headers, ws.url.scheme)

    if mode == "off":
        if cp_id:
            await _record_auth(cp_id, None, scheme)
        return False

    known, key_hash, published = (False, None, True)
    if cp_id:
        try:
            known, key_hash, published = await _lookup_cp_auth(cp_id)
        except Exception:
            logger.exception(f"OCPP auth: töltő-lekérdezés sikertelen cp={cp_id}")
            if mode == "enforce":
                await _deny(ws, 503, "auth lookup failed")
                return None
            # log módban egy DB-hiba miatt nem zárjuk ki a töltőt
    if key_hash:
        # PBKDF2 – ne blokkolja az event loopot
        dec = await asyncio.to_thread(
            ocpp_auth.evaluate, cp_id=cp_id, cp_known=known, key_hash=key_hash,
            authorization=ws.headers.get("authorization"), scheme=scheme, mode=mode,
            cp_published=published,
        )
    else:
        dec = ocpp_auth.evaluate(cp_id=cp_id, cp_known=known, key_hash=None,
                                 authorization=ws.headers.get("authorization"), scheme=scheme, mode=mode,
                                 cp_published=published)

    if dec.result == "ok":
        logger.info(f"OCPP auth OK: cp={cp_id} scheme={scheme}")
    elif dec.result == "unknown_cp":
        logger.warning(f"OCPP auth: ismeretlen töltő cp={cp_id!r} scheme={scheme} mode={mode}")
    else:
        level = logging.WARNING if dec.result in ("missing", "wrong") or not dec.accept else logging.INFO
        logger.log(level, f"OCPP auth {dec.result}: cp={cp_id} scheme={scheme} mode={mode}"
                          f"{'' if dec.accept else ' → ELUTASÍTVA'}")
    if scheme != "wss":
        logger.warning(f"OCPP: cp={cp_id} TITKOSÍTATLAN ws:// kapcsolat (nem wss)")

    if cp_id and known:
        await _record_auth(cp_id, dec.result, scheme)

    if not dec.accept:
        await _deny(ws, dec.http_status or 403, dec.reason or "rejected")
        return None
    return dec.authenticated


async def handle_ocpp(ws: WebSocket, charge_point_id: Optional[str] = None):
    cp_id: Optional[str] = charge_point_id

    authenticated = await _admit(ws, cp_id)
    if authenticated is None:
        return

    if cp_id:
        ok, old = await admit_ws(cp_id, ws, authenticated)
        if not ok:
            logger.warning(
                f"OCPP: cp={cp_id} második, NEM hitelesített kapcsolat elutasítva "
                f"(a meglévő kapcsolat hitelesített)"
            )
            await _deny(ws, 409, "charge point already connected")
            return
        await ws.accept()
        if old is not None:
            asyncio.create_task(_close_replaced(old, cp_id))
    else:
        await ws.accept()
    logger.info("OCPP kapcsolat nyitva")
    registered = bool(cp_id)

    try:
        while True:
            raw = await ws.receive_text()
            logger.debug(f"OCPP RAW: {raw}")

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Nem JSON, ignorálom")
                continue

            if not isinstance(msg, list) or len(msg) < 2:
                logger.warning("Nem OCPP frame, ignorálom")
                continue

            msg_type = msg[0]
            unique_id = str(msg[1])

            # ----------------------------------------------------------------------
            # CALLRESULT (3) / CALLERROR (4) - pending remote CALL-ok miatt
            # ----------------------------------------------------------------------
            if msg_type in (3, 4):
                if not cp_id:
                    continue

                fut = await pending_get(cp_id, unique_id)
                if fut and not fut.done():
                    if msg_type == 3:
                        payload = msg[2] if (len(msg) > 2 and isinstance(msg[2], dict)) else {}
                        fut.set_result(payload)
                    else:
                        err = {
                            "status": "Error",
                            "errorCode": msg[2] if len(msg) > 2 else "Unknown",
                            "errorDescription": msg[3] if len(msg) > 3 else "",
                            "errorDetails": msg[4] if len(msg) > 4 else {},
                        }
                        fut.set_result(err)
                continue

            # ----------------------------------------------------------------------
            # csak CALL (2)
            # ----------------------------------------------------------------------
            if msg_type != 2 or len(msg) < 3:
                logger.info(f"Nem CALL üzenet (type={msg_type}), ignorálom")
                continue

            action = msg[2]
            payload = msg[3] if (len(msg) > 3 and isinstance(msg[3], dict)) else {}

            # Bootból id kinyerés (ha /ocpp route)
            if action == "BootNotification" and cp_id is None:
                cp_id = extract_cp_id_from_boot(payload)
                if cp_id:
                    logger.info(f"ChargePoint ID kinyerve BootNotificationből: {cp_id}")
                    await register_ws(cp_id, ws)
                    registered = True
                else:
                    logger.warning("Nem tudtam ChargePoint ID-t kinyerni BootNotificationből")

            if not cp_id:
                # nincs cp_id, de ACK-oljunk safe defaulttal
                await ws.send_text(json.dumps([3, unique_id, {}]))
                continue

            # registry: a kapcsolat egyszer regisztrál (kapcsolódáskor, ill. /ocpp úton a
            # BootNotificationnél). Üzenetenként NEM írjuk újra – különben egy lecserélt (régi)
            # kapcsolat egy késve feldolgozott üzenettel visszavenné a helyét.
            if not registered:
                await register_ws(cp_id, ws)
                registered = True

            # ----------------------------------------------------------------------
            # ACTION DISPATCH
            # ----------------------------------------------------------------------
            if action == "BootNotification":
                await upsert_charge_point_from_boot(cp_id, payload)
                response = [3, unique_id, {"status": "Accepted", "currentTime": iso_utc_now_z(), "interval": 60}]
                await ws.send_text(json.dumps(response))
                # Reconnect után megnézzük van-e pending session (nem blokkol)
                asyncio.create_task(retry_pending_remote_start(cp_id))
                # MeterValues intervallum csökkentése 15 mp-re (alapból ~60s)
                asyncio.create_task(_set_meter_interval(cp_id, 15))
                # Egyedi megjelenítési szöveg beállítása (ha van OCPP_DISPLAY_TEXT env)
                asyncio.create_task(_set_display_text(cp_id))
                # Terheléselosztás: boot után az áramkorlát újra kiosztva (a töltő oldalán elveszhetett)
                asyncio.create_task(rebalance_for_cp(cp_id, "boot"))

            elif action == "Authorize":
                id_tag = payload.get("idTag", "")
                logger.info(f"Authorize: cp={cp_id} idTag={id_tag} → Accepted")
                response = [3, unique_id, {"idTagInfo": {"status": "Accepted"}}]
                await ws.send_text(json.dumps(response))

            elif action == "Heartbeat":
                await touch_last_seen(cp_id)
                response = [3, unique_id, {"currentTime": iso_utc_now_z()}]
                await ws.send_text(json.dumps(response))

            elif action == "StatusNotification":
                await save_status_notification(cp_id, payload)
                response = [3, unique_id, {}]
                await ws.send_text(json.dumps(response))

            elif action == "FirmwareStatusNotification":
                await touch_last_seen(cp_id)
                response = [3, unique_id, {}]
                await ws.send_text(json.dumps(response))

            elif action == "StartTransaction":
                tx_id = await start_transaction(cp_id, payload)
                response = [3, unique_id, {"transactionId": int(tx_id or 0), "idTagInfo": {"status": "Accepted"}}]
                await ws.send_text(json.dumps(response))
                asyncio.create_task(rebalance_for_cp(cp_id, "start"))

            elif action == "StopTransaction":
                await stop_transaction(cp_id, payload)
                response = [3, unique_id, {"idTagInfo": {"status": "Accepted"}}]
                await ws.send_text(json.dumps(response))
                asyncio.create_task(rebalance_for_cp(cp_id, "stop"))

            elif action == "MeterValues":
                await save_meter_values(cp_id, payload)
                response = [3, unique_id, {}]
                await ws.send_text(json.dumps(response))

            else:
                logger.info(f"Nem kezelt OCPP üzenet: {action} (ACK safe default)")
                response = [3, unique_id, {}]
                await ws.send_text(json.dumps(response))

    except WebSocketDisconnect:
        logger.info("OCPP kapcsolat lezárva (WebSocketDisconnect)")
    except Exception as e:
        logger.exception(f"OCPP hiba: {e}")
    finally:
        if cp_id:
            await unregister_ws_if_same(cp_id, ws)
        logger.info(f"OCPP cleanup kész (cp_id={cp_id})")


async def _set_display_text(cp_id: str) -> None:
    """DisplayCustomRfidText beállítása env változóból."""
    import os
    text = os.environ.get("OCPP_DISPLAY_TEXT", "").strip()
    if not text:
        return
    try:
        res = await change_configuration(cp_id, "DisplayCustomRfidText", text)
        status = (res or {}).get("status", "Unknown")
        if status == "Accepted":
            logger.info(f"DisplayCustomRfidText beállítva: cp={cp_id}")
        else:
            logger.warning(f"DisplayCustomRfidText visszautasítva: cp={cp_id} status={status}")
    except Exception as e:
        logger.warning(f"DisplayCustomRfidText beállítás sikertelen: cp={cp_id} err={e}")


async def _set_meter_interval(cp_id: str, interval_s: int) -> None:
    """ChangeConfiguration – MeterValueSampleInterval beállítása."""
    try:
        res = await change_configuration(cp_id, "MeterValueSampleInterval", str(interval_s))
        status = (res or {}).get("status", "Unknown")
        if status == "Accepted":
            logger.info(f"MeterValueSampleInterval={interval_s}s beállítva: cp={cp_id}")
        elif status == "RebootRequired":
            logger.info(f"MeterValueSampleInterval={interval_s}s – töltő újraindítást kér: cp={cp_id}")
        else:
            logger.warning(f"MeterValueSampleInterval beállítás visszautasítva: cp={cp_id} status={status}")
    except Exception as e:
        logger.warning(f"MeterValueSampleInterval beállítás sikertelen: cp={cp_id} err={e}")