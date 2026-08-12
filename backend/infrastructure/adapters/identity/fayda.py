"""
Fayda National ID — eKYC Adapter
==================================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls or issue JWTs.

Production: calls Ethiopia's Fayda OpenID Connect / eKYC API.
Mock (MVP): simulates Fayda OTP flow. Accepts OTP "123456" for any valid FIN.

Features:
  ✅ Issues REAL signed JWTs (PyJWT + HS256) instead of prefixed strings.
  ✅ Verifies tokens cryptographically via jwt_handler.
  ✅ Checks revocation via SQLite repo.
  ✅ OTP sessions have a real 5-minute expiry.
  ✅ Token issuance is recorded in the DB for revocation support.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from backend.application.ports.identity_port import IdentityPort
from backend.config import settings
from backend.domain.models.identity import (
    FaydaKYCResult,
    FaydaVerifyRequest,
    Gender,
    KYCLevel,
)
from backend.infrastructure.auth import jwt_handler
from backend.infrastructure.database.sqlite_repo import SQLiteRepository
from backend.infrastructure.mock_data.fayda_registry import get_identity

logger = logging.getLogger(__name__)

# Fixed OTP accepted in development mode.
_MOCK_OTP = "123456"
_SESSION_TTL_MINUTES = 5


class FaydaAdapter(IdentityPort):
    """
    Fayda National ID eKYC Adapter.

    Manages the two-step OTP verification flow and issues gateway JWTs
    on successful verification. Relies on the SQLiteRepository to persist
    token records for revocation tracking.

    Production wiring: replace `_mock_dispatch_otp()` and
    `_mock_confirm_otp()` with real httpx calls to the Fayda OIDC endpoint.
    """

    def __init__(self, repo: SQLiteRepository) -> None:
        self._repo = repo
        # In-memory OTP session store: session_id → (request, otp, expires_at)
        self._sessions: dict[str, tuple[FaydaVerifyRequest, str, datetime]] = {}

    # ── IdentityPort Contract ─────────────────────────────────────────────────

    def initiate_kyc_verification(self, request: FaydaVerifyRequest) -> str:
        """
        Dispatch an OTP to the customer's registered Fayda phone number.

        Production:
            POST {FAYDA_API_BASE_URL}/auth/otp/send
            Body: {fin: ..., phone: ..., client_id: ..., scope: ...}
            Returns: {"session_id": "...", "expires_in": 300}

        Mock:
            Generates a session_id and stores the request with a 5-min TTL.
            OTP is always _MOCK_OTP ("123456") regardless of FIN.
        """
        session_id = f"FAYDA-SES-{uuid.uuid4().hex[:16].upper()}"
        expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=_SESSION_TTL_MINUTES)
        self._sessions[session_id] = (request, _MOCK_OTP, expires_at)

        logger.info(
            "Fayda OTP session created (mock — OTP is '%s')",
            _MOCK_OTP,
            extra={"session_id": session_id, "fin_suffix": request.fin[-4:]},
        )
        return session_id

    def confirm_kyc_otp(
        self,
        session_id: str,
        otp_code: str,
        fin: str,
    ) -> FaydaKYCResult:
        """
        Validate the OTP and issue a signed gateway JWT.

        Production:
            POST {FAYDA_API_BASE_URL}/auth/otp/verify
            Body: {session_id: ..., otp: ..., fin: ...}
            Returns: {verified: true, identity: {...}, id_token: "..."}
            → decode id_token → create gateway JWT

        Mock:
            Accepts only OTP "123456". On success, issues a real HS256 JWT
            containing the FIN, KYC level, and granted scopes.
        """
        entry = self._sessions.get(session_id)
        if entry is None:
            raise ValueError(
                f"Session '{session_id}' not found or already consumed. "
                "Please re-initiate the verification."
            )

        stored_request, expected_otp, expires_at = entry

        if datetime.now(tz=timezone.utc) > expires_at:
            del self._sessions[session_id]
            raise ValueError(
                f"Session '{session_id}' has expired. OTP sessions last {_SESSION_TTL_MINUTES} minutes."
            )

        if otp_code != expected_otp:
            raise ValueError(
                f"Invalid OTP. "
                + (f"(Hint: use '{_MOCK_OTP}' in mock mode.)" if settings.DEBUG else "")
            )

        # Consume the session (one-time use)
        del self._sessions[session_id]

        # Verify the FIN exists in the national registry before issuing a token
        identity = get_identity(fin)
        if identity is None:
            raise ValueError(
                f"FIN '{fin}' not found in the Fayda national registry. "
                "Verification denied."
            )

        # Issue a real signed JWT
        scopes = stored_request.consent_scope.split(",")
        token, jti, expires_at_jwt = jwt_handler.create_gateway_jwt(
            fin=fin,
            scopes=scopes,
            kyc_level=stored_request.required_kyc_level.value,
        )

        # Persist token record for revocation support
        self._repo.save_token(
            jti=jti,
            fin=fin,
            kyc_level=stored_request.required_kyc_level.value,
            scopes=scopes,
            issued_at=datetime.now(tz=timezone.utc),
            expires_at=expires_at_jwt,
        )

        logger.info(
            "Fayda eKYC confirmed — gateway JWT issued",
            extra={"jti": jti, "kyc_level": stored_request.required_kyc_level.value},
        )

        return FaydaKYCResult(
            fin=fin,
            full_name=identity["full_name"],
            date_of_birth=datetime.strptime(identity["date_of_birth"], "%Y-%m-%d").date(),
            gender=Gender(identity["gender"]),
            nationality="ETH",
            kyc_level_achieved=stored_request.required_kyc_level,
            is_verified=True,
            verified_at=datetime.now(tz=timezone.utc),
            consent_token=token,                 # Real signed JWT
            granted_scopes=scopes,
        )

    def verify_consent_token(self, consent_token: str) -> bool:
        """
        Validate a gateway JWT: cryptographic check + revocation check.

        A token is only valid if:
          1. It has a valid HS256 signature.
          2. It has not expired (checked by PyJWT).
          3. Its JTI is not marked revoked in the SQLite DB.
        """
        if not jwt_handler.is_token_structurally_valid(consent_token):
            return False

        jti = jwt_handler.get_jti(consent_token)
        if jti and self._repo.is_token_revoked(jti):
            logger.warning("Revoked JWT presented: jti=%s", jti)
            return False

        return True

    def get_kyc_level_for_token(self, consent_token: str) -> KYCLevel:
        """Decode the JWT and return the kyc_level claim as a KYCLevel enum."""
        if not jwt_handler.is_token_structurally_valid(consent_token):
            raise ValueError("Cannot extract KYC level from an invalid or expired token.")

        kyc_level_str = jwt_handler.get_claim(consent_token, "kyc_level")
        if kyc_level_str is None:
            raise ValueError("Token is missing the 'kyc_level' claim.")

        try:
            return KYCLevel(kyc_level_str)
        except ValueError:
            raise ValueError(f"Unknown kyc_level value in token: '{kyc_level_str}'")
