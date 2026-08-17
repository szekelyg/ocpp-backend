# app/ocpp/handlers/boot.py
from __future__ import annotations

import logging
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint
from app.ocpp.time_utils import utcnow

logger = logging.getLogger("ocpp")


async def upsert_charge_point_from_boot(cp_id: str, payload: dict) -> None:
    vendor = payload.get("chargePointVendor")
    model = payload.get("chargePointModel")
    serial = payload.get("chargePointSerialNumber")
    fw = payload.get("firmwareVersion")

    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            cp = res.scalar_one_or_none()

            now_dt = utcnow()

            if cp is None:
                # Publikálatlanul jön létre: az admin felületen jelenik meg
                # "konfigurálásra vár" alatt, az éles appban nem.
                cp = ChargePoint(
                    ocpp_id=cp_id,
                    vendor=vendor,
                    model=model,
                    serial_number=serial,
                    firmware_version=fw,
                    status="available",
                    last_seen_at=now_dt,
                    is_published=False,
                )
                session.add(cp)
                logger.warning(
                    f"Új ChargePoint létrehozva, KONFIGURÁLÁSRA VÁR: {cp_id} "
                    f"(vendor={vendor} model={model} serial={serial}) – "
                    f"az admin felületen kell helyszínt/koordinátát/csatlakozót megadni és publikálni"
                )
            else:
                cp.vendor = vendor
                cp.model = model
                cp.serial_number = serial
                cp.firmware_version = fw
                cp.status = "available"
                cp.last_seen_at = now_dt
                logger.info(f"ChargePoint frissítve: {cp_id}")

            await session.commit()
    except Exception as e:
        logger.exception(f"Hiba a ChargePoint mentésekor: {e}")