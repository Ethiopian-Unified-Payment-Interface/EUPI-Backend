"""
JWT Handler — Gateway Token Issuance & Validation
==================================================
Layer: 🔴 LAYER 3 — Infrastructure / Auth
Rule: Only this module is allowed to sign or decode gateway JWTs.

All gateway tokens are signed HS256 JWTs. In production, rotate to RS256
with a proper key-management system (e.g., AWS KMS, HashiCorp Vault).

Token types
-----------
Every token carries a `type` claim, and every decoder asserts the exact type
it expects. This is load-bearing: without it a Super App session token — which
also carries sub/jti/scopes/kyc_level — validates as a gateway AIS/PIS token
and grants access to banking endpoints it was never issued for.

    gateway_access            Consumer AIS/PIS access, issued after Fayda eKYC
    superapp_session          Super App login session
    registration_verification Short-lived token bridging OTP → account creation
    admin_session             Admin portal session, carries a role claim

Token payload schema (gateway_access):
    {
        "sub":       "12345678901234",          # Fayda FIN
        "jti":       "uuid4-string",            # Unique token ID (for revocation)
        "type":      "gateway_access",          # Token type — always asserted
        "scopes":    ["accounts:read", ...],    # Granted OAuth-style scopes
        "kyc_level": "STANDARD",                # KYC assurance level achieved
        "iss":       "kifiya-open-gateway",
        "iat":       1234567890,                # Issued-at (Unix timestamp)
        "exp":       1234571490,                # Expiry (Unix timestamp)
    }
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Final

import jwt
from jwt.exceptions import DecodeError, ExpiredSignatureError, InvalidTokenError

from backend.config import settings

# ── Token type constants ──────────────────────────────────────────────────────

TOKEN_TYPE_GATEWAY: Final = "gateway_access"
TOKEN_TYPE_SUPERAPP: Final = "superapp_session"
TOKEN_TYPE_REGISTRATION: Final = "registration_verification"
TOKEN_TYPE_ADMIN: Final = "admin_session"
TOKEN_TYPE_TPP: Final = "tpp_access"
TOKEN_TYPE_TPP_USER: Final = "tpp_user_access"

ISSUER: Final = "kifiya-open-gateway"

# How a payer's consent was obtained. Carried as a claim on gateway tokens and
# therefore recoverable from any payment that stored its consent token.
CONSENT_METHOD_FAYDA_OTP: Final = "fayda_otp"
CONSENT_METHOD_SUPERAPP_PIN: Final = "superapp_pin"
CONSENT_METHOD_TPP_AUTH_CODE: Final = "tpp_authorization_code"


class TokenTypeError(InvalidTokenError):
    """Raised when a token is structurally valid but of the wrong type."""


# ── Internal helpers ──────────────────────────────────────────────────────────


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _decode(
    token: str,
    expected_type: str,
    required_claims: list[str],
) -> dict[str, Any]:
    """
    Decode, verify, and assert the token's type.

    Signature, expiry, and issuer are checked by PyJWT. The type check is ours
    and must happen for every token — see the module docstring.

    Raises:
        ExpiredSignatureError: Token passed its `exp`.
        TokenTypeError:        Valid token, wrong type for this call site.
        InvalidTokenError:     Bad signature, issuer mismatch, missing claims.
        DecodeError:           Structurally malformed.
    """
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=ISSUER,
        options={"require": [*required_claims, "type", "exp", "iat", "iss"]},
    )

    actual_type = payload.get("type")
    if actual_type != expected_type:
        raise TokenTypeError(
            f"Expected a '{expected_type}' token but received '{actual_type}'."
        )

    return payload


def _issue(
    payload: dict[str, Any],
    ttl_seconds: int,
) -> tuple[str, str, datetime]:
    """Stamp a payload with jti/iss/iat/exp and sign it."""
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    jti = str(uuid.uuid4())

    payload = {
        **payload,
        "jti": jti,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return _encode(payload), jti, expires_at


# ── Gateway access tokens (consumer AIS/PIS) ──────────────────────────────────


def create_gateway_jwt(
    fin: str,
    scopes: list[str],
    kyc_level: str,
    consent_method: str = CONSENT_METHOD_FAYDA_OTP,
    ttl_seconds: int | None = None,
) -> tuple[str, str, datetime]:
    """
    Issue a signed gateway JWT for an authenticated customer.

    Args:
        fin:            Customer's verified Fayda Identification Number.
        scopes:         List of granted consent scopes (e.g., ["accounts:read"]).
        kyc_level:      KYC assurance level of the session (e.g., "STANDARD").
        consent_method: How the payer's consent was obtained. Recorded as a
                        claim so an auditor reviewing a payment can tell
                        whether it was authorised by a Fayda OTP or by an
                        in-app transaction PIN — the two are not equivalent
                        evidence and the ledger must not blur them.
        ttl_seconds:    Lifetime override. Defaults to JWT_TOKEN_TTL_SECONDS;
                        pass something short for a token minted to authorise a
                        single payment.

    Returns:
        A 3-tuple of (encoded_token, jti, expires_at).
    """
    return _issue(
        {
            "sub": fin,
            "type": TOKEN_TYPE_GATEWAY,
            "scopes": scopes,
            "kyc_level": kyc_level,
            "consent_method": consent_method,
        },
        ttl_seconds if ttl_seconds is not None else settings.JWT_TOKEN_TTL_SECONDS,
    )


def decode_gateway_jwt(token: str) -> dict[str, Any]:
    """
    Decode and cryptographically verify a gateway access token.

    Rejects Super App session tokens, registration tokens, and admin tokens
    even though some carry an overlapping claim set.
    """
    return _decode(
        token,
        expected_type=TOKEN_TYPE_GATEWAY,
        required_claims=["sub", "jti", "scopes", "kyc_level"],
    )


def is_token_structurally_valid(token: str) -> bool:
    """
    Return True if the token is a valid, unexpired gateway access token.
    Does NOT check DB revocation — use the PaymentRepository for that.
    """
    try:
        decode_gateway_jwt(token)
        return True
    except (ExpiredSignatureError, InvalidTokenError, DecodeError):
        return False


def get_claim(token: str, claim: str) -> Any | None:
    """
    Safely extract a single claim from a valid, unexpired gateway token.

    Returns None if the token is invalid, expired, the wrong type, or the
    claim is absent.
    """
    try:
        return decode_gateway_jwt(token).get(claim)
    except (ExpiredSignatureError, InvalidTokenError, DecodeError):
        return None


def get_fin(token: str) -> str | None:
    """Convenience: extract the `sub` (FIN) claim from a valid gateway token."""
    return get_claim(token, "sub")


def get_jti(token: str) -> str | None:
    """Convenience: extract the `jti` (token ID) claim from a valid gateway token."""
    return get_claim(token, "jti")


def get_jti_for_revocation(token: str) -> str | None:
    """
    Extract `jti` from any valid token, regardless of type.

    Revocation is deliberately type-agnostic: logging out must invalidate the
    presented token whether it is a gateway, Super App, or admin session. The
    signature and expiry are still verified — only the type assertion is
    skipped, and the returned jti grants nothing on its own.

    Returns None if the token is invalid, expired, or carries no jti.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=ISSUER,
            options={"require": ["jti", "exp", "iat", "iss"]},
        )
    except (ExpiredSignatureError, InvalidTokenError, DecodeError):
        return None
    return payload.get("jti")


