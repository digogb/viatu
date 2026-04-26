"""Persistência de cookies + storage state (Playwright) da LATAM.

Dois formatos coexistem:

- `.latam_cookies.json` — lista de cookies (formato Playwright `BrowserContext.cookies()`).
  É o que o cliente httpx consome diretamente via `as_httpx_dict()`.

- `.latam_storage.json` — `BrowserContext.storage_state()` completo. Inclui
  cookies + localStorage + sessionStorage. Necessário para reabrir uma sessão
  autenticada com refresh tokens válidos no warm-up periódico.

O primer salva os dois. O cliente httpx usa só os cookies; o warm-up do worker
restaura o storage_state pra renovar a sessão.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.config import get_settings


def _cookies_path() -> Path:
    return Path(get_settings().latam_cookies_path)


def _storage_path() -> Path:
    return _cookies_path().parent / ".latam_storage.json"


def _bff_headers_path() -> Path:
    return _cookies_path().parent / ".latam_bff_headers.json"


def save(cookies: list[dict[str, Any]]) -> None:
    _cookies_path().write_text(json.dumps(cookies, indent=2, ensure_ascii=False))


def load() -> list[dict[str, Any]]:
    p = _cookies_path()
    if not p.exists():
        return []
    return json.loads(p.read_text())


def save_storage_state(state: dict[str, Any]) -> None:
    """Salva o storage_state completo do Playwright (cookies + storage)."""
    _storage_path().write_text(json.dumps(state, indent=2, ensure_ascii=False))


def load_storage_state() -> dict[str, Any] | None:
    p = _storage_path()
    if not p.exists():
        return None
    return json.loads(p.read_text())


def has_storage_state() -> bool:
    return _storage_path().exists()


def as_httpx_dict() -> dict[str, str]:
    """Formato consumível pelo httpx.AsyncClient(cookies=...)."""
    return {c["name"]: c["value"] for c in load()}


def save_bff_headers(headers: dict[str, str]) -> None:
    _bff_headers_path().write_text(json.dumps(headers, indent=2, ensure_ascii=False))


def bff_headers() -> dict[str, str]:
    """Headers x-latam-* capturados durante o primer."""
    p = _bff_headers_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def is_stale(max_age_hours: int = 6) -> bool:
    """Heurística simples: arquivo de cookies mais velho que X horas."""
    p = _cookies_path()
    if not p.exists():
        return True
    return (time.time() - p.stat().st_mtime) > max_age_hours * 3600
