"""Smoke tests do CRUD de watches usando SQLite in-memory."""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import PriceSnapshot, Watch


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def test_create_watch(db: AsyncSession):
    watch = Watch(origin="FOR", destination="IGU", departure=date(2026, 6, 21), max_points=25000)
    db.add(watch)
    await db.commit()
    await db.refresh(watch)

    assert watch.id is not None
    assert watch.active is True
    assert watch.interval_minutes == 30
    assert watch.only_direct is True


async def test_soft_delete_watch(db: AsyncSession):
    watch = Watch(origin="FOR", destination="GRU", departure=date(2026, 6, 21))
    db.add(watch)
    await db.commit()

    watch.active = False
    await db.commit()
    await db.refresh(watch)

    assert watch.active is False


async def test_price_snapshot_append_only(db: AsyncSession):
    from datetime import UTC, datetime

    watch = Watch(origin="FOR", destination="IGU", departure=date(2026, 6, 21))
    db.add(watch)
    await db.commit()

    now = datetime.now(UTC)
    for points in [22666, 25450]:
        snap = PriceSnapshot(
            watch_id=watch.id,
            flight_number="LA3253",
            fare_brand="LIGHT" if points == 22666 else "STANDARD",
            cabin="Economy / LIGHT",
            points=points,
            taxes_brl=56.88,
            captured_at=now,
        )
        db.add(snap)
    await db.commit()

    from sqlalchemy import func, select

    count = await db.scalar(
        select(func.count()).where(PriceSnapshot.watch_id == watch.id)
    )
    assert count == 2


async def test_update_watch_fields(db: AsyncSession):
    watch = Watch(origin="FOR", destination="IGU", departure=date(2026, 6, 21))
    db.add(watch)
    await db.commit()

    watch.max_points = 20000
    watch.notify_phone = "+5585999999999"
    await db.commit()
    await db.refresh(watch)

    assert watch.max_points == 20000
    assert watch.notify_phone == "+5585999999999"
