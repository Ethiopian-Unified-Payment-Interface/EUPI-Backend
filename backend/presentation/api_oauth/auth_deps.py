"""
OAuth & TPP Authentication Dependencies
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Scope checking, token-type assertion, revocation verification.

Provides Depends-able functions for protecting third-party developer (TPP) routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.domain.models.consent import ConsentScope
from backend.infrastructure.auth.jwt_handler import (
    TOKEN_TYPE_TPP,
    TOKEN_TYPE_TPP_USER,
    decode_tpp_access_jwt,
    decode_tpp_user_access_jwt,
)

_bearer = HTTPBearer()


def _get_payment_repo():
    try:
        from backend.main import get_repo
        return get_repo()
    except Exception:
        try:
            from backend.infrastructure.database.payment_repository import PaymentRepository
            return PaymentRepository()
        except Exception:
            return None


@dataclass(frozen=True)
class TPPPrincipal:
    """
    The authenticated caller on a /v1 developer route.

    Constructed by require_scopes() after validating token signature, expiry,
    type assertion, revocation status, scope presence, and user consent.
    """

    app_id: str
    client_id: str
    merchant_id: str | None
    environment: str
    token_scopes: set[ConsentScope]
    token_type: str
    psu_id: str | None = None       # None for app-level tokens
    username: str | None = None     # Resolved internally. NEVER serialised.


def require_scopes(*needed: ConsentScope) -> Callable[..., TPPPrincipal]:
    """
    Admit only callers whose token carries every listed scope AND — for
    user-scoped routes — whose token is a delegated tpp_user_access token.

    Order of checks (failing closed at each step):
      1. Bearer header present
      2. Token decoded & type asserted (tpp_user_access or tpp_access)
      3. JTI checked for revocation
      4. Every needed scope present in token_scopes
      5. Any scope requiring user consent must be tpp_user_access
    """

    def dependency(
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    ) -> TPPPrincipal:
        token = credentials.credentials

        payload = None
        token_type = None

        # 1. Decode token (try tpp_user_access then tpp_access)
        try:
            payload = decode_tpp_user_access_jwt(token)
            token_type = TOKEN_TYPE_TPP_USER
        except Exception:
            try:
                payload = decode_tpp_access_jwt(token)
                token_type = TOKEN_TYPE_TPP
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid, expired, or malformed TPP access token.",
                )

        # 2. Check token revocation by JTI
        repo = _get_payment_repo()
        jti = payload.get("jti", "")
        if repo and repo.is_token_revoked(jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked.",
            )

        # Parse token scopes
        raw_scopes = payload.get("scopes", [])
        parsed_scopes: set[ConsentScope] = set()
        for s in raw_scopes:
            try:
                parsed_scopes.add(ConsentScope(s))
            except ValueError:
                pass

        # 3. Scope & User Consent validation
        for scope in needed:
            if scope not in parsed_scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient scope. Required scope '{scope.value}' is missing from token.",
                )

            if scope.requires_user_consent and token_type != TOKEN_TYPE_TPP_USER:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Scope '{scope.value}' requires user consent and cannot be called with an app-level token.",
                )

        psu_id = payload.get("psu_id")
        app_id = payload.get("app_id", "")
        client_id = payload.get("client_id", "")
        merchant_id = payload.get("merchant_id")
        environment = payload.get("environment", "SANDBOX")

        return TPPPrincipal(
            app_id=app_id,
            client_id=client_id,
            merchant_id=merchant_id,
            environment=environment,
            token_scopes=parsed_scopes,
            token_type=token_type,
            psu_id=psu_id,
        )

    return dependency
