"""
Mock Fayda Identity Adapter — for local development & Swagger testing.
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Legacy mock adapter. Superseded by fayda.py which issues real signed JWTs.

Hardcoded behaviour:
  - initiate_kyc_verification() → always returns a mock session_id
  - confirm_kyc_otp()           → accepts OTP "123456", rejects anything else
  - verify_consent_token()      → any token starting with "fayda_ctkn_" is valid
  - get_kyc_level_for_token()   → always returns STANDARD
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from backend.application.ports.identity_port import IdentityPort
from backend.domain.models.identity import (
    FaydaKYCResult,
    FaydaVerifyRequest,
    Gender,
    KYCLevel,
)

_MOCK_OTP = "123456"
_MOCK_TOKEN_PREFIX = "fayda_ctkn_"

# In-memory session store: session_id → FaydaVerifyRequest
_sessions: dict[str, FaydaVerifyRequest] = {}


class FaydaMockAdapter(IdentityPort):
    """Mock Fayda eKYC adapter for development and Swagger testing."""

    def initiate_kyc_verification(self, request: FaydaVerifyRequest) -> str:
        session_id = f"SES-{uuid.uuid4().hex[:12].upper()}"
        _sessions[session_id] = request
        return session_id

    def confirm_kyc_otp(
        self,
        session_id: str,
        otp_code: str,
        fin: str,
    ) -> FaydaKYCResult:
        if session_id not in _sessions:
            raise ValueError(f"Session '{session_id}' not found or expired.")
        if otp_code != _MOCK_OTP:
            raise ValueError(
                f"Invalid OTP for session '{session_id}'."
            )
        session = _sessions.pop(session_id)
        consent_token = f"{_MOCK_TOKEN_PREFIX}{uuid.uuid4().hex}"
        return FaydaKYCResult(
            fin=fin,
            full_name="Abebe Girma Tadesse",
            date_of_birth=date(1990, 5, 15),
            gender=Gender.MALE,
            nationality="ETH",
            kyc_level_achieved=session.required_kyc_level,
            is_verified=True,
            verified_at=datetime.now(tz=timezone.utc),
            consent_token=consent_token,
            granted_scopes=session.consent_scope.split(","),
        )

    def verify_consent_token(self, consent_token: str) -> bool:
        # Any token with our mock prefix is considered valid.
        return consent_token.startswith(_MOCK_TOKEN_PREFIX)

    def get_kyc_level_for_token(self, consent_token: str) -> KYCLevel:
        if not self.verify_consent_token(consent_token):
            raise ValueError(f"Invalid consent token: {consent_token!r}")
        return KYCLevel.STANDARD
