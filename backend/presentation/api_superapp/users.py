"""
Presentation Layer: Super App User Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from backend.domain.models.user import SuperAppUser
from backend.presentation.api_superapp.auth_deps import get_current_superapp_user

router = APIRouter(prefix="/superapp/users", tags=["Super App — User Management"])


# ── Request / Response Schemas ─────────────────────────────────────────────────

class RegistrationOtpRequest(BaseModel):
    """Request payload to dispatch a Fayda eKYC OTP for user registration."""

    fin: str = Field(
        ...,
        description="14-digit Fayda Identification Number.",
        examples=["12345678901234"],
        min_length=14,
        max_length=14,
    )
    phone_number: str = Field(
        ...,
        description="E.164 phone number to verify against the Fayda registry.",
        examples=["+251911234567"],
    )


class RegistrationOtpResponse(BaseModel):
    """Response payload after dispatching a registration OTP."""

    session_id: str = Field(..., description="Fayda OTP session ID.", examples=["FAYDA-SES-A1B2C3D4E5F67890"])
    message: str = Field(..., description="Status message.", examples=["OTP dispatched to registered phone number."])


class UserRegisterRequest(BaseModel):
    """Payload to register a new Super App user after Fayda eKYC."""

    username: str = Field(
        ...,
        description="Base handle (3-30 chars, alphanumeric and underscores only). The system will append @eupi.",
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
    full_name: str | None = Field(
        default=None,
        description="Full legal name (autopopulated from Fayda registry if omitted).",
        examples=["Abebe Girma Tadesse"],
    )
    phone_number: str | None = Field(
        default=None,
        description="E.164 phone number (autopopulated from Fayda registry if omitted).",
        examples=["+251911234567"],
    )
    pin: str = Field(
        ...,
        description="6-digit numeric PIN for app login authentication.",
        examples=["123456"],
        min_length=6,
        max_length=6,
    )
    session_id: str | None = Field(
        default=None,
        description="Optional Fayda OTP session ID (if performing 2-step OTP registration).",
        examples=["FAYDA-SES-A1B2C3D4E5F67890"],
    )
    otp_code: str | None = Field(
        default=None,
        description="Optional 6-digit OTP code received on phone.",
        examples=["123456"],
    )


class SuperAppUserResponse(BaseModel):
    """Full registered Super App user profile."""

    username: str = Field(..., description="Unique handle.", examples=["abebe_girma@eupi"])
    fin: str = Field(..., description="14-digit Fayda Identification Number.", examples=["12345678901234"])
    full_name: str = Field(..., description="Full legal name.", examples=["Abebe Girma Tadesse"])
    phone_number: str = Field(..., description="Registered phone number.", examples=["+251911234567"])
    created_at: datetime = Field(..., description="Timestamp of account registration.")
    is_active: bool = Field(default=True, description="Account active status.", examples=[True])


class PublicUserProfileResponse(BaseModel):
    """Public-facing profile for P2P recipient verification. No sensitive data."""

    username: str = Field(..., description="Unique handle.", examples=["abebe_girma@eupi"])
    full_name: str = Field(..., description="Full legal name.", examples=["Abebe Girma Tadesse"])


class PinLoginRequest(BaseModel):
    """Payload for Super App PIN-based login."""

    username: str = Field(
        ...,
        description="Username of the account to log into.",
        examples=["abebe_girma@eupi"],
    )
    pin: str = Field(
        ...,
        description="6-digit numeric PIN.",
        examples=["123456"],
        min_length=6,
        max_length=6,
    )


class PinLoginResponse(BaseModel):
    """Successful PIN login response."""

    username: str = Field(..., description="Authenticated username.", examples=["abebe_girma@eupi"])
    full_name: str = Field(..., description="Full legal name.", examples=["Abebe Girma Tadesse"])
    session_token: str = Field(..., description="JWT session token to include in Authorization header for subsequent calls.", examples=["eyJhbGciOiJIUzI1..."])
    message: str = Field(..., description="Login result.", examples=["PIN verified. Welcome back!"])


class ChangePinRequest(BaseModel):
    """Payload to change the user's PIN."""

    username: str = Field(
        ...,
        description="Full Super App username (with @eupi suffix).",
        examples=["abebe_girma@eupi"],
    )
    current_pin: str = Field(
        ...,
        description="Current 6-digit PIN.",
        examples=["123456"],
        min_length=6,
        max_length=6,
    )
    new_pin: str = Field(
        ...,
        description="New 6-digit PIN.",
        examples=["654321"],
        min_length=6,
        max_length=6,
    )


