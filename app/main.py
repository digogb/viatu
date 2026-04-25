"""API HTTP — busca on-demand e CRUD de watches (Fase 2)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException

from app.config import get_settings
from app.latam_client import LatamAuthError, LatamClient
from app.schemas import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cliente LATAM compartilhado entre requests (reaproveita conexão HTTP/2)
    app.state.latam = LatamClient()
    yield
    await app.state.latam.aclose()


app = FastAPI(title="Viatu", version="0.1.0", lifespan=lifespan)


def get_latam() -> LatamClient:
    return app.state.latam


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


# CRUD de watches será adicionado na Fase 2.
