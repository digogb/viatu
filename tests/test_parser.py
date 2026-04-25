"""Teste do parser contra a resposta real do BFF."""
from __future__ import annotations

import json
from pathlib import Path

from app.latam_client import _parse_search, cheapest_per_brand


def test_parse_real_response():
    sample = json.loads(Path("docs/sample-response.json").read_text())
    options = _parse_search(sample)

    assert len(options) == 4  # 1 itinerário × 4 brands
    light = next(o for o in options if o.fare_brand == "LIGHT")
    assert light.points == 22666
    assert light.taxes_brl == 56.88
    assert light.flight_number == "LA3253"
    assert light.stops == 1
    assert light.fare_basis == "QLKX0V1"
    assert "LATAM Airlines Brasil" in light.operators


def test_cheapest_per_brand():
    sample = json.loads(Path("docs/sample-response.json").read_text())
    options = _parse_search(sample)
    by_brand = cheapest_per_brand(options)

    assert by_brand["LIGHT"].points == 22666
    assert by_brand["STANDARD"].points == 25450
    assert by_brand["FULL"].points == 26857
    assert by_brand["PREMIUM ECONOMY"].points == 33591
