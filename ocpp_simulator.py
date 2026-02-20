#!/usr/bin/env python3
import asyncio
import json
import sys
import random
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, List

import websockets


# ---------------- time helpers ----------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_offset(dt: Optional[datetime] = None) -> str:
    dt = dt or now_utc()
    s = dt.isoformat()
    if s.endswith("+00:00"):
        return s
    return s.replace("Z", "+00:00")


def floor_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def next_minute_boundary(dt: datetime) -> datetime:
    floored = floor_to_minute(dt)
    if dt == floored:
        return dt
    return floored + timedelta(minutes=1)


# ---------------- OCPP helpers ----------------

def ocpp_call(unique_id: str, action: str, payload: Dict[str, Any]) -> List[Any]:
    return [2, unique_id, action, payload]


@dataclass
class SimState:
    cp_id: str
    connector_id: int = 0

    plugged: bool = False      # <-- bedugva
    charging: bool = False     # <-- ténylegesen tölt

    power_w: int = 11000
    energy_wh_total: float = 7146314.0

    last_energy_update: datetime = now_utc()
    transaction_id: Optional[int] = None

    def set_plugged(self, on: bool) -> None:
        # ha kihúzzuk, akkor töltés is off + tx reset (StopTransaction-t külön küldjük a logikában)
        self.plugged = on
        if not on:
            self.charging = False

    def set_charging(self, on: bool) -> None:
        self._update_energy()
        self.charging = on

    def _update_energy(self) -> None:
        now = now_utc()
        dt = (now - self.last_energy_update).total_seconds()
        if dt <= 0:
            return

        if self.charging and self.power_w > 0:
            self.energy_wh_total += (self.power_w * dt) / 3600.0

        self.last_energy_update = now

    def get_energy_wh(self) -> int:
        self._update_energy()
        return int(round(self.energy_wh_total))

    def get_currents(self) -> Dict[str, float]:
        if not self.charging or self.power_w <= 0:
            return {"total": 0.0, "l1": 0.0, "l2": 0.0, "l3": 0.0}

        i = self.power_w / (math.sqrt(3) * 400.0)
        i = round(i, 2)
        return {"total": i, "l1": i, "l2": i, "l3": i}

    def get_powers(self) -> Dict[str, int]:
        if not self.charging or self.power_w <= 0:
            return {"total": 0, "l1": 0, "l2": 0, "l3": 0}

        per = int(round(self.power_w / 3))
        return {"total": self.power_w, "l1": per, "l2": per, "l3": per}

    def ocpp_status(self) -> str:
        # “bedugva, de nem tölt” -> Preparing
        if self.charging:
            return "Charging"
        if self.plugged:
            return "Preparing"
        return "Available"


# ---------------- Simulator ----------------

