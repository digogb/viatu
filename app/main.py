"""API HTTP — busca on-demand e CRUD de watches."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.latam_client import LatamAuthError, LatamClient
from app.models import PriceSnapshot, Watch
from app.schemas import (
    CheckResult,
    SearchRequest,
    SearchResponse,
    SnapshotOut,
    WatchCreate,
    WatchDetail,
    WatchOut,
    WatchUpdate,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.latam = LatamClient()
    yield
    await app.state.latam.aclose()


app = FastAPI(title="Viatu", version="0.1.0", lifespan=lifespan)


def get_latam() -> LatamClient:
    return app.state.latam


# ---------------------------------------------------------------------------
# Busca on-demand
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.now(UTC).isoformat()}


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, client: LatamClient = Depends(get_latam)):
    try:
        options = await client.search(req)
    except LatamAuthError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    options.sort(key=lambda o: o.points)
    return SearchResponse(
        origin=req.origin.upper(),
        destination=req.destination.upper(),
        departure=req.departure,
        return_date=req.return_date,
        options=options,
        fetched_at=datetime.now(UTC),
    )


@app.get("/calendar")
async def calendar(
    origin: str,
    destination: str,
    month: int,
    year: int,
    round_trip: bool = False,
    client: LatamClient = Depends(get_latam),
):
    try:
        data = await client.calendar(origin, destination, month, year, round_trip)
    except LatamAuthError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return data


# ---------------------------------------------------------------------------
# Watches CRUD
# ---------------------------------------------------------------------------

@app.post("/watches", response_model=WatchOut, status_code=201)
async def create_watch(body: WatchCreate, db: AsyncSession = Depends(get_session)):
    watch = Watch(**body.model_dump())
    db.add(watch)
    await db.commit()
    await db.refresh(watch)
    return watch


@app.get("/watches", response_model=list[WatchOut])
async def list_watches(active_only: bool = True, db: AsyncSession = Depends(get_session)):
    q = select(Watch).order_by(Watch.created_at.desc())
    if active_only:
        q = q.where(Watch.active.is_(True))
    result = await db.execute(q)
    return result.scalars().all()


@app.get("/watches/{watch_id}", response_model=WatchDetail)
async def get_watch(watch_id: int, db: AsyncSession = Depends(get_session)):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")
    result = await db.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.watch_id == watch_id)
        .order_by(PriceSnapshot.captured_at.desc())
        .limit(20)
    )
    snapshots = result.scalars().all()
    return WatchDetail.model_validate({**watch.__dict__, "snapshots": snapshots})


@app.patch("/watches/{watch_id}", response_model=WatchOut)
async def update_watch(watch_id: int, body: WatchUpdate, db: AsyncSession = Depends(get_session)):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(watch, k, v)
    await db.commit()
    await db.refresh(watch)
    return watch


@app.delete("/watches/{watch_id}", status_code=204)
async def delete_watch(watch_id: int, db: AsyncSession = Depends(get_session)):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")
    watch.active = False
    await db.commit()


# ---------------------------------------------------------------------------
# Check síncrono
# ---------------------------------------------------------------------------

@app.post("/watches/{watch_id}/check", response_model=CheckResult)
async def check_watch(
    watch_id: int,
    db: AsyncSession = Depends(get_session),
    client: LatamClient = Depends(get_latam),
):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")

    req = SearchRequest(
        origin=watch.origin,
        destination=watch.destination,
        departure=watch.departure,
        return_date=watch.return_date,
        adults=watch.adults,
        cabin=watch.cabin,  # type: ignore[arg-type]
    )

    try:
        options = await client.search(req)
    except LatamAuthError as e:
        raise HTTPException(503, str(e)) from e

    now = datetime.now(UTC)
    snaps: list[PriceSnapshot] = []
    for opt in options:
        snap = PriceSnapshot(
            watch_id=watch.id,
            flight_number=opt.flight_number,
            stops=opt.stops,
            departure_at=datetime.fromisoformat(opt.departure_at) if opt.departure_at else None,
            arrival_at=datetime.fromisoformat(opt.arrival_at) if opt.arrival_at else None,
            duration_minutes=opt.duration_minutes,
            fare_brand=opt.fare_brand or "UNKNOWN",
            fare_basis=opt.fare_basis,
            cabin=opt.cabin,
            points=opt.points,
            taxes_brl=opt.taxes_brl,
            captured_at=now,
        )
        db.add(snap)
        snaps.append(snap)

    await db.commit()
    for s in snaps:
        await db.refresh(s)

    cheapest = min(snaps, key=lambda s: s.points) if snaps else None
    cheapest_out = SnapshotOut.model_validate(cheapest) if cheapest else None
    return CheckResult(watch_id=watch.id, new_snapshots=len(snaps), cheapest=cheapest_out)
