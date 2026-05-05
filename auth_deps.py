"""Optional API key (Bearer or X-API-Key) for hosted deployments."""

from __future__ import annotations

from fastapi import Header, HTTPException

import settings


def require_api_key_if_configured(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    if not settings.API_KEY:
        return
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()
    if token == settings.API_KEY:
        return
    raise HTTPException(
        status_code=401,
        detail="Invalid or missing API key. Send Authorization: Bearer <key> or X-API-Key.",
    )