class VoltieLikeSimulator:
    def __init__(self, url: str):
        self.url = url
        self.cp_id = url.rstrip("/").split("/")[-1] or "VLTHU_SIM01"

        self.state = SimState(cp_id=self.cp_id)

        self._msg_counter = random.randint(118700000, 118799999)
        self.ws = None
        self._stop = asyncio.Event()

        # uid -> action (hogy tudjuk, melyik válasz mire jött)
        self._pending: Dict[str, str] = {}

    def next_id(self) -> str:
        self._msg_counter += 1
        return str(self._msg_counter)

    async def send_call(self, action: str, payload: Dict[str, Any]) -> str:
        uid = self.next_id()
        self._pending[uid] = action
        msg = ocpp_call(uid, action, payload)
        await self.ws.send(json.dumps(msg))
        print(f">> {action} ({uid})")
        return uid

    async def recv_loop(self) -> None:
        try:
            async for raw in self.ws:
                print(f"<< {raw}")
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                # CALLRESULT: [3, uniqueId, payload]
                if isinstance(msg, list) and len(msg) >= 3 and msg[0] == 3:
                    uid = msg[1]
                    payload = msg[2] if isinstance(msg[2], dict) else {}
                    action = self._pending.pop(uid, None)

                    if action == "StartTransaction":
                        txid = payload.get("transactionId")
                        if isinstance(txid, int) and txid > 0:
                            self.state.transaction_id = txid
                            print(f"[SIM] transactionId beállítva a válaszból: {self.state.transaction_id}")

        except Exception as e:
            print(f"[recv_loop] vége: {e}")
        finally:
            self._stop.set()

    # ---------------- Boot ----------------

    async def boot_sequence(self) -> None:
        boot_payload = {
            "chargePointVendor": "VOLTIE",
            "chargePointModel": "VOLTIE PRO",
            "chargeBoxSerialNumber": self.cp_id,
            "chargePointSerialNumber": "SIM-0000000000000000",
            "firmwareVersion": "1.2.46-2.89",
        }

        await self.send_call("BootNotification", boot_payload)

        await asyncio.sleep(0.2)
        await self.send_call("StatusNotification", {
            "connectorId": 1,
            "status": self.state.ocpp_status(),
            "errorCode": "NoError",
            "timestamp": iso_utc_offset(),
        })

        await asyncio.sleep(0.2)
        await self.send_call("FirmwareStatusNotification", {"status": "Installed"})

    # ---------------- Status helper ----------------

    async def send_status(self) -> None:
        await self.send_call("StatusNotification", {
            "connectorId": 1,
            "status": self.state.ocpp_status(),
            "errorCode": "NoError",
            "timestamp": iso_utc_offset(),
        })

    # ---------------- Transaction ----------------

    async def send_start_transaction(self):
        payload = {
            "connectorId": 1,
            "idTag": "SIM_USER",
            "timestamp": iso_utc_offset(),
            "meterStart": self.state.get_energy_wh(),
        }
        await self.send_call("StartTransaction", payload)
        print("[SIM] StartTransaction elküldve (txId a válaszból jön)")

    async def send_stop_transaction(self):
        if not self.state.transaction_id:
            print("[SIM] Nincs transaction_id, nem küldök StopTransaction-t.")
            return

        payload = {
            "transactionId": self.state.transaction_id,
            "timestamp": iso_utc_offset(),
            "meterStop": self.state.get_energy_wh(),
            "reason": "Local",
        }
        await self.send_call("StopTransaction", payload)
        print("[SIM] StopTransaction elküldve")

        self.state.transaction_id = None

    # ---------------- MeterValues ----------------

    def build_meter_values_payload(self, ts_minute: datetime) -> Dict[str, Any]:
        energy_wh = self.state.get_energy_wh()
        p = self.state.get_powers()
        i = self.state.get_currents()

        sampled = [
            {"measurand": "Current.Import", "format": "Raw", "unit": "A",
             "value": f"{i['total']:.2f}", "context": "Sample.Clock"},

            {"measurand": "Energy.Active.Import.Register", "format": "Raw", "unit": "Wh",
             "value": str(energy_wh), "context": "Sample.Clock"},

            {"measurand": "Power.Active.Import", "format": "Raw", "unit": "W",
             "value": str(p["total"]), "context": "Sample.Clock"},
        ]

        payload: Dict[str, Any] = {
            "connectorId": 0,  # Voltie-szerű: 0
            "meterValue": [{
                "sampledValue": sampled,
                "timestamp": iso_utc_offset(ts_minute),
            }]
        }

        # töltés közben küldünk transactionId-t
        if self.state.charging and self.state.transaction_id:
            payload["transactionId"] = self.state.transaction_id

        return payload

    async def meter_values_task(self) -> None:
        while not self._stop.is_set():
            now = now_utc()
            nxt = next_minute_boundary(now)
            await asyncio.sleep(max(0.1, (nxt - now).total_seconds()))

            ts = floor_to_minute(now_utc())
            payload = self.build_meter_values_payload(ts)
            await self.send_call("MeterValues", payload)

    async def heartbeat_task(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(60)
            await self.send_call("Heartbeat", {})

    # ---------------- CLI ----------------

    async def cli_task(self) -> None:
        print("\nParancsok: plug | unplug | start | stop | status | quit\n")
        loop = asyncio.get_running_loop()

        async def send_status(st: str):
            await self.send_call("StatusNotification", {
                "connectorId": 1,
                "status": st,
                "errorCode": "NoError",
                "timestamp": iso_utc_offset(),
            })

        while not self._stop.is_set():
            cmd = await loop.run_in_executor(None, input, "sim> ")
            cmd = cmd.strip().lower()

            if cmd == "plug":
                self.state.plugged = True
                # bedugva, de még nem tölt
                self.state.set_charging(False)
                await send_status("Preparing")

            elif cmd == "start":
                if not self.state.plugged:
                    print("[SIM] Előbb: plug (bedugás), utána: start")
                    continue

                # indul a töltés
                self.state.set_charging(True)
                await self.send_start_transaction()
                await send_status("Charging")

            elif cmd == "stop":
                if not self.state.charging:
                    print("[SIM] Nem tölt, stop-nak nincs hatása. (Ha ki akarod húzni: unplug)")
                    continue

                # leállítjuk a töltést (kábel maradhat bedugva)
                self.state.set_charging(False)
                await self.send_stop_transaction()

                # sok töltő küld Finishing-et; mi is küldhetjük
                await send_status("Finishing")

                # majd vissza Preparing-ra, mert bedugva maradt
                if self.state.plugged:
                    await asyncio.sleep(0.2)
                    await send_status("Preparing")
                else:
                    await asyncio.sleep(0.2)
                    await send_status("Available")

            elif cmd == "unplug":
                # ha tölt, előbb stop!
                if self.state.charging:
                    print("[SIM] Töltés közben unplug -> előbb stop, aztán unplug.")
                    # automatikusan megcsináljuk:
                    self.state.set_charging(False)
                    await self.send_stop_transaction()
                    await send_status("Finishing")
                    await asyncio.sleep(0.2)

                self.state.plugged = False
                self.state.set_charging(False)
                self.state.transaction_id = None
                await send_status("Available")

            elif cmd == "status":
                print(
                    f"plugged={self.state.plugged} charging={self.state.charging} "
                    f"tx={self.state.transaction_id} energy={self.state.get_energy_wh()} Wh"
                )

            elif cmd in ("quit", "exit"):
                self._stop.set()
    # ---------------- Main ----------------

    async def run(self) -> None:
        print(f"[SIM] csatlakozás: {self.url}")

        async with websockets.connect(
            self.url,
            subprotocols=["ocpp1.6"],
            ping_interval=None,
        ) as ws:
            self.ws = ws

            await self.boot_sequence()

            tasks = [
                asyncio.create_task(self.recv_loop()),
                asyncio.create_task(self.heartbeat_task()),
                asyncio.create_task(self.meter_values_task()),
                asyncio.create_task(self.cli_task()),
            ]

            await self._stop.wait()

            for t in tasks:
                t.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        print("[SIM] vége")


# ---------------- Entrypoint ----------------

def main():
    if len(sys.argv) < 2:
        print("Használat:")
        print("python ocpp_simulator.py ws://127.0.0.1:8000/ocpp/VLTHU_SIM01")
        sys.exit(1)

    url = sys.argv[1]
    sim = VoltieLikeSimulator(url)

    asyncio.run(sim.run())


if __name__ == "__main__":
    main()