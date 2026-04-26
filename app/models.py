"""Modelos SQLAlchemy — Watch, PriceSnapshot, Alert, SearchJob."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
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
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class SearchJob(Base):
    __tablename__ = "search_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # calendar, range_dates, range_months
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
