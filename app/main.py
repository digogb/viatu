"""API HTTP — busca on-demand, CRUD de watches, auth dashboard."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_token, require_auth
from app.config import get_settings
from app.db import get_session
from app.latam_client import LatamAuthError, LatamClient, PlaywrightSearchClient
from app.models import Alert, PriceSnapshot, SearchJob, Watch
from app.schemas import (
    AlertOut,
    CalendarRequest,
    CalendarResponse,
    CheckResult,
    HistoryDay,
    JobOut,
    LoginRequest,
    SearchRangeRequest,
    SearchRequest,
    SearchResponse,
    SnapshotOut,
    WatchCreate,
    WatchDetail,
    WatchOut,
    WatchUpdate,
    WatchWithSnapshot,
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


AuthDep = Annotated[str, Depends(require_auth)]

# ---------------------------------------------------------------------------
# Health (sem auth, necessário para Docker healthcheck)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.now(UTC).isoformat()}


# ---------------------------------------------------------------------------
# API Router (prefix /api)
# ---------------------------------------------------------------------------

api = APIRouter(prefix="/api")


# --- Auth ---

@api.post("/auth/login")
async def login(body: LoginRequest, response: Response):
    cfg = get_settings()
    if body.password != cfg.dashboard_password:
        raise HTTPException(status_code=401, detail="Senha incorreta")
    token = create_token()
    response.set_cookie(
        "viatu_session",
        token,
        httponly=True,
        max_age=cfg.jwt_ttl_days * 86_400,
        samesite="lax",
    )
    return {"ok": True}


@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("viatu_session")
    return {"ok": True}


@api.get("/auth/me")
async def me(auth: AuthDep):
    return {"authenticated": True}


# --- Busca ---

@api.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    auth: AuthDep,
    client: LatamClient = Depends(get_latam),
):
    try:
        options = await client.search(req)
    except LatamAuthError as e:
        raise HTTPException(503, str(e)) from e
    options.sort(key=lambda o: o.points)
    return SearchResponse(
        origin=req.origin.upper(),
        destination=req.destination.upper(),
        departure=req.departure,
        return_date=req.return_date,
        options=options,
        fetched_at=datetime.now(UTC),
    )


@api.post("/search/calendar", response_model=CalendarResponse)
async def search_calendar(
    body: CalendarRequest,
    auth: AuthDep,
    client: LatamClient = Depends(get_latam),
):
    try:
        data = await client.calendar(body.origin, body.destination, body.month, body.year, body.round_trip)
    except LatamAuthError as e:
        raise HTTPException(503, str(e)) from e

    days = []
    for item in data.get("content", []):
        date_str = item.get("date") or item.get("outFrom", "")
        lowest = item.get("lowestPrice") or {}
        if date_str and lowest.get("amount"):
            days.append({
                "date": str(date_str)[:10],
                "points": int(lowest["amount"]),
                "taxes_brl": float(lowest.get("taxes", 0)),
            })
    return CalendarResponse(days=days)


@api.post("/search/range")
async def search_range(
    body: SearchRangeRequest,
    auth: AuthDep,
    db: AsyncSession = Depends(get_session),
):
    if len(body.dates) > 7:
        from app.tasks import run_search_job
        job = SearchJob(
            kind="range_dates",
            params=body.model_dump(mode="json"),
            status="pending",
            progress=0,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        run_search_job.delay(job.id)
        return {"job_id": job.id}

    # Síncrono — até 7 datas via Playwright em thread
    pw_client = PlaywrightSearchClient()
    results = []
    for dep_date in body.dates:
        req = SearchRequest(
            origin=body.origin,
            destination=body.destination,
            departure=dep_date,
            return_date=body.return_date,
            adults=body.adults,
            cabin=body.cabin,
        )
        try:
            options = await asyncio.to_thread(pw_client.search, req)
            cheapest = min(
                (o for o in options if (o.fare_brand or "").upper() == "LIGHT"),
                key=lambda o: o.points,
                default=options[0] if options else None,
            )
            results.append({
                "date": dep_date.isoformat(),
                "cheapest_light": cheapest.model_dump() if cheapest else None,
                "options": [o.model_dump() for o in options],
            })
        except Exception as exc:
            logger.warning("range search falhou para %s: %s", dep_date, exc)
            results.append({"date": dep_date.isoformat(), "error": str(exc)})
    return {"results": results}


# --- Jobs ---

@api.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: int, auth: AuthDep, db: AsyncSession = Depends(get_session)):
    job = await db.get(SearchJob, job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return job


@api.delete("/jobs/{job_id}", status_code=204)
async def cancel_job(job_id: int, auth: AuthDep, db: AsyncSession = Depends(get_session)):
    job = await db.get(SearchJob, job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    job.status = "error"
    job.error = "Cancelado pelo usuário"
    await db.commit()


# --- Watches (rotas estáticas antes das dinâmicas) ---

@api.post("/watches/from-search", response_model=WatchOut, status_code=201)
async def create_watch_from_search(
    body: WatchCreate,
    auth: AuthDep,
    db: AsyncSession = Depends(get_session),
):
    watch = Watch(**body.model_dump())
    db.add(watch)
    await db.commit()
    await db.refresh(watch)
    return watch


@api.post("/watches", response_model=WatchOut, status_code=201)
async def create_watch(body: WatchCreate, auth: AuthDep, db: AsyncSession = Depends(get_session)):
    watch = Watch(**body.model_dump())
    db.add(watch)
    await db.commit()
    await db.refresh(watch)
    return watch


@api.get("/watches", response_model=list[WatchWithSnapshot])
async def list_watches(
    active_only: bool = True,
    auth: AuthDep = ...,
    db: AsyncSession = Depends(get_session),
):
    q = select(Watch).order_by(Watch.created_at.desc())
    if active_only:
        q = q.where(Watch.active.is_(True))
    watches = (await db.execute(q)).scalars().all()

    result = []
    for w in watches:
        snap_row = (
            await db.execute(
                select(PriceSnapshot)
                .where(PriceSnapshot.watch_id == w.id, PriceSnapshot.fare_brand == "LIGHT")
                .order_by(PriceSnapshot.captured_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        result.append(WatchWithSnapshot.model_validate({**w.__dict__, "last_snapshot": snap_row}))
    return result


@api.get("/watches/{watch_id}/history", response_model=list[HistoryDay])
async def watch_history(
    watch_id: int,
    days: int = 30,
    auth: AuthDep = ...,
    db: AsyncSession = Depends(get_session),
):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")

    cutoff = datetime.now(UTC) - timedelta(days=days)
    day_col = func.date_trunc("day", PriceSnapshot.captured_at).label("day")
    rows = (
        await db.execute(
            select(
                day_col,
                func.min(PriceSnapshot.points).label("min_points"),
                func.max(PriceSnapshot.points).label("max_points"),
                func.avg(PriceSnapshot.points).label("avg_points"),
            )
            .where(
                PriceSnapshot.watch_id == watch_id,
                PriceSnapshot.fare_brand == "LIGHT",
                PriceSnapshot.captured_at >= cutoff,
            )
            .group_by(day_col)
            .order_by(day_col)
        )
    ).all()

    return [
        HistoryDay(
            date=r.day.date().isoformat(),
            min_points=r.min_points,
            max_points=r.max_points,
            avg_points=float(r.avg_points),
        )
        for r in rows
    ]


@api.put("/watches/{watch_id}/active", response_model=WatchOut)
async def toggle_active(
    watch_id: int,
    auth: AuthDep,
    db: AsyncSession = Depends(get_session),
):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")
    watch.active = not watch.active
    await db.commit()
    await db.refresh(watch)
    return watch


@api.get("/watches/{watch_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(
    watch_id: int,
    auth: AuthDep = ...,
    page: int = 1,
    page_size: int = 50,
    fare_brand: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")

    q = (
        select(PriceSnapshot)
        .where(PriceSnapshot.watch_id == watch_id)
        .order_by(PriceSnapshot.captured_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if fare_brand:
        q = q.where(PriceSnapshot.fare_brand == fare_brand.upper())
    rows = (await db.execute(q)).scalars().all()
    return rows


@api.get("/watches/{watch_id}/alerts", response_model=list[AlertOut])
async def list_alerts(
    watch_id: int,
    auth: AuthDep = ...,
    db: AsyncSession = Depends(get_session),
):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")

    rows = (
        await db.execute(
            select(Alert)
            .where(Alert.watch_id == watch_id)
            .order_by(Alert.sent_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return rows


@api.get("/watches/{watch_id}", response_model=WatchDetail)
async def get_watch(watch_id: int, auth: AuthDep = ..., db: AsyncSession = Depends(get_session)):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")
    snapshots = (
        await db.execute(
            select(PriceSnapshot)
            .where(PriceSnapshot.watch_id == watch_id)
            .order_by(PriceSnapshot.captured_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return WatchDetail.model_validate({**watch.__dict__, "snapshots": snapshots})


@api.patch("/watches/{watch_id}", response_model=WatchOut)
async def update_watch(
    watch_id: int,
    body: WatchUpdate,
    auth: AuthDep,
    db: AsyncSession = Depends(get_session),
):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(watch, k, v)
    await db.commit()
    await db.refresh(watch)
    return watch


@api.delete("/watches/{watch_id}", status_code=204)
async def delete_watch(watch_id: int, auth: AuthDep, db: AsyncSession = Depends(get_session)):
    watch = await db.get(Watch, watch_id)
    if not watch:
        raise HTTPException(404, "Watch não encontrado")
    watch.active = False
    await db.commit()


@api.post("/watches/{watch_id}/check", response_model=CheckResult)
async def check_watch(
    watch_id: int,
    auth: AuthDep,
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
    return CheckResult(
        watch_id=watch.id,
        new_snapshots=len(snaps),
        cheapest=SnapshotOut.model_validate(cheapest) if cheapest else None,
    )


# Registra o router na app
app.include_router(api)

# ---------------------------------------------------------------------------
# Serve frontend SPA (Phase 7) — apenas se o build existir
# ---------------------------------------------------------------------------

_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="spa")
