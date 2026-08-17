"""
Admin Authentication API Routes
Layer: 🔵 LAYER 4 — Presentation / API Routers

The only unauthenticated routes under /v1/admin. Everything else requires the
session token issued here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from backend.application.use_cases.admin_auth_service import (
    AdminAccountInactiveError,
    InvalidAdminCredentialsError,
)
from backend.domain.models.admin_user import AdminUser
from backend.presentation.api_admin.auth_deps import get_current_admin_user

router = APIRouter(prefix="/auth", tags=["Admin — Authentication"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class AdminLoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Operator login email.", examples=["admin@kifiya.com"])
    password: str = Field(..., min_length=1, description="Operator password.")


class AdminLoginResponse(BaseModel):
    access_token: str = Field(..., description="Signed admin session JWT.")
    token_type: str = Field(default="bearer", description="Always 'bearer'.")
    expires_at: datetime = Field(..., description="UTC expiry of the session token.")
    email: str = Field(..., description="Authenticated operator email.")
    full_name: str = Field(..., description="Operator display name.")
    role: str = Field(..., description="Operator role: ADMIN or READ_ONLY.")


class AdminProfileResponse(BaseModel):
    email: str
    full_name: str
    role: str
    last_login_at: datetime | None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/login",
    response_model=AdminLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin Login",
    description=(
        "**Authenticate a Kifiya operator and start an admin session.**\n\n"
        "Returns a signed session token. Send it as `Authorization: Bearer <token>` "
        "on every other `/v1/admin/*` call."
    ),
)
def admin_login(body: AdminLoginRequest) -> AdminLoginResponse:
    from backend.infrastructure.auth import jwt_handler
    from backend.main import get_admin_auth_service

    service = get_admin_auth_service()

    try:
        admin = service.authenticate(email=str(body.email), password=body.password)
    except InvalidAdminCredentialsError:
        # Deliberately identical for unknown email and wrong password so the
        # response cannot be used to enumerate valid operator accounts.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AdminAccountInactiveError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    token, _jti, expires_at = jwt_handler.create_admin_jwt(
        email=admin.email,
        role=admin.role.value,
    )

    return AdminLoginResponse(
        access_token=token,
        expires_at=expires_at,
        email=admin.email,
        full_name=admin.full_name,
        role=admin.role.value,
    )


@router.get(
    "/me",
    response_model=AdminProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Current Admin Profile",
    description="Returns the operator identified by the session token. Used by the portal to restore a session on load.",
)
def get_admin_profile(
    admin: Annotated[AdminUser, Depends(get_current_admin_user)],
) -> AdminProfileResponse:
    return AdminProfileResponse(
        email=admin.email,
        full_name=admin.full_name,
        role=admin.role.value,
        last_login_at=admin.last_login_at,
    )
