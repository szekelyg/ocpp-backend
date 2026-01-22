#!/usr/bin/env python3
import asyncio
import json
import sys
import time
import random
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, List

import websockets


# ---------------- time helpers ----------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso_utc_z(dt: Optional[datetime] = None) -> str:
    dt = dt or now_utc()
    # VOLTIE a +00:00-t küldi a meter timestampban, de a Heartbeat response-ban nálad "Z" is ok volt.
    # Itt egységesen +00:00-t adunk a töltő által küldött timestampokban.
    return dt.isoformat().replace("+00:00", "Z")

def iso_utc_offset(dt: Optional[datetime] = None) -> str:
    dt = dt or now_utc()
    # '2026-01-22T14:50:00.000+00:00' stílushoz:
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

def ocpp_call_result(unique_id: str, payload: Dict[str, Any]) -> List[Any]:
    return [3, unique_id, payload]

@dataclass
class SimState:
    cp_id: str
    connector_id: int = 0  # VOLTIE-nál logban 0
    charging: bool = False
    power_w: int = 11000   # 11 kW
    energy_wh_total: float = 7146314.0  # induló érték (Wh) – mint a logban (persze lehet akár 0 is)
    last_energy_update: datetime = now_utc()

    def set_charging(self, on: bool) -> None:
        self._update_energy()
        self.charging = on

    def set_power(self, w: int) -> None:
        self._update_energy()
        self.power_w = max(0, int(w))

    def _update_energy(self) -> None:
        # energiát valós idő alapján növeljük: Wh += (W * dt_seconds / 3600)
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
        # 3 fázis ~ 400V line-line, P ≈ sqrt(3)*V*I  => I ≈ P / (sqrt(3)*400)
        # 11kW -> ~15.9A
        if not self.charging or self.power_w <= 0:
            return {"total": 0.0, "l1": 0.0, "l2": 0.0, "l3": 0.0}
        i = self.power_w / (math.sqrt(3) * 400.0)
        # VOLTIE logban 2 tizedes
        i = round(i, 2)
        return {"total": i, "l1": i, "l2": i, "l3": i}

    def get_powers(self) -> Dict[str, int]:
        if not self.charging or self.power_w <= 0:
            return {"total": 0, "l1": 0, "l2": 0, "l3": 0}
        per = int(round(self.power_w / 3))
        return {"total": int(self.power_w), "l1": per, "l2": per, "l3": per}


