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


class VerifyRegistrationOtpRequest(BaseModel):
    """Payload to verify the registration OTP (Step 2 of 3)."""

    session_id: str = Field(
        ...,
        description="Fayda OTP session ID received from Step 1 (/register/request-otp).",
        examples=["FAYDA-SES-A1B2C3D4E5F67890"],
    )
    otp_code: str = Field(
        ...,
        description="6-digit OTP code received on phone.",
        examples=["123456"],
        min_length=6,
        max_length=6,
    )


class VerifyRegistrationOtpResponse(BaseModel):
    """Response payload after successful OTP verification (Step 2 of 3)."""

    registration_token: str = Field(
        ...,
        description="Signed verification token carrying identity attributes to submit in Step 3.",
        examples=["eyJhbGciOiJIUzI1..."],
    )
    fin: str = Field(..., description="Verified Fayda FIN.", examples=["12345678901234"])
    full_name: str = Field(..., description="Legal name from Fayda.", examples=["Abebe Girma Tadesse"])
    phone_number: str = Field(..., description="Verified phone number.", examples=["+251911234567"])
    message: str = Field(..., description="Status message.", examples=["OTP verified successfully. Proceed to complete registration."])


class CompleteRegistrationRequest(BaseModel):
    """Payload to complete user registration (Step 3 of 3)."""

    registration_token: str = Field(
        ...,
        description="Verified registration token from Step 2 (/register/verify-otp).",
        examples=["eyJhbGciOiJIUzI1..."],
    )
    username: str = Field(
        ...,
        description="Desired base handle (3-30 chars, alphanumeric and underscores). The system will append @eupi.",
        examples=["abebe_girma"],
        min_length=3,
        max_length=30,
    )
    pin: str = Field(
        ...,
        description="6-digit numeric login PIN.",
        examples=["123456"],
        min_length=6,
        max_length=6,
    )


class UserRegisterRequest(BaseModel):
    """Payload to register a new Super App user."""

    username: str = Field(
        ...,
        description="Base handle (3-30 chars, alphanumeric and underscores only). The system will append @eupi.",
        examples=["abebe_girma"],
        min_length=3,
        max_length=30,
    )
    pin: str = Field(
        ...,
        description="6-digit numeric PIN for app login authentication.",
        examples=["123456"],
        min_length=6,
        max_length=6,
    )
    registration_token: str | None = Field(
        default=None,
        description="Verified registration token from Step 2 (/register/verify-otp).",
        examples=["eyJhbGciOiJIUzI1..."],
    )
    fin: str | None = Field(
        default=None,
        description="14-digit Fayda Identification Number (if registering directly without registration_token).",
        examples=["12345678901234"],
    )
    full_name: str | None = Field(
        default=None,
        description="Full legal name (autopopulated if omitted).",
        examples=["Abebe Girma Tadesse"],
    )
    phone_number: str | None = Field(
        default=None,
        description="E.164 phone number (autopopulated if omitted).",
        examples=["+251911234567"],
    )
    session_id: str | None = Field(
        default=None,
        description="Optional Fayda OTP session ID.",
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
        description="Username handle (e.g. 'abebe_girma'). The @eupi postfix is automatically handled.",
        examples=["abebe_girma"],
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
        description="Username handle (e.g. 'abebe_girma'). The @eupi postfix is automatically handled.",
        examples=["abebe_girma"],
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
    summary="Step 1 of 3: Request Registration OTP",
    description=(
        "**Step 1 of 3-Step Registration**: Accepts `fin` and `phone_number`.\n\n"
        "Verifies that the phone number matches the Fayda National Registry record for this FIN. "
        "Dispatches a 6-digit OTP and returns a `session_id` for Step 2."
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
        message="Fayda eKYC OTP dispatched to registered phone number. Pass session_id and otp_code to /register/verify-otp.",
    )


@router.post(
    "/register/verify-otp",
    response_model=VerifyRegistrationOtpResponse,
    status_code=status.HTTP_200_OK,
    summary="Step 2 of 3: Verify Registration OTP",
    description=(
        "**Step 2 of 3-Step Registration**: Accepts `session_id` and `otp_code`.\n\n"
        "Validates the OTP code sent in Step 1. On success, returns a signed `registration_token` "
        "which securely encodes the verified citizen identity attributes (FIN, legal name, phone number) for Step 3."
    ),
)
def verify_registration_otp(body: VerifyRegistrationOtpRequest) -> VerifyRegistrationOtpResponse:
    from backend.main import get_user_registration_service
    service = get_user_registration_service()

    try:
        result = service.verify_registration_otp(session_id=body.session_id, otp_code=body.otp_code)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return VerifyRegistrationOtpResponse(
        registration_token=result["registration_token"],
        fin=result["fin"],
        full_name=result["full_name"],
        phone_number=result["phone_number"],
        message="OTP verified successfully. Submit registration_token, username, and pin to /register/complete.",
    )


@router.post(
    "/register/complete",
    response_model=SuperAppUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Step 3 of 3: Complete User Registration",
    description=(
        "**Step 3 of 3-Step Registration**: Accepts `registration_token`, `username`, and 6-digit `pin`.\n\n"
        "Does NOT require entering FIN or phone number again! Decodes the verified identity from Step 2, "
        "validates username uniqueness, and creates the Super App user profile."
    ),
)
def complete_registration(body: CompleteRegistrationRequest) -> SuperAppUserResponse:
    from backend.main import get_user_registration_service
    service = get_user_registration_service()

    try:
        user = service.complete_registration(
            registration_token=body.registration_token,
            username=body.username,
            pin=body.pin,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Vault the national ID immediately on account creation. Composed here
    # rather than inside UserRegistrationService so the registration use case
    # keeps depending only on its own ports.
    #
    # Best-effort: the account already exists at this point, and failing the
    # response would leave the user with an account they were told was not
    # created. The gap is logged loudly and is repairable by re-vaulting.
    try:
        from backend.main import get_consent_service

        get_consent_service().vault_fin(user.username, user.fin)
    except Exception:  # noqa: BLE001 — see above
        import logging

        logging.getLogger(__name__).exception(
            "Failed to vault the FIN for a newly registered user.",
            extra={"username": user.username},
        )

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
    from backend.application.use_cases.user_registration_service import PINLockedError
    from backend.main import get_user_registration_service
    service = get_user_registration_service()

    try:
        user, session_token = service.verify_pin(username=body.username, pin=body.pin)
    except PINLockedError as exc:
        # 429 rather than 401 so the client can show a wait-and-retry state
        # instead of prompting for the PIN again.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        )
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
        from backend.infrastructure.auth.jwt_handler import get_jti_for_revocation
        jti = get_jti_for_revocation(token)
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

    from backend.domain.models.user import normalize_username
    if normalize_username(current_user.username) != normalize_username(body.username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot change PIN for another user.")

    from backend.application.use_cases.user_registration_service import PINLockedError
    try:
        service.change_pin(
            username=body.username,
            current_pin=body.current_pin,
            new_pin=body.new_pin,
        )
    except PINLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
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


@router.get(
    "/me",
    response_model=SuperAppUserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Authenticated User Profile",
    description="Returns full profile metadata for the authenticated session user.",
)
def get_current_user_profile(
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> SuperAppUserResponse:
    return SuperAppUserResponse(
        username=current_user.username,
        fin=current_user.fin,
        full_name=current_user.full_name,
        phone_number=current_user.phone_number,
        created_at=current_user.created_at,
        is_active=current_user.is_active,
    )

