from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Numeric,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class ChargePointStatus(str, PyEnum):
    offline = "offline"
    available = "available"
    charging = "charging"
    faulted = "faulted"


class ConnectorStatus(str, PyEnum):
    available = "available"
    occupied = "occupied"
    charging = "charging"
    faulted = "faulted"


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    slug = Column(String(255), nullable=False, unique=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    locations = relationship("Location", back_populates="organization")
    charge_points = relationship("ChargePoint", back_populates="organization")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)

    name = Column(String(255), nullable=False)
    address_text = Column(String(512), nullable=True)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    organization = relationship("Organization", back_populates="locations")
    charge_points = relationship("ChargePoint", back_populates="location")


class ChargePoint(Base):
    __tablename__ = "charge_points"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)

    ocpp_id = Column(String(255), nullable=False, unique=True)  # ChargeBoxIdentity
    serial_number = Column(String(255), nullable=True)
    model = Column(String(255), nullable=True)
    vendor = Column(String(255), nullable=True)
    firmware_version = Column(String(255), nullable=True)

    status = Column(String(32), nullable=False, default=ChargePointStatus.offline.value)
    last_seen_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    organization = relationship("Organization", back_populates="charge_points")
    location = relationship("Location", back_populates="charge_points")
    connectors = relationship("Connector", back_populates="charge_point")


class Connector(Base):
    __tablename__ = "connectors"

    id = Column(Integer, primary_key=True, index=True)
    charge_point_id = Column(Integer, ForeignKey("charge_points.id"), nullable=False)

    connector_number = Column(Integer, nullable=False)  # 1,2,3...
    max_kw = Column(Numeric(10, 2), nullable=True)

    status = Column(String(32), nullable=False, default=ConnectorStatus.available.value)
    last_status_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    charge_point = relationship("ChargePoint", back_populates="connectors")