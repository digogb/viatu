"""Testes do WhatsAppNotifier e helpers de mensagem."""
from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
import respx

from app.notifier import WhatsAppNotifier, build_deeplink, build_message


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setenv("EVOLUTION_BASE_URL", "https://evo.test")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "viatu-test")
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-key")
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# WhatsAppNotifier.send
# ---------------------------------------------------------------------------

@respx.mock
async def test_send_success():
    respx.post("https://evo.test/message/sendText/viatu-test").mock(
        return_value=httpx.Response(200, json={"key": {"id": "BAE5abc"}, "status": "PENDING"})
    )
    notifier = WhatsAppNotifier()
    ok = await notifier.send("+5585999999999", "mensagem de teste")

    assert ok is True
    req = respx.calls.last.request
    assert req.headers["apikey"] == "test-key"
    body = json.loads(req.content)
    assert body["number"] == "+5585999999999"
    assert body["text"] == "mensagem de teste"


@respx.mock
async def test_send_evolution_error_in_body():
    # Evolution retorna 200 mas sem 'key' — indicativo de erro
    respx.post("https://evo.test/message/sendText/viatu-test").mock(
        return_value=httpx.Response(200, json={"error": "instance not connected"})
    )
    notifier = WhatsAppNotifier()
    ok = await notifier.send("+5585999999999", "teste")
    assert ok is False


@respx.mock
async def test_send_http_500():
    respx.post("https://evo.test/message/sendText/viatu-test").mock(
        return_value=httpx.Response(500)
    )
    notifier = WhatsAppNotifier()
    ok = await notifier.send("+5585999999999", "teste")
    assert ok is False


@respx.mock
async def test_send_network_error():
    respx.post("https://evo.test/message/sendText/viatu-test").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    notifier = WhatsAppNotifier()
    ok = await notifier.send("+5585999999999", "teste")
    assert ok is False


# ---------------------------------------------------------------------------
# build_deeplink
# ---------------------------------------------------------------------------

def test_build_deeplink_ow():
    dep = datetime(2026, 6, 21, 6, 0, 0)
    link = build_deeplink("FOR", "IGU", dep, adults=1, cabin="Y")
    assert "origin=FOR" in link
    assert "destination=IGU" in link
    assert "redemption=true" in link
    assert "trip=OW" in link
    assert "2026-06-21" in link
    assert "cabin=Economy" in link


def test_build_deeplink_rt():
    from datetime import date
    dep = datetime(2026, 6, 21, 6, 0, 0)
    link = build_deeplink("FOR", "IGU", dep, adults=2, cabin="Y", return_date=date(2026, 6, 26))
    assert "trip=RT" in link
    assert "adt=2" in link


# ---------------------------------------------------------------------------
# build_message
# ---------------------------------------------------------------------------

def test_build_message_format():
    from types import SimpleNamespace
    from datetime import date

    watch = SimpleNamespace(
        origin="FOR", destination="IGU",
        departure=date(2026, 6, 21),
        max_points=25000, adults=1, cabin="Y", return_date=None,
    )
    snapshot = SimpleNamespace(
        flight_number="LA3253",
        departure_at=datetime(2026, 6, 21, 6, 0, 0),
        arrival_at=datetime(2026, 6, 21, 14, 5, 0),
        duration_minutes=485,
        fare_brand="LIGHT",
        points=22666,
        taxes_brl=56.88,
        stops=1,
    )
    msg = build_message(watch, snapshot, "https://latam.example/link")

    assert "22.666 milhas" in msg
    assert "R$ 56.88" in msg or "R$ 56,88" in msg
    assert "LA3253" in msg
    assert "21/06/2026" in msg
    assert "8h05min" in msg
    assert "25.000 milhas" in msg
    assert "1 conexão" in msg