# ── Super App session tokens ──────────────────────────────────────────────────


def create_superapp_session_jwt(
    username: str,
    fin: str,
) -> tuple[str, str, datetime]:
    """
    Issue a signed Super App session JWT for an authenticated user login.

    Args:
        username: Registered Super App handle.
        fin:      Verified Fayda Identification Number.

    Returns:
        3-tuple of (encoded_token, jti, expires_at).
    """
    return _issue(
        {
            "sub": username,
            "fin": fin,
            "type": TOKEN_TYPE_SUPERAPP,
            "scopes": ["superapp:user"],
            "kyc_level": "STANDARD",
        },
        settings.JWT_TOKEN_TTL_SECONDS,
    )


def decode_superapp_session_jwt(token: str) -> dict[str, Any]:
    """Decode and verify a Super App session JWT."""
    return _decode(
        token,
        expected_type=TOKEN_TYPE_SUPERAPP,
        required_claims=["sub", "jti"],
    )


# ── Registration tokens (OTP → account creation bridge) ───────────────────────


def create_registration_token(
    fin: str,
    full_name: str,
    phone_number: str,
) -> str:
    """
    Issue a signed temporary registration token after Step 2 OTP verification.

    Valid for 15 minutes — long enough to choose a handle and PIN, short enough
    that a leaked token is not a standing account-creation capability.
    """
    token, _jti, _expires_at = _issue(
        {
            "fin": fin,
            "full_name": full_name,
            "phone_number": phone_number,
            "type": TOKEN_TYPE_REGISTRATION,
        },
        ttl_seconds=15 * 60,
    )
    return token


