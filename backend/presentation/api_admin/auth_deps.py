"""
Admin Authentication Dependencies
Layer: 🔵 LAYER 4 — Presentation / API Routers

Every Admin API route depends on `get_current_admin_user`. There is no
unauthenticated path: a missing, malformed, expired, wrong-type, or revoked
token is a 401.

This module previously returned a valid admin identity when no credentials were
supplied, accepted the literal strings "dev-admin-token"/"mock-admin-token", and
called a `jwt_handler.verify_access_token` that did not exist — so presenting a
real token raised AttributeError and 500'd, leaving the unauthenticated path as
the only one that worked.
"""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import DecodeError, ExpiredSignatureError, InvalidTokenError

from backend.domain.models.admin_user import AdminRole, AdminUser
from backend.infrastructure.auth import jwt_handler

# auto_error=False so a missing header produces our own 401 with a useful
# message rather than FastAPI's bare 403.
_bearer_scheme = HTTPBearer(auto_error=False, description="Admin session JWT")

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Admin authentication required.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_admin_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)],
) -> AdminUser:
    """
    Resolve and verify the admin session token on the request.

    Returns:
        The authenticated :class:`~domain.models.admin_user.AdminUser`.

    Raises:
        HTTPException: 401 if the token is absent, invalid, expired, of the
                       wrong type, or the operator no longer exists or is
                       disabled.
    """
    if credentials is None or not credentials.credentials:
        raise _UNAUTHENTICATED

    try:
        payload = jwt_handler.decode_admin_jwt(credentials.credentials)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (InvalidTokenError, DecodeError):
        raise _UNAUTHENTICATED

    email = payload.get("sub")
    if not email:
        raise _UNAUTHENTICATED

    # Re-read the operator on every request. A token issued before a role change
    # or a deactivation must not outlive it for the rest of its TTL.
    from backend.main import get_admin_user_repository

    admin = get_admin_user_repository().get_by_email(email)
    if admin is None or not admin.is_active:
        raise _UNAUTHENTICATED

    return admin


def require_role(*allowed: AdminRole) -> Callable[..., AdminUser]:
    """
    Build a dependency that admits only the listed roles.

    Usage:
        @router.post("/banks", dependencies=[Depends(require_role(AdminRole.ADMIN))])

    Args:
        allowed: Roles permitted to call the route.

    Returns:
        A FastAPI dependency yielding the authenticated AdminUser, or raising
        403 when the operator's role is not permitted.
    """

    def _guard(
        admin: Annotated[AdminUser, Depends(get_current_admin_user)],
    ) -> AdminUser:
        if admin.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{admin.role.value}' is not permitted to perform this action."
                ),
            )
        return admin

    return _guard


# Convenience dependency for the common "must be able to write" case.
require_admin = require_role(AdminRole.ADMIN)
