"""Auth JWT para o dashboard — single-user via cookie httpOnly."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Cookie, HTTPException, status

from app.config import get_settings

_ALGORITHM = "HS256"


def create_token() -> str:
    cfg = get_settings()
    payload = {
        "sub": "dashboard",
        "exp": datetime.now(UTC) + timedelta(days=cfg.jwt_ttl_days),
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=_ALGORITHM)


def require_auth(viatu_session: Annotated[str | None, Cookie()] = None) -> str:
    if not viatu_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        jwt.decode(viatu_session, get_settings().jwt_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
    return viatu_session
