import asyncio
import json
from datetime import datetime, timezone

import websockets


async def ocpp_simulator():
    # Szimulált töltő ID
    charge_point_id = "VLTHU_SIM01"

    # VÁLASZTHATSZ:
    # ha a Cloudflare-en át akarod tesztelni:
    # url = f"ws://ocpp.napos.hu/ocpp/{charge_point_id}"
    # ha csak lokálban akarod (stabilabb, egyszerűbb):
    url = f"ws://localhost:8000/ocpp/{charge_point_id}"

    print(f"Kapcsolódás: {url}")

    async with websockets.connect(url) as ws:
        print("WebSocket kapcsolat nyitva (szimulátor)")

        # ---- 1) BootNotification ----
        boot_msg_id = "SIM-BOOT-1"
        boot_payload = {
            "chargePointVendor": "SIM_VENDOR",
            "chargePointModel": "SIM_MODEL",
            "chargeBoxSerialNumber": charge_point_id,
            "chargePointSerialNumber": "SIM-SERIAL-0001",
            "firmwareVersion": "0.0.1",
            "iccid": "",
            "imsi": "",
            "meterType": "SIM meter",
            "meterSerialNumber": "SIM-METER-0001",
        }

        boot_frame = [2, boot_msg_id, "BootNotification", boot_payload]
        await ws.send(json.dumps(boot_frame))
        print("BootNotification elküldve:", boot_frame)

        boot_resp = await ws.recv()
        print("BootNotification válasz:", boot_resp)

        # ---- 2) Heartbeat ----
        hb_msg_id = "SIM-HB-1"
        hb_frame = [2, hb_msg_id, "Heartbeat", {}]
        await ws.send(json.dumps(hb_frame))
        print("Heartbeat elküldve:", hb_frame)

        hb_resp = await ws.recv()
        print("Heartbeat válasz:", hb_resp)

        # ---- 3) MeterValues (egyszerűsített) ----
        mv_msg_id = "SIM-MV-1"
        now_iso = datetime.now(timezone.utc).isoformat()

        mv_payload = {
            "connectorId": 0,
            "meterValue": [
                {
                    "timestamp": now_iso,
                    "sampledValue": [
                        {
                            "measurand": "Energy.Active.Import.Register",
                            "unit": "Wh",
                            "value": "123456",
                            "context": "Sample.Clock",
                        },
                        {
                            "measurand": "Power.Active.Import",
                            "unit": "W",
                            "value": "3500",
                            "context": "Sample.Clock",
                        },
                    ],
                }
            ],
        }

        mv_frame = [2, mv_msg_id, "MeterValues", mv_payload]
        await ws.send(json.dumps(mv_frame))
        print("MeterValues elküldve:", mv_frame)

        mv_resp = await ws.recv()
        print("MeterValues válasz:", mv_resp)

        print("Szimuláció kész, kapcsolat lezárva.")


if __name__ == "__main__":
    asyncio.run(ocpp_simulator())