class MessageResponse(BaseModel):
    """Standard operation result message."""

    message: str = Field(..., description="Operation result.", examples=["Operation completed successfully."])


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/register/request-otp",
    response_model=RegistrationOtpResponse,
    status_code=status.HTTP_200_OK,
    summary="1. Request Registration OTP (Fayda eKYC)",
    description=(
        "**Step 1 of Registration**: Dispatches a 6-digit OTP to the phone number registered to the Fayda FIN.\n\n"
        "Returns a `session_id` to pass alongside the OTP code when completing registration."
    ),
)
def request_registration_otp(body: RegistrationOtpRequest) -> RegistrationOtpResponse:
    from backend.main import get_user_registration_service
    service = get_user_registration_service()

    try:
        session_id = service.request_registration_otp(fin=body.fin, phone_number=body.phone_number)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return RegistrationOtpResponse(
        session_id=session_id,
        message="Fayda eKYC OTP dispatched to the phone number registered with this National ID.",
    )


@router.post(
    "/register",
    response_model=SuperAppUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="2. Register Super App User",
    description=(
        "**Creates a new Super App platform account.**\n\n"
        "Verifies that the Fayda FIN exists in the National Registry and checks optional OTP verification. "
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
            pin=body.pin,
            session_id=body.session_id,
            otp_code=body.otp_code,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return SuperAppUserResponse(
        username=user.username,
        fin=user.fin,
        full_name=user.full_name,
        phone_number=user.phone_number,
        created_at=user.created_at,
        is_active=user.is_active,
    )


@router.post(
    "/login",
    response_model=PinLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Login with PIN & Start Session",
    description=(
        "**Authenticate a Super App user with their username and 6-digit PIN.**\n\n"
        "Returns the authenticated user's identity and a signed `session_token` on success. "
        "Include this token in the `Authorization: Bearer <session_token>` header for all subsequent calls."
    ),
)
def login_with_pin(body: PinLoginRequest) -> PinLoginResponse:
    from backend.main import get_user_registration_service
    service = get_user_registration_service()

    try:
        user, session_token = service.verify_pin(username=body.username, pin=body.pin)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    return PinLoginResponse(
        username=user.username,
        full_name=user.full_name,
        session_token=session_token,
        message="PIN verified. Welcome back!",
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout & Revoke Session",
    description="Invalidates the active Super App session token.",
)
def logout_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> MessageResponse:
    from backend.main import get_repo
    token = (authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else x_session_token)
    if token:
        from backend.infrastructure.auth.jwt_handler import get_jti
        jti = get_jti(token)
        if jti:
            get_repo().revoke_token(jti)
    return MessageResponse(message="Logged out successfully. Session invalidated.")


@router.put(
    "/change-pin",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Change PIN",
    description="**Change the user's 6-digit login PIN.** Requires active session and current PIN.",
)
def change_pin(
    body: ChangePinRequest,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> MessageResponse:
    from backend.main import get_user_registration_service
    service = get_user_registration_service()

    if current_user.username != body.username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot change PIN for another user.")

    try:
        service.change_pin(
            username=body.username,
            current_pin=body.current_pin,
            new_pin=body.new_pin,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return MessageResponse(message="PIN changed successfully.")


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
