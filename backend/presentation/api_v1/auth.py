"""
Presentation Layer: Auth Routes — POST /v1/auth/fayda
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["🔐 Authentication"])


# ── Request / Response schemas (presentation-layer only) ──────────────────────

class FaydaAuthInitiateRequest(BaseModel):
    """Request body for Step 1: trigger OTP dispatch to the customer's phone."""

    fin: str = Field(
        ...,
        description="Customer's 14-digit Fayda Identification Number.",
        examples=["12345678901234"],
        min_length=14,
        max_length=14,
    )
    phone_number: str = Field(
        ...,
        description="Registered phone number in E.164 format.",
        examples=["+251911234567"],
    )
    consent_scope: str = Field(
        ...,
        description="Comma-separated OAuth-style scopes the customer is granting.",
        examples=["accounts:read,transactions:read"],
    )


class FaydaAuthInitiateResponse(BaseModel):
    """Response returned after OTP has been dispatched."""

    session_id: str = Field(..., description="Opaque session token. Present with OTP in confirm step.")
    message: str = Field(default="OTP sent to the registered phone number.")
    expires_in_seconds: int = Field(default=300, description="Session expires in 5 minutes.")


class FaydaAuthConfirmRequest(BaseModel):
    """Request body for Step 2: submit the OTP to obtain a JWT."""

    session_id: str = Field(..., description="Session ID from the initiate step.")
    otp_code: str = Field(..., min_length=6, max_length=6, description="6-digit OTP.", examples=["123456"])
    fin: str = Field(..., min_length=14, max_length=14, description="Customer's FIN.", examples=["12345678901234"])


class FaydaAuthConfirmResponse(BaseModel):
    """Response containing the gateway JWT issued after successful verification."""

    access_token: str = Field(..., description="Bearer JWT for authenticating AIS/PIS requests.")
    token_type: str = Field(default="Bearer")
    expires_in: int = Field(default=3600, description="Token TTL in seconds.")
    kyc_level: str = Field(..., description="KYC assurance level achieved (BASIC / STANDARD / ENHANCED).")
    granted_scopes: list[str] = Field(..., description="Confirmed consent scopes.")


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/fayda",
    response_model=FaydaAuthInitiateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate Fayda eKYC — dispatch OTP",
    description=(
        "Triggers the Fayda identity system to dispatch a one-time password "
        "to the customer's registered phone number. Returns a `session_id` "
        "that must be presented in the `/auth/fayda/confirm` call."
    ),
)
def initiate_fayda_auth(body: FaydaAuthInitiateRequest) -> FaydaAuthInitiateResponse:
    from backend.main import get_identity_port  # lazy import to avoid circular refs
    identity_port = get_identity_port()
    from backend.domain.models.identity import FaydaVerifyRequest, KYCLevel
    verify_request = FaydaVerifyRequest(
        fin=body.fin,
        phone_number=body.phone_number,
        required_kyc_level=KYCLevel.STANDARD,
        consent_scope=body.consent_scope,
    )
    try:
        session_id = identity_port.initiate_kyc_verification(verify_request)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return FaydaAuthInitiateResponse(session_id=session_id)


@router.post(
    "/fayda/confirm",
    response_model=FaydaAuthConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm OTP — receive Gateway JWT",
    description=(
        "Validates the customer's OTP against the active Fayda session. "
        "On success returns a signed JWT that must be passed as a "
        "`Bearer` token on all AIS and PIS requests."
    ),
)
def confirm_fayda_auth(body: FaydaAuthConfirmRequest) -> FaydaAuthConfirmResponse:
    from backend.main import get_identity_port
    identity_port = get_identity_port()
    try:
        result = identity_port.confirm_kyc_otp(
            session_id=body.session_id,
            otp_code=body.otp_code,
            fin=body.fin,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    return FaydaAuthConfirmResponse(
        access_token=result.consent_token,
        kyc_level=result.kyc_level_achieved.value,
        granted_scopes=result.granted_scopes,
    )
