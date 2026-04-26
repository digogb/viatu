"""Cliente HTTP do BFF do latamairlines.com.

Dois clientes disponíveis:

- `LatamClient`: curl_cffi com Chrome impersonation. Passa pelo Akamai mas
  ainda recebe 403 do backend por falta de captcha/search tokens. Mantido
  para calendar e testes futuros.

- `PlaywrightSearchClient`: subprocess que chama `app.playwright_search`.
  O browser real gera todos os tokens anti-bot automaticamente. Usar este
  nas tasks Celery.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import date
from uuid import uuid4

from curl_cffi.requests import AsyncSession, RequestsError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.cookie_store import as_httpx_dict, bff_headers
from app.schemas import CABIN_TO_LATAM, FareOption, SearchRequest

logger = logging.getLogger(__name__)


class LatamAuthError(Exception):
    """403/401 do BFF — cookies expiraram, precisa re-rodar primer."""


def _base_headers() -> dict[str, str]:
    s = get_settings()
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": s.latam_base_url,
        "Referer": f"{s.latam_base_url}/br/pt/oferta-voos",
    }


class LatamClient:
    def __init__(self) -> None:
        self._session_id = str(uuid4())
        s = get_settings()
        self._session = AsyncSession(
            impersonate="chrome",
            headers=_base_headers(),
            timeout=20,
        )

    async def aclose(self) -> None:
        await self._session.close()

    def _request_headers(self) -> dict[str, str]:
        return {
            **bff_headers(),
            "x-latam-app-session-id": self._session_id,
            "x-latam-request-id": str(uuid4()),
            "x-latam-track-id": str(uuid4()),
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RequestsError),
    )
    async def search(self, req: SearchRequest) -> list[FareOption]:
        s = get_settings()
        url = f"{s.latam_base_url}/bff/air-offers/v2/offers/search/redemption"
        params: dict[str, str | int] = {
            "redemption": "true",
            "sort": "RECOMMENDED",
            "cabinType": CABIN_TO_LATAM[req.cabin],
            "origin": req.origin.upper(),
            "destination": req.destination.upper(),
            "outFrom": req.departure.isoformat(),
            "adult": req.adults,
            "child": 0,
            "infant": 0,
            "locale": "pt-br",
            "outOfferId": "null",
            "inOfferId": "null",
            "outFlightDate": "null",
            "inFlightDate": "null",
        }
        if req.return_date:
            params["inFrom"] = req.return_date.isoformat()

        cookies = as_httpx_dict()
        headers = self._request_headers()
        logger.debug("search: %d cookies, %d bff-headers", len(cookies), len(headers))

        resp = await self._session.get(url, params=params, cookies=cookies, headers=headers)
        if resp.status_code in (401, 403):
            raise LatamAuthError(
                f"BFF retornou {resp.status_code}. Re-rode `python -m app.primer`."
            )
        if not resp.ok:
            logger.error("BFF %d body: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        return _parse_search(resp.json())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RequestsError),
    )
    async def calendar(
        self,
        origin: str,
        destination: str,
        month: int,
        year: int,
        round_trip: bool = False,
    ) -> dict:
        s = get_settings()
        url = f"{s.latam_base_url}/bff/air-offers/v2/calendar"
        resp = await self._session.get(
            url,
            params={
                "origin": origin.upper(),
                "destination": destination.upper(),
                "month": month,
                "year": year,
                "isRoundTrip": "true" if round_trip else "false",
            },
            cookies=as_httpx_dict(),
            headers=self._request_headers(),
        )
        if resp.status_code in (401, 403):
            raise LatamAuthError(f"BFF /calendar retornou {resp.status_code}.")
        resp.raise_for_status()
        return resp.json()


def _parse_search(payload: dict) -> list[FareOption]:
    options: list[FareOption] = []
    for itin in payload.get("content", []):
        summary = itin.get("summary", {})
        origin = summary.get("origin", {})
        destination = summary.get("destination", {})
        flight_code = summary.get("flightCode", "")
        duration = int(summary.get("duration") or 0)
        stops = int(summary.get("stopOvers") or 0)
        operators = summary.get("flightOperators", [])

        for brand in summary.get("brands", []):
            price = brand.get("price", {})
            taxes = brand.get("taxes", {})
            cabin_obj = brand.get("cabin", {})
            options.append(
                FareOption(
                    flight_number=flight_code,
                    departure_at=origin.get("departure", ""),
                    arrival_at=destination.get("arrival", ""),
                    duration_minutes=duration,
                    cabin=f"{cabin_obj.get('label', '')} / {brand.get('brandText', '')}",
                    points=int(price.get("amount", 0)),
                    taxes_brl=float(taxes.get("amount", 0)),
                    fare_brand=brand.get("brandText"),
                    stops=stops,
                    fare_basis=brand.get("farebasis"),
                    offer_id=brand.get("offerId"),
                    operators=operators,
                )
            )
    return options


def cheapest_per_brand(options: list[FareOption]) -> dict[str, FareOption]:
    """Para cada brand (LIGHT, STANDARD, ...), retorna a opção mais barata."""
    result: dict[str, FareOption] = {}
    for opt in options:
        brand = opt.fare_brand or "UNKNOWN"
        cur = result.get(brand)
        if cur is None or opt.points < cur.points:
            result[brand] = opt
    return result


# ---------------------------------------------------------------------------
# PlaywrightSearchClient
# ---------------------------------------------------------------------------

class PlaywrightSearchClient:
    """Busca via subprocess Playwright — o browser gera todos os tokens anti-bot.

    Chame a partir de contexto síncrono (task Celery). Nunca dentro de
    coroutine existente.
    """

    def search(self, req: SearchRequest, timeout: int = 90) -> list[FareOption]:
        """Executa playwright_search como subprocess e retorna FareOptions.

        Raises:
            LatamAuthError: se o subprocess retornar código de saída 1 com
                mensagem de auth (sessão expirada).
            RuntimeError: para qualquer outro erro do subprocess.
        """
        cmd = [
            sys.executable, "-m", "app.playwright_search",
            "--origin", req.origin,
            "--destination", req.destination,
            "--departure", req.departure.isoformat(),
            "--adults", str(req.adults),
            "--cabin", req.cabin,
        ]
        if req.return_date:
            cmd += ["--return-date", req.return_date.isoformat()]

        logger.info(
            "PlaywrightSearchClient: %s→%s %s",
            req.origin, req.destination, req.departure,
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.error("playwright_search falhou:\n%s", stderr)
            if "401" in stderr or "403" in stderr or "storage_state" in stderr.lower():
                raise LatamAuthError(f"playwright_search: {stderr}")
            raise RuntimeError(f"playwright_search exit {result.returncode}: {stderr}")

        raw = json.loads(result.stdout)
        options = [FareOption(**item) for item in raw]
        logger.info(
            "PlaywrightSearchClient: %d opções recebidas para %s→%s",
            len(options), req.origin, req.destination,
        )
        return options
