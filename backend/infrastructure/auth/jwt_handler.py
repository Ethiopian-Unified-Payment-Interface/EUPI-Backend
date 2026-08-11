"""
JWT Handler — Gateway Token Issuance & Validation
==================================================
Layer: 🔴 LAYER 3 — Infrastructure / Auth
Rule: Only this module is allowed to sign or decode gateway JWTs.

All gateway tokens are signed HS256 JWTs. In production, rotate to RS256
with a proper key-management system (e.g., AWS KMS, HashiCorp Vault).

Token payload schema:
    {
        "sub":       "12345678901234",          # Fayda FIN
        "jti":       "uuid4-string",            # Unique token ID (for revocation)
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
from typing import Any

import jwt
from jwt.exceptions import DecodeError, ExpiredSignatureError, InvalidTokenError

from backend.config import settings


def create_gateway_jwt(
    fin: str,
    scopes: list[str],
    kyc_level: str,
) -> tuple[str, str, datetime]:
    """
    Issue a signed gateway JWT for an authenticated customer.

    Args:
        fin:       Customer's verified Fayda Identification Number.
        scopes:    List of granted consent scopes (e.g., ["accounts:read"]).
        kyc_level: KYC assurance level of the Fayda session (e.g., "STANDARD").

    Returns:
        A 3-tuple of:
            - encoded_token (str): The signed JWT string.
            - jti (str): The unique token ID (for DB revocation tracking).
            - expires_at (datetime): UTC expiry timestamp.
    """
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(seconds=settings.JWT_TOKEN_TTL_SECONDS)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": fin,
        "jti": jti,
        "scopes": scopes,
        "kyc_level": kyc_level,
        "iss": "kifiya-open-gateway",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    token: str = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, jti, expires_at


def decode_gateway_jwt(token: str) -> dict[str, Any]:
    """
    Decode and cryptographically verify a gateway JWT.

    Args:
        token: The encoded JWT string.

    Returns:
        The decoded payload dict.

    Raises:
        ExpiredSignatureError: If the token has passed its `exp` timestamp.
        InvalidTokenError:     If the signature is invalid, issuer mismatches,
                               or any other JWT validation failure.
        DecodeError:           If the token is structurally malformed.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["sub", "jti", "scopes", "kyc_level", "exp", "iat"]},
    )


def is_token_structurally_valid(token: str) -> bool:
    """
    Return True if the token has a valid signature and has not expired.
    Does NOT check DB revocation — use the SQLiteRepository for that.
    """
    try:
        decode_gateway_jwt(token)
        return True
    except (ExpiredSignatureError, InvalidTokenError, DecodeError):
        return False


def get_claim(token: str, claim: str) -> Any | None:
    """
    Safely extract a single claim from a valid, unexpired token.

    Returns None if the token is invalid, expired, or the claim is absent.
    """
    try:
        return decode_gateway_jwt(token).get(claim)
    except (ExpiredSignatureError, InvalidTokenError, DecodeError):
        return None


def get_fin(token: str) -> str | None:
    """Convenience: extract the `sub` (FIN) claim from a valid token."""
    return get_claim(token, "sub")


def get_jti(token: str) -> str | None:
    """Convenience: extract the `jti` (token ID) claim from a valid token."""
    return get_claim(token, "jti")
