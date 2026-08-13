"""
Presentation Layer: Super App Authentication Dependencies
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Extract and validate Super App session JWT from request headers.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from backend.domain.models.user import SuperAppUser
from backend.infrastructure.auth.jwt_handler import decode_superapp_session_jwt


def get_current_superapp_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> SuperAppUser:
    """
    FastAPI dependency to extract and validate the Super App session token from headers.

    Accepts token via either:
      - Authorization: Bearer <session_token>
      - X-Session-Token: <session_token>

    Raises:
        HTTPException 401 Unauthorized if header is missing, token is invalid,
        expired, revoked, or user profile is not found.
    """
    token: str | None = None

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_session_token:
        token = x_session_token.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Super App session header missing. Please log in with your 6-digit PIN.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_superapp_session_jwt(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired Super App session: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    username = payload.get("sub")

    if not username or not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session token claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check DB revocation
    from backend.main import get_repo, get_user_registration_service
    repo = get_repo()
    if repo.is_token_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been logged out / revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_service = get_user_registration_service()
    user = user_service._user_repo.get_by_username(username)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Super App user '{username}' is inactive or not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
