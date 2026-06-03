"""Optional API-key authentication for hosted deployments."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import settings


def require_api_key_if_configured(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    if not settings.api_key:
        return

    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()

    if token and hmac.compare_digest(token, settings.api_key):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key.",
    )
