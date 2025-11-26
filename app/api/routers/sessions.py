from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_db
from app.db.models import ChargeSession, ChargePoint

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/", response_model=list[dict])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ChargeSession))
    sessions = result.scalars().all()

    return [
        {
            "id": s.id,
            "charge_point_id": s.charge_point_id,
            "connector_id": s.connector_id,
            "ocpp_transaction_id": s.ocpp_transaction_id,
            "user_tag": s.user_tag,
            "started_at": s.started_at.isoformat(),
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            "energy_kwh": s.energy_kwh,
            "cost_huf": s.cost_huf,
        }
        for s in sessions
    ]