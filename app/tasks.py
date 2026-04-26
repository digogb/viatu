"""Tasks Celery: sweep_active_watches, check_watch, reprime_cookies, notify."""
from __future__ import annotations

import asyncio
import logging
import random
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.celery_app import celery
from app.config import get_settings
from app.latam_client import LatamAuthError, PlaywrightSearchClient
from app.models import Alert, PriceSnapshot, SearchJob, Watch
from app.notifier import WhatsAppNotifier, build_deeplink, build_message
from app.schemas import SearchRequest

logger = logging.getLogger(__name__)


def _make_session_factory():
    """Engine com NullPool — seguro para asyncio.run() em tasks Celery."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False), engine


# ---------------------------------------------------------------------------
# sweep_active_watches
# ---------------------------------------------------------------------------

@celery.task(name="app.tasks.sweep_active_watches")
def sweep_active_watches() -> None:
    """Lista watches ativos e enfileira check_watch com jitter por índice."""
    watch_ids = asyncio.run(_list_active_watch_ids())
    logger.info("Sweep: %d watches ativos", len(watch_ids))
    for idx, watch_id in enumerate(watch_ids):
        jitter = random.randint(0, 60) + 5 * idx
        check_watch.apply_async((watch_id,), countdown=jitter)
        logger.debug("Agendado watch %d em %ds", watch_id, jitter)


async def _list_active_watch_ids() -> list[int]:
    factory, engine = _make_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(select(Watch.id).where(Watch.active.is_(True)))
            return list(result.scalars().all())
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# check_watch
# ---------------------------------------------------------------------------

@celery.task(name="app.tasks.check_watch", bind=True, max_retries=3, default_retry_delay=60)
def check_watch(self, watch_id: int) -> dict:
    try:
        # 1. Carrega watch do banco (async)
        watch = asyncio.run(_load_watch(watch_id))
        if watch is None:
            return {"watch_id": watch_id, "skipped": True}

        # 2. Busca via Playwright (sync — cria próprio event loop via subprocess)
        req = SearchRequest(
            origin=watch["origin"],
            destination=watch["destination"],
            departure=date.fromisoformat(watch["departure"]),
            return_date=date.fromisoformat(watch["return_date"]) if watch["return_date"] else None,
            adults=watch["adults"],
            cabin=watch["cabin"],
        )
        client = PlaywrightSearchClient()
        options = client.search(req)

        # 3. Grava snapshots e decide notificação (async)
        return asyncio.run(_save_and_notify(watch_id, watch, options))

    except LatamAuthError:
        logger.warning("Auth error no watch %d — disparando reprime_cookies", watch_id)
        reprime_cookies.delay()
        raise self.retry(countdown=120)
    except Exception as exc:
        logger.exception("Erro no watch %d", watch_id)
        raise self.retry(exc=exc, countdown=30)


async def _load_watch(watch_id: int) -> dict | None:
    factory, engine = _make_session_factory()
    try:
        async with factory() as session:
            watch = await session.get(Watch, watch_id)
            if not watch or not watch.active:
                logger.info("Watch %d inativo ou não encontrado, ignorando", watch_id)
                return None
            return {
                "id": watch.id,
                "origin": watch.origin,
                "destination": watch.destination,
                "departure": watch.departure.isoformat(),
                "return_date": watch.return_date.isoformat() if watch.return_date else None,
                "adults": watch.adults,
                "cabin": watch.cabin,
                "max_points": watch.max_points,
                "only_direct": watch.only_direct,
                "notify_phone": watch.notify_phone,
            }
    finally:
        await engine.dispose()


async def _save_and_notify(watch_id: int, watch: dict, options: list) -> dict:
    factory, engine = _make_session_factory()
    try:
        async with factory() as session:
            now = datetime.now(UTC)
            one_min_ago = now - timedelta(minutes=1)
            new_count = 0

            for opt in options:
                dep_at = datetime.fromisoformat(opt.departure_at) if opt.departure_at else None

                already = await session.scalar(
                    select(PriceSnapshot.id).where(
                        and_(
                            PriceSnapshot.watch_id == watch_id,
                            PriceSnapshot.flight_number == opt.flight_number,
                            PriceSnapshot.fare_basis == opt.fare_basis,
                            PriceSnapshot.departure_at == dep_at,
                            PriceSnapshot.captured_at >= one_min_ago,
                        )
                    ).limit(1)
                )
                if already:
                    continue

                session.add(PriceSnapshot(
                    watch_id=watch_id,
                    flight_number=opt.flight_number,
                    stops=opt.stops,
                    departure_at=dep_at,
                    arrival_at=datetime.fromisoformat(opt.arrival_at) if opt.arrival_at else None,
                    duration_minutes=opt.duration_minutes,
                    fare_brand=opt.fare_brand or "UNKNOWN",
                    fare_basis=opt.fare_basis,
                    cabin=opt.cabin,
                    points=opt.points,
                    taxes_brl=opt.taxes_brl,
                    captured_at=now,
                ))
                new_count += 1

            await session.commit()

            max_points = watch.get("max_points")
            if max_points and new_count > 0:
                light = min(
                    (o for o in options if o.stops <= 1 and (o.fare_brand or "").upper() == "LIGHT"),
                    key=lambda o: o.points,
                    default=None,
                )
                if light and light.points <= max_points:
                    dep_at = datetime.fromisoformat(light.departure_at) if light.departure_at else None
                    snap_id = await session.scalar(
                        select(PriceSnapshot.id).where(
                            and_(
                                PriceSnapshot.watch_id == watch_id,
                                PriceSnapshot.flight_number == light.flight_number,
                                PriceSnapshot.fare_basis == light.fare_basis,
                                PriceSnapshot.departure_at == dep_at,
                                PriceSnapshot.captured_at >= one_min_ago,
                            )
                        ).limit(1)
                    )
                    if snap_id:
                        notify.delay(watch_id, snap_id)

            logger.info("check_watch %d: %d novos snapshots", watch_id, new_count)
            return {"watch_id": watch_id, "new_snapshots": new_count}
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# reprime_cookies
# ---------------------------------------------------------------------------

@celery.task(name="app.tasks.reprime_cookies")
def reprime_cookies() -> None:
    """Renova cookies do Akamai rodando o primer em subprocess isolado."""
    logger.info("Iniciando reprime_cookies...")
    result = subprocess.run(
        [sys.executable, "-m", "app.primer"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        logger.error("primer falhou (code %d): %s", result.returncode, result.stderr[:300])
        raise RuntimeError(f"primer falhou: {result.stderr[:200]}")
    logger.info("reprime_cookies OK: %s", result.stdout.strip())


# ---------------------------------------------------------------------------
# notify
# ---------------------------------------------------------------------------

@celery.task(name="app.tasks.notify")
def notify(watch_id: int, snapshot_id: int) -> None:
    asyncio.run(_notify_async(watch_id, snapshot_id))


async def _notify_async(watch_id: int, snapshot_id: int) -> None:
    factory, engine = _make_session_factory()
    try:
        async with factory() as session:
            watch = await session.get(Watch, watch_id)
            snapshot = await session.get(PriceSnapshot, snapshot_id)

            if not watch or not snapshot:
                logger.warning("notify: watch %d ou snapshot %d não encontrado", watch_id, snapshot_id)
                return

            # Anti-spam: não envia se já alertou nas últimas N horas com preço >= atual
            if not await _should_notify(session, watch_id, snapshot.points):
                logger.info("notify: watch %d suprimido por cooldown", watch_id)
                return

            deeplink = build_deeplink(
                origin=watch.origin,
                destination=watch.destination,
                departure_at=snapshot.departure_at,
                adults=watch.adults,
                cabin=watch.cabin,
                return_date=watch.return_date,
            )
            message = build_message(watch, snapshot, deeplink)

            # Loga sempre — útil para testar sem Evolution configurada
            logger.info("notify: mensagem para watch %d:\n%s", watch_id, message)

            evolution_configured = bool(get_settings().evolution_base_url and watch.notify_phone)
            if not evolution_configured:
                logger.info(
                    "notify: Evolution API não configurada ou notify_phone ausente — dry run"
                )
                return

            notifier = WhatsAppNotifier()
            success = await notifier.send(watch.notify_phone, message)

            session.add(Alert(
                watch_id=watch_id,
                snapshot_id=snapshot_id,
                channel="whatsapp",
                sent_at=datetime.now(UTC),
                success=success,
            ))
            await session.commit()

            logger.info("notify: watch %d snapshot %d — enviado=%s", watch_id, snapshot_id, success)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# run_search_job
# ---------------------------------------------------------------------------

@celery.task(name="app.tasks.run_search_job", bind=True, max_retries=0)
def run_search_job(self, job_id: int) -> None:
    """Executa job de busca em range — atualiza progresso e armazena resultado."""
    job_params = asyncio.run(_start_job(job_id))
    if job_params is None:
        return

    dates_str: list[str] = job_params.get("dates", [])
    dates = [date.fromisoformat(d) for d in dates_str]
    total = len(dates)

    client = PlaywrightSearchClient()
    results = []

    for idx, dep_date in enumerate(dates):
        req = SearchRequest(
            origin=job_params["origin"],
            destination=job_params["destination"],
            departure=dep_date,
            return_date=date.fromisoformat(job_params["return_date"]) if job_params.get("return_date") else None,
            adults=job_params.get("adults", 1),
            cabin=job_params.get("cabin", "Y"),
        )
        try:
            options = client.search(req)
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
            logger.warning("run_search_job %d: falhou para %s: %s", job_id, dep_date, exc)
            results.append({"date": dep_date.isoformat(), "error": str(exc)})

        asyncio.run(_update_job_progress(job_id, int((idx + 1) / total * 100)))

    asyncio.run(_finish_job(job_id, results))


async def _start_job(job_id: int) -> dict | None:
    factory, engine = _make_session_factory()
    try:
        async with factory() as session:
            job = await session.get(SearchJob, job_id)
            if not job:
                return None
            job.status = "running"
            await session.commit()
            return dict(job.params)
    finally:
        await engine.dispose()


async def _update_job_progress(job_id: int, progress: int) -> None:
    factory, engine = _make_session_factory()
    try:
        async with factory() as session:
            job = await session.get(SearchJob, job_id)
            if job:
                job.progress = progress
                await session.commit()
    finally:
        await engine.dispose()


async def _finish_job(job_id: int, results: list) -> None:
    factory, engine = _make_session_factory()
    try:
        async with factory() as session:
            job = await session.get(SearchJob, job_id)
            if job:
                job.status = "done"
                job.progress = 100
                job.result = {"results": results}
                await session.commit()
    finally:
        await engine.dispose()


async def _should_notify(session, watch_id: int, current_points: int) -> bool:
    cooldown = get_settings().alert_cooldown_hours
    cutoff = datetime.now(UTC) - timedelta(hours=cooldown)

    recent = await session.scalar(
        select(Alert)
        .where(
            and_(
                Alert.watch_id == watch_id,
                Alert.sent_at >= cutoff,
                Alert.success.is_(True),
            )
        )
        .order_by(Alert.sent_at.desc())
        .limit(1)
    )
    if recent is None:
        return True

    # Envia somente se o preço caiu mais do que no último alerta
    last_points = await session.scalar(
        select(PriceSnapshot.points).where(PriceSnapshot.id == recent.snapshot_id)
    )
    return last_points is not None and current_points < last_points
