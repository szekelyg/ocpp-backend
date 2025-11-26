from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from .base import Base


class ChargePoint(Base):
    __tablename__ = "charge_points"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, nullable=True)
    location_id = Column(Integer, nullable=True)

    # OCPP azonosító (amit a path-ban használunk, pl. VLTHU001B)
    ocpp_id = Column(String, unique=True, index=True, nullable=False)

    serial_number = Column(String, nullable=True)
    model = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
    firmware_version = Column(String, nullable=True)

    status = Column(String, nullable=True)  # pl. Available, Charging, Faulted
    last_seen_at = Column(DateTime, nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.utcnow(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )

    sessions = relationship(
        "ChargeSession",
        back_populates="charge_point",
        cascade="all, delete-orphan",
    )


class ChargeSession(Base):
    __tablename__ = "charge_sessions"

    id = Column(Integer, primary_key=True, index=True)

    charge_point_id = Column(
        Integer,
        ForeignKey("charge_points.id", ondelete="CASCADE"),
        nullable=False,
    )

    connector_id = Column(Integer, nullable=True)  # pl. 1,2,3...
    ocpp_transaction_id = Column(String, nullable=True)  # StartTransaction ID
    user_tag = Column(String, nullable=True)  # RFID / user azonosító

    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    energy_kwh = Column(Float, nullable=True)
    cost_huf = Column(Float, nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.utcnow(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )

    charge_point = relationship("ChargePoint", back_populates="sessions")