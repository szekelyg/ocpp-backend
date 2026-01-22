from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship

from .base import Base


def utcnow():
    return datetime.now(timezone.utc)


class ChargePoint(Base):
    __tablename__ = "charge_points"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, nullable=True)
    location_id = Column(Integer, nullable=True)

    # OCPP azonosító (path-ban használjuk, pl. VLTHU001B)
    ocpp_id = Column(String, unique=True, index=True, nullable=False)

    serial_number = Column(String, nullable=True)
    model = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
    firmware_version = Column(String, nullable=True)

    status = Column(String(32), nullable=False, default="available")
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    sessions = relationship(
        "ChargeSession",
        back_populates="charge_point",
        cascade="all, delete-orphan",
    )

    samples = relationship(
        "MeterSample",
        back_populates="charge_point",
        cascade="all, delete-orphan",
    )


class ChargeSession(Base):
    __tablename__ = "charge_sessions"

    id = Column(Integer, primary_key=True, index=True)

    charge_point_id = Column(Integer, ForeignKey("charge_points.id", ondelete="CASCADE"), nullable=False)

    connector_id = Column(Integer, nullable=True)  # pl. 1,2,3...
    ocpp_transaction_id = Column(String, nullable=True)  # StartTransaction transactionId
    user_tag = Column(String, nullable=True)  # RFID / user azonosító

    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # később ezek számolhatóak meter sample-ből is, de jó ha van "összegzett" mező
    energy_kwh = Column(Float, nullable=True)
    cost_huf = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    charge_point = relationship("ChargePoint", back_populates="sessions")

    samples = relationship(
        "MeterSample",
        back_populates="session",
    )


class MeterSample(Base):
    __tablename__ = "meter_samples"

    id = Column(Integer, primary_key=True, index=True)

    charge_point_id = Column(Integer, ForeignKey("charge_points.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(Integer, ForeignKey("charge_sessions.id", ondelete="SET NULL"), nullable=True)

    connector_id = Column(Integer, nullable=True)

    # OCPP meterValue[].timestamp (ha nincs, akkor szerver idő)
    ts = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    # számlázás / kijelzés szempontból fontosak
    energy_wh_total = Column(Float, nullable=True)  # Energy.Active.Import.Register (Wh)
    power_w = Column(Float, nullable=True)          # Power.Active.Import (W)
    current_a = Column(Float, nullable=True)        # Current.Import (A)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    charge_point = relationship("ChargePoint", back_populates="samples")
    session = relationship("ChargeSession", back_populates="samples")