class VoltieLikeSimulator:
    def __init__(self, url: str):
        self.url = url
        # cp id a path-ból
        self.cp_id = url.rstrip("/").split("/")[-1] or "VLTHU_SIM01"
        self.state = SimState(cp_id=self.cp_id)

        # uniqueId VOLTIE-nál szám string
        self._msg_counter = random.randint(118700000, 118799999)

        self.ws = None
        self._stop = asyncio.Event()

    def next_id(self) -> str:
        self._msg_counter += 1
        return str(self._msg_counter)

    async def send_call(self, action: str, payload: Dict[str, Any]) -> None:
        uid = self.next_id()
        msg = ocpp_call(uid, action, payload)
        await self.ws.send(json.dumps(msg))
        print(f">> {action} {uid}")

    async def recv_loop(self) -> None:
        try:
            async for raw in self.ws:
                # szerver válaszai jönnek (CALLRESULT = 3)
                print(f"<< {raw}")
        except Exception as e:
            print(f"[recv_loop] vége: {e}")
        finally:
            self._stop.set()

    async def boot_sequence(self) -> None:
        # VOLTIE-szerű Boot payload
        boot_payload = {
            "chargePointVendor": "VOLTIE",
            "chargePointModel": "VOLTIE PRO",
            "chargeBoxSerialNumber": self.cp_id,
            "chargePointSerialNumber": "SIM-0000000000000000",
            "firmwareVersion": "1.2.46-2.89",
            "iccid": "",
            "imsi": "",
            "meterType": "Internal meter",
            "meterSerialNumber": "No Id read yet",
        }
        await self.send_call("BootNotification", boot_payload)

        # StatusNotification (0 és 1) – mint a VOLTIE log
        await asyncio.sleep(0.2)
        await self.send_call("StatusNotification", {
            "connectorId": 0,
            "status": "Available",
            "errorCode": "NoError",
            "timestamp": iso_utc_offset(now_utc()).replace("+00:00", "+00:00"),
        })
        await asyncio.sleep(0.2)
        await self.send_call("StatusNotification", {
            "connectorId": 1,
            "status": "Available",
            "errorCode": "NoError",
            "timestamp": iso_utc_offset(now_utc()).replace("+00:00", "+00:00"),
        })

        # FirmwareStatusNotification
        await asyncio.sleep(0.2)
        await self.send_call("FirmwareStatusNotification", {"status": "Installed"})

    def build_meter_values_payload(self, ts_minute: datetime) -> Dict[str, Any]:
        # VOLTIE log: connectorId:0 és meterValue:[{ sampledValue:[...], timestamp:"...:00.000+00:00"}]
        energy_wh = self.state.get_energy_wh()
        p = self.state.get_powers()
        i = self.state.get_currents()

        # VOLTIE-szerű: format Raw, context Sample.Clock, több measurand + phases
        sampled = [
            {"measurand": "Current.Import", "format": "Raw", "unit": "A", "value": f"{i['total']:.2f}", "context": "Sample.Clock"},
            {"measurand": "Current.Import", "phase": "L1", "format": "Raw", "unit": "A", "value": f"{i['l1']:.2f}", "context": "Sample.Clock"},
            {"measurand": "Current.Import", "phase": "L2", "format": "Raw", "unit": "A", "value": f"{i['l2']:.2f}", "context": "Sample.Clock"},
            {"measurand": "Current.Import", "phase": "L3", "format": "Raw", "unit": "A", "value": f"{i['l3']:.2f}", "context": "Sample.Clock"},

            # VOLTIE-ben van Current.Offered is
            {"measurand": "Current.Offered", "format": "Raw", "unit": "A", "value": "0" if not self.state.charging else f"{i['total']:.0f}", "context": "Sample.Clock"},

            {"measurand": "Energy.Active.Import.Register", "format": "Raw", "unit": "Wh", "value": str(energy_wh), "context": "Sample.Clock"},
            # VOLTIE logban fázis energiák 0 voltak; itt is 0-ra hagyjuk (hűség)
            {"measurand": "Energy.Active.Import.Register", "phase": "L1", "format": "Raw", "unit": "Wh", "value": "0", "context": "Sample.Clock"},
            {"measurand": "Energy.Active.Import.Register", "phase": "L2", "format": "Raw", "unit": "Wh", "value": "0", "context": "Sample.Clock"},
            {"measurand": "Energy.Active.Import.Register", "phase": "L3", "format": "Raw", "unit": "Wh", "value": "0", "context": "Sample.Clock"},

            {"measurand": "Power.Active.Import", "format": "Raw", "unit": "W", "value": str(p["total"]), "context": "Sample.Clock"},
            {"measurand": "Power.Active.Import", "phase": "L1", "format": "Raw", "unit": "W", "value": str(p["l1"]), "context": "Sample.Clock"},
            {"measurand": "Power.Active.Import", "phase": "L2", "format": "Raw", "unit": "W", "value": str(p["l2"]), "context": "Sample.Clock"},
            {"measurand": "Power.Active.Import", "phase": "L3", "format": "Raw", "unit": "W", "value": str(p["l3"]), "context": "Sample.Clock"},
        ]

        mv = {
            "sampledValue": sampled,
            "timestamp": iso_utc_offset(ts_minute),
        }
        return {
            "connectorId": self.state.connector_id,
            "meterValue": [mv],
        }

    async def heartbeat_task(self) -> None:
        # VOLTIE: kb 60 mp-enként
        while not self._stop.is_set():
            await asyncio.sleep(60)
            await self.send_call("Heartbeat", {})

    async def meter_values_task(self) -> None:
        # VOLTIE: kerek percben küldi, timestamp ...:00.000+00:00
        # Itt úgy csináljuk, hogy mindig a következő perc elejéig alszunk.
        while not self._stop.is_set():
            now = now_utc()
            nxt = next_minute_boundary(now)
            # hogy tényleg elérjük a :00-t
            sleep_s = max(0.1, (nxt - now).total_seconds())
            await asyncio.sleep(sleep_s)

            ts = floor_to_minute(now_utc())
            payload = self.build_meter_values_payload(ts)
            await self.send_call("MeterValues", payload)

    async def cli_task(self) -> None:
        # egyszerű "gombok" a terminálban
        help_txt = (
            "\nParancsok:\n"
            "  start            -> töltés indul (11kW default)\n"
            "  stop             -> töltés leáll\n"
            "  power <W>         -> teljesítmény W-ban (pl. power 11000)\n"
            "  status           -> állapot kiírás\n"
            "  quit             -> kilép\n"
        )
        print(help_txt)

        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                cmd = await loop.run_in_executor(None, input, "sim> ")
            except (EOFError, KeyboardInterrupt):
                self._stop.set()
                break

            cmd = (cmd or "").strip()
            if not cmd:
                continue

            if cmd == "start":
                self.state.set_charging(True)
                print(f"[OK] Töltés: ON, power={self.state.power_w}W")
                # opcionális: küldhetünk StatusNotification-t "Charging"-re (ha akarod)
                await self.send_call("StatusNotification", {
                    "connectorId": 1,
                    "status": "Charging",
                    "errorCode": "NoError",
                    "timestamp": iso_utc_offset(now_utc()),
                })

            elif cmd == "stop":
                self.state.set_charging(False)
                print("[OK] Töltés: OFF")
                await self.send_call("StatusNotification", {
                    "connectorId": 1,
                    "status": "Available",
                    "errorCode": "NoError",
                    "timestamp": iso_utc_offset(now_utc()),
                })

            elif cmd.startswith("power "):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].isdigit():
                    self.state.set_power(int(parts[1]))
                    print(f"[OK] power={self.state.power_w}W")
                else:
                    print("[HIBA] Használat: power 11000")

            elif cmd == "status":
                print(f"cp_id={self.state.cp_id} charging={self.state.charging} power_w={self.state.power_w} energy_wh_total={self.state.get_energy_wh()}")

            elif cmd in ("quit", "exit"):
                self._stop.set()
                break

            else:
                print(help_txt)

    async def run(self) -> None:
        print(f"[SIM] csatlakozás: {self.url}")
        async with websockets.connect(
            self.url,
            subprotocols=["ocpp1.6"],
            ping_interval=None,   # OCPP-nél jobb ha mi kontrolláljuk
        ) as ws:
            self.ws = ws

            # indító szekvencia
            await self.boot_sequence()

            # feladatok
            tasks = [
                asyncio.create_task(self.recv_loop()),
                asyncio.create_task(self.heartbeat_task()),
                asyncio.create_task(self.meter_values_task()),
                asyncio.create_task(self.cli_task()),
            ]

            await self._stop.wait()

            for t in tasks:
                t.cancel()
            # best-effort cancel
            await asyncio.gather(*tasks, return_exceptions=True)

        print("[SIM] vége")


def main():
    if len(sys.argv) < 2:
        print("Használat:")
        print("  python ocpp_simulator.py ws://127.0.0.1:8000/ocpp/VLTHU_SIM01")
        print("  python ocpp_simulator.py wss://ocpp.napos.hu/ocpp/VLTHU_SIM01")
        sys.exit(1)

    url = sys.argv[1].strip()
    sim = VoltieLikeSimulator(url)
    asyncio.run(sim.run())


if __name__ == "__main__":
    main()