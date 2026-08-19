"""
Developer Portal Authentication Endpoints
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)

Implements self-service registration, email verification with automatic Sandbox
provisioning, developer login, and session profile restoration.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from backend.presentation.api_developer.auth_deps import (
    DeveloperPrincipal,
    get_current_developer,
)

router = APIRouter(prefix="/developer", tags=["Developer Portal — Authentication & Onboarding"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class DeveloperRegisterPayload(BaseModel):
    full_name: str = Field(..., examples=["Abebe Girma"])
    email: EmailStr = Field(..., examples=["abebe@ethiopay.et"])
    phone_number: str = Field(..., examples=["+251911234567"])
    password: str = Field(..., min_length=8, examples=["SecurePassword123!"])
    company_name: str = Field(..., examples=["EthioPay Solutions PLC"])


class DeveloperVerifyEmailPayload(BaseModel):
    email: EmailStr = Field(..., examples=["abebe@ethiopay.et"])
    token: str = Field(..., description="6-digit verification code or token.", examples=["123456"])


class DeveloperLoginPayload(BaseModel):
    email: EmailStr = Field(..., examples=["abebe@ethiopay.et"])
    password: str = Field(..., examples=["SecurePassword123!"])


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new developer account",
)
def register_developer(body: DeveloperRegisterPayload) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        res = service.register_developer(
            full_name=body.full_name,
            email=body.email,
            phone_number=body.phone_number,
            password=body.password,
            company_name=body.company_name,
        )
        return res
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/verify-email",
    status_code=status.HTTP_200_OK,
    summary="Verify email and activate instant Sandbox credentials",
)
def verify_email(body: DeveloperVerifyEmailPayload) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        res = service.verify_email(email=body.email, token=body.token)
        return res
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    summary="Developer login and session generation",
)
def login_developer(body: DeveloperLoginPayload) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        res = service.login_developer(email=body.email, password=body.password)
        return res
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Get current developer profile and apps",
)
def get_current_developer_profile(
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        profile = service.get_profile(principal.developer_id)
        return profile
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
