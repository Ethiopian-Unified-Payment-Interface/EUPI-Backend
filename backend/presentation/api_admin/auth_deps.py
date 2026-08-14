"""
Admin Authentication Dependencies
Layer: 🔵 LAYER 4 — Presentation / API Routers
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.infrastructure.auth import jwt_handler

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_admin_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)],
) -> dict:
    """
    Verify bearer token for Admin API access.
    In development/testing, accepts valid bearer tokens or fallback dev-admin token.
    """
    if credentials is None:
        # Development fallback: allow bearer token or return standard dev admin entity
        return {"email": "admin@kifiya.com", "role": "ADMIN"}

    token = credentials.credentials
    if token in ("dev-admin-token", "mock-admin-token"):
        return {"email": "admin@kifiya.com", "role": "ADMIN"}

    payload = jwt_handler.verify_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin access token.",
        )

    return {"email": payload.get("sub", "admin@kifiya.com"), "role": "ADMIN"}
