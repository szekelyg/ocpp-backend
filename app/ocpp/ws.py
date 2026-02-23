# app/ocpp/ws.py
from __future__ import annotations

import json
import logging
from typing import Optional, Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.ocpp.parsers import extract_cp_id_from_boot
from app.ocpp.time_utils import iso_utc_now_z
from app.ocpp.registry import (
    register_ws,
    unregister_ws_if_same,
    pending_get,
)
from app.ocpp.handlers.boot import upsert_charge_point_from_boot
from app.ocpp.handlers.heartbeat import touch_last_seen
from app.ocpp.handlers.status import save_status_notification
from app.ocpp.handlers.transactions import start_transaction, stop_transaction
from app.ocpp.handlers.meter import save_meter_values

logger = logging.getLogger("ocpp")


async def handle_ocpp(ws: WebSocket, charge_point_id: Optional[str] = None):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    cp_id: Optional[str] = charge_point_id

    # ha path-ban jött az ID, regisztráljuk rögtön
    if cp_id:
        await register_ws(cp_id, ws)

    try:
        while True:
            raw = await ws.receive_text()
            logger.info(f"OCPP RAW: {raw}")

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
                else:
                    logger.warning("Nem tudtam ChargePoint ID-t kinyerni BootNotificationből")

            if not cp_id:
                # nincs cp_id, de ACK-oljunk safe defaulttal
                await ws.send_text(json.dumps([3, unique_id, {}]))
                continue

            # registry frissítés (ha új ws)
            await register_ws(cp_id, ws)

            # ----------------------------------------------------------------------
            # ACTION DISPATCH
            # ----------------------------------------------------------------------
            if action == "BootNotification":
                await upsert_charge_point_from_boot(cp_id, payload)
                response = [3, unique_id, {"status": "Accepted", "currentTime": iso_utc_now_z(), "interval": 60}]
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

            elif action == "StopTransaction":
                await stop_transaction(cp_id, payload)
                response = [3, unique_id, {"idTagInfo": {"status": "Accepted"}}]
                await ws.send_text(json.dumps(response))

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