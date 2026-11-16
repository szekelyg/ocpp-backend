# app/ocpp/handlers/boot.py
from __future__ import annotations

import logging
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint
from app.ocpp.time_utils import utcnow

logger = logging.getLogger("ocpp")

# Ennyi publikálatlan („konfigurálásra vár") töltő lehet egyszerre. Ismeretlen azonosítóval
# bárki küldhet BootNotificationt, és mindegyik új charge_points sort hozna létre.
MAX_UNPUBLISHED_CHARGE_POINTS = 20


async def upsert_charge_point_from_boot(cp_id: str, payload: dict) -> bool:
    """A töltő adatainak mentése. False = ismeretlen töltő, de a publikálatlanok kerete betelt
    (nem vesszük fel, a boot elutasítandó)."""
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
                unpublished = (await session.execute(
                    select(func.count()).select_from(ChargePoint).where(ChargePoint.is_published.is_(False))
                )).scalar_one()
                if unpublished >= MAX_UNPUBLISHED_CHARGE_POINTS:
                    logger.warning(
                        f"Ismeretlen töltő BootNotificationje ELUTASÍTVA: {cp_id} – már {unpublished} "
                        f"publikálatlan töltő vár konfigurálásra (keret: {MAX_UNPUBLISHED_CHARGE_POINTS}); "
                        f"az admin felületen publikálni vagy törölni kell közülük"
                    )
                    return False
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
    return True
