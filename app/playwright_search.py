"""Busca via Playwright — intercepta a response do BFF enquanto o browser navega.

Chamado como subprocess pelo worker (nunca dentro de coroutine existente).

Uso:
    uv run python -m app.playwright_search \\
        --origin FOR --destination GRU --departure 2026-06-21 \\
        [--return-date 2026-06-26] [--adults 1] [--cabin Y]

Saída: JSON no stdout com lista de FareOption.
Exit 1 + mensagem no stderr em caso de erro.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date

from playwright.async_api import Response, async_playwright
from playwright_stealth import StealthConfig, stealth_async

from app.config import get_settings
from app.cookie_store import load_storage_state, save
from app.latam_client import _parse_search

logger = logging.getLogger(__name__)

CABIN_MAP = {"Y": "Economy", "C": "Business", "W": "PremiumEconomy", "F": "First"}

BFF_SEARCH_PATH = "/bff/air-offers/v2/offers/search/redemption"


def _build_url(origin: str, dest: str, departure: date, return_date: date | None,
               adults: int, cabin: str) -> str:
    s = get_settings()
    dep_str = f"{departure.isoformat()}T00:00:00.000Z"
    trip = "RT" if return_date else "OW"
    cabin_str = CABIN_MAP.get(cabin, "Economy")
    url = (
        f"{s.latam_base_url}/br/pt/oferta-voos"
        f"?origin={origin.upper()}"
        f"&outbound={dep_str}"
        f"&destination={dest.upper()}"
        f"&adt={adults}&chd=0&inf=0"
        f"&trip={trip}"
        f"&cabin={cabin_str}"
        f"&redemption=true"
        f"&sort=RECOMMENDED"
    )
    if return_date:
        url += f"&inbound={return_date.isoformat()}T00:00:00.000Z"
    return url


async def _search(
    origin: str,
    dest: str,
    departure: date,
    return_date: date | None,
    adults: int,
    cabin: str,
) -> list[dict]:
    settings = get_settings()
    state = load_storage_state()
    if state is None:
        raise RuntimeError("Sem storage_state. Rode: uv run python -m app.primer --init")

    url = _build_url(origin, dest, departure, return_date, adults, cabin)
    logger.info("playwright_search: navegando para %s", url[:120])

    captured: asyncio.Future[dict] = asyncio.get_event_loop().create_future()

    async def on_response(response: Response) -> None:
        logger.debug("Response: %d %s", response.status, response.url[:100])
        if BFF_SEARCH_PATH in response.url and not captured.done():
            logger.info("BFF response encontrada: %d %s", response.status, response.url[:100])
            try:
                body = await response.json()
                captured.set_result(body)
            except Exception as exc:
                if not captured.done():
                    captured.set_exception(exc)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=settings.primer_headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = await browser.new_context(
            locale="pt-BR",
            user_agent=settings.latam_user_agent,
            viewport={"width": 1366, "height": 900},
            storage_state=state,
        )
        ctx.on("response", on_response)
        page = await ctx.new_page()
        await stealth_async(page, StealthConfig(
            nav_user_agent=settings.latam_user_agent,
            nav_platform="Win32",
            languages=("pt-BR", "pt", "en-US", "en"),
        ))

        try:
            logger.info("Navegando para URL de busca...")
            await page.goto(url, wait_until="load", timeout=settings.primer_timeout_ms)
            logger.info("Página carregada: %s", page.url[:120])

            # Aguarda a BFF response aparecer (browser faz a chamada automaticamente)
            try:
                payload = await asyncio.wait_for(captured, timeout=30)
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"BFF response não capturada em 30s. URL final: {page.url[:120]}\n"
                    "Possível causa: sessão expirada ou página redirecionou para login."
                )

            # Atualiza cookies após a navegação (renova bm_sv, _xp_session, etc)
            cookies = await ctx.cookies("https://www.latamairlines.com")
            save(cookies)
            logger.info("playwright_search: %d cookies atualizados", len(cookies))

        finally:
            await browser.close()

    options = _parse_search(payload)
    return [o.model_dump() for o in options]


def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Busca LATAM via Playwright")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--departure", required=True, help="YYYY-MM-DD")
    parser.add_argument("--return-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--cabin", default="Y")
    args = parser.parse_args()

    departure = date.fromisoformat(args.departure)
    return_date = date.fromisoformat(args.return_date) if args.return_date else None

    try:
        result = asyncio.run(_search(
            origin=args.origin,
            dest=args.destination,
            departure=departure,
            return_date=return_date,
            adults=args.adults,
            cabin=args.cabin,
        ))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
