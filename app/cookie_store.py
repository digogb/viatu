"""Persistência de cookies do Akamai/LATAM em arquivo JSON."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


def _path() -> Path:
    return Path(get_settings().latam_cookies_path)


def save(cookies: list[dict[str, Any]]) -> None:
    _path().write_text(json.dumps(cookies, indent=2, ensure_ascii=False))


def load() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    return json.loads(p.read_text())


def as_httpx_dict() -> dict[str, str]:
    """Formato consumível pelo httpx.AsyncClient(cookies=...)."""
    return {c["name"]: c["value"] for c in load()}


def is_stale(max_age_hours: int = 6) -> bool:
    """Heurística simples: arquivo mais velho que X horas."""
    p = _path()
    if not p.exists():
        return True
    import time
    return (time.time() - p.stat().st_mtime) > max_age_hours * 3600
