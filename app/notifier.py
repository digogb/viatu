"""Notificações WhatsApp via Evolution API."""
from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_CABIN_LABEL = {"Y": "Economy", "W": "PremiumEconomy", "J": "Business", "F": "First"}


def _fmt_points(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}min"


def _fmt_stops(stops: int) -> str:
    if stops == 0:
        return "direto"
    return "1 conexão" if stops == 1 else f"{stops} conexões"


def build_deeplink(
    origin: str,
    destination: str,
    departure_at: datetime | None,
    adults: int,
    cabin: str,
    return_date=None,
) -> str:
    outbound = departure_at.strftime("%Y-%m-%dT%H:%M:%S.000Z") if departure_at else ""
    params: dict = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "outbound": outbound,
        "adt": adults,
        "chd": 0,
        "inf": 0,
        "trip": "RT" if return_date else "OW",
        "cabin": _CABIN_LABEL.get(cabin, "Economy"),
        "redemption": "true",
        "sort": "RECOMMENDED",
    }
    return f"https://www.latamairlines.com/br/pt/oferta-voos?{urlencode(params)}"


def build_message(watch, snapshot, deeplink: str) -> str:
    dep_date = (
        snapshot.departure_at.strftime("%d/%m/%Y")
        if snapshot.departure_at
        else str(watch.departure)
    )
    dep_time = snapshot.departure_at.strftime("%H:%M") if snapshot.departure_at else "—"
    duration = _fmt_duration(snapshot.duration_minutes) if snapshot.duration_minutes else "—"
    threshold = _fmt_points(watch.max_points) if watch.max_points else "—"

    return (
        f"✈️ *Queda de preço LATAM*\n\n"
        f"{watch.origin} → {watch.destination} em {dep_date}\n\n"
        f"💰 *{_fmt_points(snapshot.points)} milhas* + R$ {snapshot.taxes_brl:.2f} ({snapshot.fare_brand})\n"
        f"🛫 {snapshot.flight_number} às {dep_time} — {_fmt_stops(snapshot.stops)}\n"
        f"⏱️ {duration}\n\n"
        f"Limite definido: {threshold} milhas\n"
        f"Reservar: {deeplink}"
    )


class WhatsAppNotifier:
    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.evolution_base_url.rstrip("/")
        self._instance = s.evolution_instance
        self._api_key = s.evolution_api_key

    async def send(self, phone: str, message: str) -> bool:
        url = f"{self._base_url}/message/sendText/{self._instance}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    url,
                    headers={"apikey": self._api_key},
                    json={"number": phone, "text": message},
                )
            except httpx.HTTPError as exc:
                logger.error("Erro HTTP ao enviar WhatsApp: %s", exc)
                return False

        if resp.status_code != 200:
            logger.error("Evolution API retornou %d: %s", resp.status_code, resp.text[:200])
            return False

        body = resp.json()
        # Evolution às vezes retorna 200 com erro no body — validar presença de 'key'
        if "key" not in body:
            logger.error("Evolution API sem 'key' na resposta: %s", body)
            return False

        return True
