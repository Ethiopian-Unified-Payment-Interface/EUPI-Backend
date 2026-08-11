"""
Domain Model: Identity
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.

Defines the Fayda National ID eKYC schemas used for customer identity
verification (AIS consent) and developer KYB (Know Your Business) onboarding.

Fayda is Ethiopia's national digital ID system (ISO/IEC 24745 compliant).
FIN = Fayda Identification Number (analogous to a National ID number).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class KYCLevel(str, Enum):
    """
    Fayda KYC assurance levels aligned with NIST SP 800-63-3 IAL tiers.

    BASIC   — Name + FIN number only (IAL1). Suitable for low-value AIS.
    STANDARD — Name + FIN + biometric liveness check (IAL2). Required for PIS.
    ENHANCED — Full face-match + document scan (IAL3). Required for large value PIS.
    """

    BASIC = "BASIC"
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class Gender(str, Enum):
    """Gender as recorded on the Fayda National ID."""

    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class FaydaVerifyRequest(BaseModel):
    """
    Request payload to trigger a Fayda eKYC verification.

    Submitted by the TPP on behalf of its customer. The gateway forwards
    this to the Fayda identity_port for OTP dispatch and liveness checks.
    """

    fin: str = Field(
        ...,
        description="Fayda Identification Number (14-digit numeric string).",
        min_length=14,
        max_length=14,
        pattern=r"^\d{14}$",
        examples=["12345678901234"],
    )
    phone_number: str = Field(
        ...,
        description="Registered phone number for OTP delivery (E.164 format).",
        pattern=r"^\+251\d{9}$",
        examples=["+251911234567"],
    )
    required_kyc_level: KYCLevel = Field(
        default=KYCLevel.STANDARD,
        description="Minimum KYC assurance level required for the intended operation.",
    )
    consent_scope: str = Field(
        ...,
        description="Comma-separated OAuth-style scopes granted by the customer.",
        examples=["accounts:read,transactions:read"],
    )


class FaydaKYCResult(BaseModel):
    """
    The normalised result of a successful Fayda eKYC verification.

    Returned by the identity_port after Fayda confirms the customer's identity.
    The gateway uses this to issue a scoped JWT to the TPP.
    """

    fin: str = Field(
        ...,
        description="Verified Fayda Identification Number.",
        examples=["12345678901234"],
    )
    full_name: str = Field(
        ...,
        description="Full legal name as recorded in the Fayda registry.",
        examples=["Abebe Girma Tadesse"],
    )
    date_of_birth: date = Field(
        ...,
        description="Date of birth as per the Fayda ID (ISO 8601 date).",
        examples=["1990-05-15"],
    )
    gender: Gender = Field(
        ...,
        description="Gender as recorded on the Fayda ID.",
    )
    nationality: str = Field(
        default="ETH",
        description="ISO 3166-1 alpha-3 nationality code.",
        examples=["ETH"],
    )
    kyc_level_achieved: KYCLevel = Field(
        ...,
        description="Actual KYC assurance level confirmed by Fayda for this session.",
    )
    is_verified: bool = Field(
        ...,
        description="True if identity was positively confirmed; False if any check failed.",
    )
    verified_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the Fayda verification was completed.",
    )
    consent_token: str = Field(
        ...,
        description="Opaque short-lived consent token issued after successful verification. "
                    "Must be presented for subsequent PIS/AIS operations.",
        examples=["fayda_ctkn_a1b2c3d4e5f6"],
    )
    granted_scopes: list[str] = Field(
        default_factory=list,
        description="List of OAuth-style scopes confirmed by the customer.",
        examples=[["accounts:read", "transactions:read"]],
    )
    photo_url: Optional[str] = Field(
        default=None,
        description="Signed URL for the customer's Fayda ID photo (expires in 60s). "
                    "Only returned when required_kyc_level=ENHANCED.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "fin": "12345678901234",
                "full_name": "Abebe Girma Tadesse",
                "date_of_birth": "1990-05-15",
                "gender": "MALE",
                "nationality": "ETH",
                "kyc_level_achieved": "STANDARD",
                "is_verified": True,
                "verified_at": "2025-11-01T09:45:00Z",
                "consent_token": "fayda_ctkn_a1b2c3d4e5f6",
                "granted_scopes": ["accounts:read", "transactions:read"],
                "photo_url": None,
            }
        }
    }
