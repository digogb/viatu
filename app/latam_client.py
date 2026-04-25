"""Cliente HTTP do BFF do latamairlines.com.

Endpoints:
- GET /bff/air-offers/v2/offers/search/redemption — busca de tarifas em pontos
- GET /bff/air-offers/v2/calendar — heatmap de preços do mês
"""
from __future__ import annotations

import logging
from datetime import date

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.cookie_store import as_httpx_dict
from app.schemas import CABIN_TO_LATAM, FareOption, SearchRequest

logger = logging.getLogger(__name__)


class LatamAuthError(Exception):
    """403/401 do BFF — cookies expiraram, precisa re-rodar primer."""


def _base_headers() -> dict[str, str]:
    s = get_settings()
    return {
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Origin": s.latam_base_url,
        "Referer": f"{s.latam_base_url}/br/pt/oferta-voos",
        "User-Agent": s.latam_user_agent,
        # Headers x-latam-* ainda não confirmados como obrigatórios.
        # Se ocorrer 403 mesmo com cookies válidos, capturar do DevTools
        # e adicionar aqui.
    }


class LatamClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owned = client is None
        self._client = client or httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers=_base_headers(),
            cookies=as_httpx_dict(),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        if self._owned:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
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

        resp = await self._client.get(url, params=params)
        if resp.status_code in (401, 403):
            raise LatamAuthError(
                f"BFF retornou {resp.status_code}. Re-rode `python -m app.primer`."
            )
        resp.raise_for_status()
        return _parse_search(resp.json())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
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
        resp = await self._client.get(
            url,
            params={
                "origin": origin.upper(),
                "destination": destination.upper(),
                "month": month,
                "year": year,
                "isRoundTrip": "true" if round_trip else "false",
            },
        )
        if resp.status_code in (401, 403):
            raise LatamAuthError(f"BFF /calendar retornou {resp.status_code}.")
        resp.raise_for_status()
        return resp.json()


def _parse_search(payload: dict) -> list[FareOption]:
    """Parser baseado no shape real confirmado em docs/sample-response.json.

    Estrutura:
      content[].summary.{
        flightCode, duration, stopOvers,
        origin{departure, iataCode, ...},
        destination{arrival, iataCode, ...},
        brands[ {price{amount, currency}, taxes{amount}, farebasis, offerId, ...} ],
        flightOperators: [str],
      }
    """
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
