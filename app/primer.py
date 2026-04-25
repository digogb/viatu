"""Primer: abre uma busca real no latamairlines.com com Playwright e
extrai os cookies do Akamai Bot Manager (_abck, bm_sv, bm_sz, ...) que
o cliente httpx vai reusar.

Uso:
    uv run python -m app.primer

Roda como subprocess a partir do worker quando os cookies expiram.
Não chame este módulo dentro de um event loop existente.
"""
from __future__ import annotations

import asyncio
import logging

from playwright.async_api import async_playwright

from app.config import get_settings
from app.cookie_store import save

logger = logging.getLogger(__name__)

# URL canônica de busca: economy, OW, com toggle de pontos ligado.
# Usamos uma rota estável (FOR-GRU) para o priming — só precisamos que
# os cookies sejam emitidos, não importa qual data.
PRIMER_URL = (
    "https://www.latamairlines.com/br/pt/oferta-voos"
    "?origin=FOR&destination=GRU"
    "&outbound=2026-12-15T15%3A00%3A00.000Z"
    "&adt=1&chd=0&inf=0"
    "&trip=OW&cabin=Economy"
    "&redemption=true&sort=RECOMMENDED"
)


async def prime() -> int:
    settings = get_settings()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.primer_headless)
        ctx = await browser.new_context(
            locale="pt-BR",
            user_agent=settings.latam_user_agent,
            viewport={"width": 1366, "height": 900},
        )
        page = await ctx.new_page()
        try:
            await page.goto(
                PRIMER_URL,
                wait_until="networkidle",
                timeout=settings.primer_timeout_ms,
            )
            # Espera os resultados começarem a renderizar — confirma que
            # passou pelo desafio do Akamai. Ajuste o seletor se mudar.
            await page.wait_for_selector(
                '[data-testid*="flight"], [class*="flight-card"]',
                timeout=settings.primer_timeout_ms,
            )
        finally:
            cookies = await ctx.cookies("https://www.latamairlines.com")
            save(cookies)
            await browser.close()

        logger.info("Primer salvou %d cookies", len(cookies))
        return len(cookies)


def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    n = asyncio.run(prime())
    if n < 5:
        raise SystemExit(f"Primer só capturou {n} cookies — esperado >= 5")
    print(f"OK — {n} cookies salvos.")


if __name__ == "__main__":
    main()
