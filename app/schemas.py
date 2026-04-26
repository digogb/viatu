"""Schemas Pydantic para entrada/saída da API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

CabinType = Literal["Y", "W", "J", "F"]
CABIN_TO_LATAM = {
    "Y": "Economy",
    "W": "PremiumEconomy",
    "J": "Business",
    "F": "First",
}


class SearchRequest(BaseModel):
    origin: str = Field(min_length=3, max_length=3, description="IATA da origem")
    destination: str = Field(min_length=3, max_length=3)
    departure: date
    return_date: date | None = None
    adults: int = Field(default=1, ge=1, le=9)
    cabin: CabinType = "Y"


class FareOption(BaseModel):
    flight_number: str
    departure_at: str
    arrival_at: str
    duration_minutes: int
    cabin: str
    points: int
    taxes_brl: float
    fare_brand: str | None = None
    stops: int = 0
    fare_basis: str | None = None
    offer_id: str | None = None
    operators: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    origin: str
    destination: str
    departure: date
    return_date: date | None = None
    options: list[FareOption]
    fetched_at: datetime


class WatchCreate(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departure: date
    return_date: date | None = None
    cabin: CabinType = "Y"
    adults: int = Field(default=1, ge=1, le=9)
    max_points: int | None = None
    only_direct: bool = True
    interval_minutes: int = Field(default=30, ge=15, le=1440)
    notify_phone: str | None = None  # E.164


class WatchUpdate(BaseModel):
    max_points: int | None = None
    only_direct: bool | None = None
    interval_minutes: int | None = None
    notify_phone: str | None = None
    active: bool | None = None


class WatchOut(BaseModel):
    id: int
    origin: str
    destination: str
    departure: date
    return_date: date | None
    cabin: str
    adults: int
    max_points: int | None
    only_direct: bool
    interval_minutes: int
    notify_phone: str | None
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SnapshotOut(BaseModel):
    id: int
    watch_id: int
    flight_number: str
    stops: int
    departure_at: datetime | None
    arrival_at: datetime | None
    duration_minutes: int
    fare_brand: str
    fare_basis: str | None
    cabin: str
    points: int
    taxes_brl: float
    captured_at: datetime

    model_config = {"from_attributes": True}


class WatchDetail(WatchOut):
    snapshots: list[SnapshotOut] = []


class CheckResult(BaseModel):
    watch_id: int
    new_snapshots: int
    cheapest: SnapshotOut | None = None
