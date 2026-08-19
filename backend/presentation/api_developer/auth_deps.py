"""
Developer Portal Authentication Dependencies
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
"""

from __future__ import annotations

from typing import Any
from fastapi import Header, HTTPException, status
from pydantic import BaseModel

from backend.infrastructure.auth.jwt_handler import decode_developer_session_jwt


class DeveloperPrincipal(BaseModel):
    """Authenticated developer user identity extracted from session token."""

    developer_id: str
    email: str
    company_name: str
    status: str


def get_current_developer(
    authorization: str | None = Header(default=None),
) -> DeveloperPrincipal:
    """
    Extract and validate the developer portal session token from Authorization header.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:].strip()
    try:
        claims = decode_developer_session_jwt(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired developer session token: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return DeveloperPrincipal(
        developer_id=claims["developer_id"],
        email=claims["email"],
        company_name=claims.get("company_name", ""),
        status=claims.get("status", "SANDBOX_ACTIVE"),
    )