def decode_registration_token(token: str) -> dict[str, Any]:
    """Decode and verify a registration token."""
    return _decode(
        token,
        expected_type=TOKEN_TYPE_REGISTRATION,
        required_claims=["fin", "full_name", "phone_number"],
    )


# ── Admin session tokens ──────────────────────────────────────────────────────


def create_admin_jwt(email: str, role: str) -> tuple[str, str, datetime]:
    """
    Issue a signed admin portal session token.

    Args:
        email: Admin's login email — becomes the `sub` claim and the audit actor.
        role:  Role name driving RBAC (see domain.models.admin_user.AdminRole).

    Returns:
        3-tuple of (encoded_token, jti, expires_at).
    """
    return _issue(
        {
            "sub": email,
            "type": TOKEN_TYPE_ADMIN,
            "role": role,
        },
        settings.ADMIN_SESSION_TTL_SECONDS,
    )


def decode_admin_jwt(token: str) -> dict[str, Any]:
    """
    Decode and verify an admin session token.

    Raises on anything that is not a live, correctly-typed admin token — there
    is deliberately no permissive fallback.
    """
    return _decode(
        token,
        expected_type=TOKEN_TYPE_ADMIN,
        required_claims=["sub", "jti", "role"],
    )


# ── TPP App access tokens (client credentials, no user) ───────────────────────


def create_tpp_access_jwt(
    app_id: str,
    client_id: str,
    merchant_id: str | None = None,
    environment: str = "SANDBOX",
    scopes: list[str] | None = None,
    ttl_seconds: int = 3600,
) -> tuple[str, str, datetime]:
    """
    Issue a signed TPP app-level access token (client credentials grant).

    Carries NO psu_id and NO kyc_level so it cannot reach user-scoped routes.
    """
    return _issue(
        {
            "sub": app_id,
            "type": TOKEN_TYPE_TPP,
            "app_id": app_id,
            "client_id": client_id,
            "merchant_id": merchant_id,
            "environment": environment,
            "scopes": scopes or [],
        },
        ttl_seconds,
    )


def decode_tpp_access_jwt(token: str) -> dict[str, Any]:
    """Decode and verify a TPP app-level access token."""
    return _decode(
        token,
        expected_type=TOKEN_TYPE_TPP,
        required_claims=["sub", "jti", "app_id", "client_id", "environment", "scopes"],
    )


# ── TPP User delegated access tokens (auth code grant) ───────────────────────


def create_tpp_user_access_jwt(
    psu_id: str,
    app_id: str,
    client_id: str,
    environment: str = "SANDBOX",
    scopes: list[str] | None = None,
    kyc_level: str = "STANDARD",
    ttl_seconds: int = 3600,
) -> tuple[str, str, datetime]:
    """
    Issue a signed TPP user-delegated access token (authorization code grant).

    `sub` is the per-app pseudonym (psu_id), never the username or Fayda FIN.
    """
    return _issue(
        {
            "sub": psu_id,
            "type": TOKEN_TYPE_TPP_USER,
            "psu_id": psu_id,
            "app_id": app_id,
            "client_id": client_id,
            "environment": environment,
            "scopes": scopes or [],
            "kyc_level": kyc_level,
            "consent_method": CONSENT_METHOD_TPP_AUTH_CODE,
        },
        ttl_seconds,
    )


def decode_tpp_user_access_jwt(token: str) -> dict[str, Any]:
    """Decode and verify a TPP user-delegated access token."""
    return _decode(
        token,
        expected_type=TOKEN_TYPE_TPP_USER,
        required_claims=["sub", "jti", "psu_id", "app_id", "client_id", "environment", "scopes"],
    )

