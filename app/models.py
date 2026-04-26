"""Modelos SQLAlchemy — Watch, PriceSnapshot, Alert."""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(3))
    destination: Mapped[str] = mapped_column(String(3))
    departure: Mapped[date] = mapped_column(Date)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cabin: Mapped[str] = mapped_column(String(1), default="Y")
    adults: Mapped[int] = mapped_column(Integer, default=1)
    max_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    only_direct: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    snapshots: Mapped[list[PriceSnapshot]] = relationship(back_populates="watch", lazy="noload")
    alerts: Mapped[list[Alert]] = relationship(back_populates="watch", lazy="noload")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (
        Index("ix_price_snapshots_watch_captured", "watch_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    flight_number: Mapped[str] = mapped_column(String(10))
    stops: Mapped[int] = mapped_column(Integer, default=0)
    departure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    fare_brand: Mapped[str] = mapped_column(String(30))
    fare_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cabin: Mapped[str] = mapped_column(String(50))
    points: Mapped[int] = mapped_column(Integer)
    taxes_brl: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    watch: Mapped[Watch] = relationship(back_populates="snapshots", lazy="noload")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("price_snapshots.id"))
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    success: Mapped[bool] = mapped_column(Boolean, default=False)

    watch: Mapped[Watch] = relationship(back_populates="alerts", lazy="noload")
    snapshot: Mapped[PriceSnapshot] = relationship(lazy="noload")
