"""Primer: gerencia a sessão Playwright autenticada na LATAM.

Dois modos:

- `--init`: login inicial. Abre o browser visível (headed), você loga
  manualmente, o script salva o storage_state completo (cookies + localStorage
  + sessionStorage). Roda 1× por sessão (semanas/meses, dependendo do refresh
  token da LATAM).

- (padrão, sem flag): warm-up. Carrega o storage_state salvo, navega na home
  da LATAM por alguns segundos pro site renovar cookies de sessão via refresh
  token, salva os cookies atualizados pro httpx consumir. Chamado pelo worker
  periodicamente e quando der 401/403.

Em ambos os modos:
- `playwright_stealth.stealth_async` é aplicado em cada página pra reduzir
  detecção pelo Akamai
- BFF headers (`x-latam-*`) são interceptados e salvos em `.latam_bff_headers.json`
- Cookies são salvos em `.latam_cookies.json` (formato consumido pelo httpx)
- Storage state completo salvo em `.latam_storage.json` (só pro warm-up)

Uso:
    uv run python -m app.primer --init   # 1ª vez ou quando expirar
    uv run python -m app.primer          # warm-up (usado pelo worker)

Roda como subprocess. Não chame dentro de um event loop existente.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from playwright.async_api import BrowserContext, Page, async_playwright
from playwright_stealth import StealthConfig, stealth_async

from app.config import get_settings
from app.cookie_store import (
    has_storage_state,
    load,
    load_storage_state,
    save,
    save_bff_headers,
    save_storage_state,
)

logger = logging.getLogger(__name__)

HOMEPAGE = "https://www.latamairlines.com/br/pt"
LOGIN_URL = "https://www.latamairlines.com/br/pt/login"

# Search em milhas (precisa estar logado pra retornar pricing em LOYALTY_POINTS).
# Usado no fim do --init pra disparar uma chamada BFF autenticada e capturar
# headers x-latam-*.
SEARCH_MILES_URL = (
    "https://www.latamairlines.com/br/pt/oferta-voos"
    "?origin=FOR&destination=GRU"
    "&outbound=2026-12-15T15%3A00%3A00.000Z"
    "&adt=1&chd=0&inf=0&trip=OW&cabin=Economy"
    "&redemption=true&sort=RECOMMENDED"
)

# Cookies que a LATAM emite após autenticação bem-sucedida
_AUTH_COOKIE_HINTS = {"JWTTOKEN", "mbox", "at_check"}


def _stealth_config() -> StealthConfig:
    s = get_settings()
    return StealthConfig(
        nav_user_agent=s.latam_user_agent,
        nav_platform="Win32",
        languages=("pt-BR", "pt", "en-US", "en"),
    )


async def _is_logged_in(ctx: BrowserContext) -> bool:
    cookies = await ctx.cookies("https://www.latamairlines.com")
    names = {c["name"] for c in cookies}
    return bool(_AUTH_COOKIE_HINTS & names)


async def _accept_cookie_banner(page: Page) -> None:
    try:
        await page.get_by_role("button", name="Aceite todos os cookies").click(timeout=4000)
        logger.info("Primer: banner de cookies aceito")
        await page.wait_for_timeout(1000)
    except Exception:
        pass


async def _wait_for_manual_login(page: Page) -> bool:
    """Abre o login e aguarda o usuário pressionar ENTER no terminal."""
    settings = get_settings()
    await page.goto(LOGIN_URL, wait_until="load", timeout=settings.primer_timeout_ms)

    print()
    print("=" * 64)
    print("  LOGIN MANUAL — faça login no browser que abriu")
    print("=" * 64)
    print("  1. Preencha CPF/e-mail, senha e qualquer 2FA")
    print("  2. Aguarde aparecer a home/dashboard com seu nome no topo")
    print("  3. Volte AQUI no terminal e pressione ENTER")
    print()
    print("  Importante: NÃO pressione ENTER antes de estar logado.")
    print("=" * 64)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "\n>>> ENTER após login completo: ")

    logged = await _is_logged_in(page.context)
    logger.info("Primer: login manual confirmado — autenticado=%s (URL=%s)", logged, page.url[:80])
    return logged


async def _setup_bff_capture(ctx: BrowserContext) -> dict[str, str]:
    captured: dict[str, str] = {}

    async def _on_request(request):
        if "/bff/" in request.url and "/air-offers/" in request.url and not captured:
            for k, v in request.headers.items():
                lk = k.lower()
                if lk.startswith("x-latam-") or lk in ("x-request-id", "x-b3-traceid"):
                    captured[k] = v
            if captured:
                logger.info("BFF headers capturados: %s", list(captured.keys()))

    ctx.on("request", _on_request)
    return captured


async def _persist(ctx: BrowserContext, captured_headers: dict[str, str]) -> int:
    cookies = await ctx.cookies("https://www.latamairlines.com")
    save(cookies)
    state = await ctx.storage_state()
    save_storage_state(state)
    if captured_headers:
        save_bff_headers(captured_headers)
        logger.info("BFF headers salvos: %s", list(captured_headers.keys()))
    return len(cookies)


# ---------------------------------------------------------------------------
# Modo --init: login inicial
# ---------------------------------------------------------------------------

async def init_session() -> int:
    """Abre browser headed pra você logar. Salva storage_state ao final."""
    settings = get_settings()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
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
        )
        captured = await _setup_bff_capture(ctx)
        page = await ctx.new_page()
        await stealth_async(page, _stealth_config())

        try:
            logger.info("Primer init: carregando homepage...")
            await page.goto(HOMEPAGE, wait_until="load", timeout=settings.primer_timeout_ms)
            await page.wait_for_timeout(2000)
            await _accept_cookie_banner(page)

            logged = await _wait_for_manual_login(page)
            if not logged:
                logger.warning("Primer init: cookies de auth NÃO detectados. Salvando estado mesmo assim.")

            # Dispara busca em milhas pra capturar BFF headers autenticados
            if logged:
                logger.info("Primer init: validando com busca em milhas...")
                await page.goto(SEARCH_MILES_URL, wait_until="load", timeout=settings.primer_timeout_ms)
                await page.wait_for_timeout(8000)

            return await _persist(ctx, captured)
        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# Modo padrão: warm-up usando storage_state
# ---------------------------------------------------------------------------

async def warmup() -> int:
    """Restaura storage_state e navega rapidamente pra renovar cookies."""
    settings = get_settings()
    state = load_storage_state()
    if state is None:
        raise RuntimeError(
            "Sem storage_state salvo. Rode primeiro: uv run python -m app.primer --init"
        )

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
        captured = await _setup_bff_capture(ctx)
        page = await ctx.new_page()
        await stealth_async(page, _stealth_config())

        try:
            logger.info("Primer warmup: navegando na home pra renovar tokens...")
            await page.goto(HOMEPAGE, wait_until="load", timeout=settings.primer_timeout_ms)
            await page.wait_for_timeout(5000)

            # Toca uma busca em milhas pra confirmar auth ainda válida
            logger.info("Primer warmup: validando sessão com busca em milhas...")
            await page.goto(SEARCH_MILES_URL, wait_until="load", timeout=settings.primer_timeout_ms)
            await page.wait_for_timeout(6000)

            logged = await _is_logged_in(ctx)
            if not logged:
                logger.warning(
                    "Primer warmup: sessão expirou. Rode `python -m app.primer --init` pra relogar."
                )

            return await _persist(ctx, captured)
        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if "--init" in sys.argv:
        n = asyncio.run(init_session())
    else:
        if not has_storage_state():
            print("Sem storage_state. Use: uv run python -m app.primer --init", file=sys.stderr)
            sys.exit(1)
        n = asyncio.run(warmup())

    cookie_names = {c["name"] for c in load()}
    has_abck = "_abck" in cookie_names
    has_auth = bool(_AUTH_COOKIE_HINTS & cookie_names)

    if n < 5 or not has_abck:
        raise SystemExit(
            f"Primer salvou apenas {n} cookies — falta _abck.\n"
            "Akamai pode ter detectado automação. Tente --init em outro IP/momento."
        )
    print(
        f"OK — {n} cookies salvos "
        f"(anti-bot={'sim' if has_abck else 'não'}, auth={'sim' if has_auth else 'não'})."
    )


if __name__ == "__main__":
    main()
