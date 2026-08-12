"""
Presentation Layer: Super App User Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/superapp/users", tags=["Super App — User Management"])


# ── Request / Response Schemas ─────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    """Payload to register a new Super App user after Fayda eKYC."""

    username: str = Field(
        ...,
        description="Unique handle (3-30 chars, alphanumeric and underscores only).",
        examples=["abebe_girma"],
        min_length=3,
        max_length=30,
    )
    fin: str = Field(
        ...,
        description="14-digit Fayda Identification Number (must exist in the registry).",
        examples=["12345678901234"],
        min_length=14,
        max_length=14,
    )
    full_name: str = Field(
        ...,
        description="Full legal name from Fayda eKYC verification.",
        examples=["Abebe Girma Tadesse"],
    )
    phone_number: str = Field(
        ...,
        description="E.164 phone number.",
        examples=["+251911234567"],
    )


class SuperAppUserResponse(BaseModel):
    """Full registered Super App user profile."""

    user_id: str = Field(..., description="Gateway-assigned unique user ID.", examples=["550e8400-e29b-41d4-a716-446655440000"])
    username: str = Field(..., description="Unique handle.", examples=["abebe_girma"])
    fin: str = Field(..., description="14-digit Fayda Identification Number.", examples=["12345678901234"])
    full_name: str = Field(..., description="Full legal name.", examples=["Abebe Girma Tadesse"])
    phone_number: str = Field(..., description="Registered phone number.", examples=["+251911234567"])
    created_at: datetime = Field(..., description="Timestamp of account registration.")
    is_active: bool = Field(default=True, description="Account active status.", examples=[True])


class PublicUserProfileResponse(BaseModel):
    """Public-facing profile for P2P recipient verification. No sensitive data."""

    username: str = Field(..., description="Unique handle.", examples=["abebe_girma"])
    full_name: str = Field(..., description="Full legal name.", examples=["Abebe Girma Tadesse"])


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=SuperAppUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Super App User",
    description=(
        "**Creates a new Super App platform account.**\n\n"
        "Requires a Fayda FIN that has passed eKYC verification. "
        "The username must be unique across the platform (3-30 characters, alphanumeric + underscores).\n\n"
        "**Test Hint**: Use FIN `12345678901234` (Abebe Girma Tadesse) or `23456789012345` (Selamawit Bekele Hailu)."
    ),
)
def register_user(body: UserRegisterRequest) -> SuperAppUserResponse:
    from backend.main import get_user_registration_service
    service = get_user_registration_service()

    try:
        user = service.register_user(
            username=body.username,
            fin=body.fin,
            full_name=body.full_name,
            phone_number=body.phone_number,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return SuperAppUserResponse(
        user_id=user.user_id,
        username=user.username,
        fin=user.fin,
        full_name=user.full_name,
        phone_number=user.phone_number,
        created_at=user.created_at,
        is_active=user.is_active,
    )


@router.get(
    "/profile/{username}",
    response_model=PublicUserProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Lookup Public Profile by Username",
    description=(
        "**Recipient verification for P2P transfers.**\n\n"
        "Returns only non-sensitive public profile data (username + full name). "
        "Use this before initiating a transfer to confirm the recipient."
    ),
)
def get_public_profile(username: str) -> PublicUserProfileResponse:
    from backend.main import get_user_registration_service
    service = get_user_registration_service()

    try:
        profile = service.get_public_profile(username=username)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return PublicUserProfileResponse(
        username=profile.username,
        full_name=profile.full_name,
    )
