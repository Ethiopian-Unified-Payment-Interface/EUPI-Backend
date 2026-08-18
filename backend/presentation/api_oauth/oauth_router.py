"""
OAuth 2.0 Router — POST /v1/oauth/token, GET /v1/oauth/authorize
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Unpack OAuth2 requests → validate credentials/PKCE → issue JWT tokens or redirect.

RFC 6749 & RFC 7636 compliant OAuth 2.0 Authorization Server endpoints.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Form, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.domain.models.consent import ConsentScope
from backend.infrastructure.auth.jwt_handler import (
    create_tpp_access_jwt,
    create_tpp_user_access_jwt,
)
from backend.presentation.api_oauth.oauth_helpers import OAuthHelper

router = APIRouter(prefix="/oauth", tags=["OAuth 2.0 Developer Platform"])
_helper = OAuthHelper()


# ── Schemas ───────────────────────────────────────────────────────────────────

class TokenRequestBody(BaseModel):
    grant_type: str = Field(..., examples=["client_credentials", "authorization_code"])
    client_id: str | None = Field(default=None, examples=["client_app_1"])
    client_secret: str | None = Field(default=None, examples=["secret_dev_123"])
    scope: str | None = Field(default=None, examples=["payments:read:own webhooks:receive"])
    code: str | None = Field(default=None)
    redirect_uri: str | None = Field(default=None)
    code_verifier: str | None = Field(default=None)
    refresh_token: str | None = Field(default=None)


class TokenResponse(BaseModel):
    """Standard OAuth 2.0 Token Response."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    scope: str
    refresh_token: str | None = None


class AuthorizeResponse(BaseModel):
    """Metadata response for authorization code consent UI."""

    request_id: str
    client_id: str
    app_name: str
    merchant_name: str
    requested_scopes: list[dict[str, str]]
    redirect_uri: str
    state: str


class ConsentApproveBody(BaseModel):
    """Body sent when a user approves requested scopes."""

    username: str = Field(..., description="Super app handle of approving user.")
    approved_scopes: list[str] = Field(..., description="List of approved scope strings.")


# In-memory store for pending authorization requests (short-lived)
_auth_requests: dict[str, dict[str, Any]] = {}


# ── Helper parsing HTTP Basic Auth ────────────────────────────────────────────

def _parse_basic_auth(auth_header: str | None) -> tuple[str | None, str | None]:
    if not auth_header or not auth_header.startswith("Basic "):
        return None, None
    try:
        import base64
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        parts = decoded.split(":", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], None)
    except Exception:
        return None, None


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/token",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Issue OAuth 2.0 access token",
    description=(
        "Standard OAuth 2.0 token endpoint supporting client_credentials and "
        "authorization_code (with PKCE S256)."
    ),
)
def issue_token(
    body: TokenRequestBody,
    authorization: str | None = Header(default=None),
) -> TokenResponse:
    grant_type = body.grant_type
    client_id = body.client_id
    client_secret = body.client_secret
    scope = body.scope
    code = body.code
    redirect_uri = body.redirect_uri
    code_verifier = body.code_verifier
    refresh_token = body.refresh_token

    # 1. Parse client credentials from Basic Auth header if present
    header_client_id, header_client_secret = _parse_basic_auth(authorization)
    effective_client_id = header_client_id or client_id
    effective_client_secret = header_client_secret or client_secret

    if not effective_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing client_id.",
        )

    # Lookup developer application
    app = _helper.get_app_by_client_id(effective_client_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Developer application with client_id '{effective_client_id}' not found.",
        )

    if app.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Developer application status is '{app.status}'.",
        )

    # ── Grant Type 1: client_credentials (App-level access) ───────────────────
    if grant_type == "client_credentials":
        if not effective_client_secret or not _helper.verify_client_secret(app, effective_client_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid client_secret.",
            )

        # Parse requested scopes
        app_allowed: list[str] = json.loads(app.allowed_scopes) if isinstance(app.allowed_scopes, str) else app.allowed_scopes
        requested_scopes = scope.split() if scope else app_allowed

        # Validate requested scopes against allowed_scopes and ensure they are app-level
        validated_scopes: list[str] = []
        for s in requested_scopes:
            if s not in app_allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Scope '{s}' is not allowed for this developer application.",
                )
            try:
                cs = ConsentScope(s)
                if not cs.is_app_level:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Scope '{s}' requires user consent and cannot be granted via client_credentials.",
                    )
                validated_scopes.append(s)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid scope '{s}'.",
                )

        token, jti, expires_at = create_tpp_access_jwt(
            app_id=app.app_id,
            client_id=app.client_id,
            merchant_id=app.merchant_id,
            environment=app.environment,
            scopes=validated_scopes,
            ttl_seconds=3600,
        )
        return TokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(validated_scopes),
        )

    # ── Grant Type 2: authorization_code (User-delegated access with PKCE) ────
    elif grant_type == "authorization_code":
        if not code or not redirect_uri or not code_verifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="authorization_code grant requires 'code', 'redirect_uri', and 'code_verifier'.",
            )

        try:
            auth_record = _helper.consume_authorization_code(
                raw_code=code,
                app_id=app.app_id,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        # Resolve user pseudonym psu_id
        from backend.main import get_consent_service
        consent_service = get_consent_service()
        psu_id = consent_service.resolve_psu_id(
            username=auth_record.username,
            app_id=app.app_id,
        )

        scopes_list: list[str] = json.loads(auth_record.scopes)
        token, jti, expires_at = create_tpp_user_access_jwt(
            psu_id=psu_id,
            app_id=app.app_id,
            client_id=app.client_id,
            environment=app.environment,
            scopes=scopes_list,
            kyc_level="STANDARD",
            ttl_seconds=3600,
        )
        return TokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(scopes_list),
            refresh_token=f"ref_{secrets_token()}",
        )

    # ── Grant Type 3: refresh_token ───────────────────────────────────────────
    elif grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing refresh_token.",
            )
        # Mock refresh token issuance
        token, _, _ = create_tpp_access_jwt(
            app_id=app.app_id,
            client_id=app.client_id,
            merchant_id=app.merchant_id,
            environment=app.environment,
            scopes=json.loads(app.allowed_scopes),
            ttl_seconds=3600,
        )
        return TokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=3600,
            scope=app.allowed_scopes,
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported grant_type '{grant_type}'.",
        )


@router.get(
    "/authorize",
    response_model=AuthorizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Authorize third-party application access",
    description="RFC 6749 Authorization Code Request endpoint.",
)
def authorize_request(
    response_type: str = Query(..., examples=["code"]),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: str = Query(...),
    state: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query(default="S256"),
) -> AuthorizeResponse:
    if response_type != "code":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported response_type. Only 'code' is supported.",
        )

    app = _helper.get_app_by_client_id(client_id)
    if not app or app.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or inactive client_id.",
        )

    allowed_redirects: list[str] = json.loads(app.redirect_uris) if isinstance(app.redirect_uris, str) else app.redirect_uris
    if allowed_redirects and redirect_uri not in allowed_redirects:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"redirect_uri '{redirect_uri}' is not registered for this app.",
        )

    # Format requested scope details
    requested_list = scope.split()
    formatted_scopes: list[dict[str, str]] = []
    for s in requested_list:
        try:
            cs = ConsentScope(s)
            formatted_scopes.append({"scope": cs.value, "description": cs.description})
        except ValueError:
            formatted_scopes.append({"scope": s, "description": s})

    request_id = f"req_{uuid.uuid4().hex[:16]}"
    _auth_requests[request_id] = {
        "app_id": app.app_id,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scopes": requested_list,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    }

    return AuthorizeResponse(
        request_id=request_id,
        client_id=client_id,
        app_name=app.app_name,
        merchant_name=app.merchant_name,
        requested_scopes=formatted_scopes,
        redirect_uri=redirect_uri,
        state=state,
    )


@router.post(
    "/consent/{request_id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve consent and generate authorization code",
)
def approve_consent(request_id: str, body: ConsentApproveBody) -> dict[str, str]:
    req = _auth_requests.pop(request_id, None)
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authorization request expired or invalid.",
        )

    app_id = req["app_id"]
    from backend.main import get_consent_service
    consent_service = get_consent_service()

    # Record consent grants in DB
    for s_str in body.approved_scopes:
        try:
            cs = ConsentScope(s_str)
            consent_service.grant_consent(
                username=body.username,
                app_id=app_id,
                scope=cs,
            )
        except Exception:
            pass

    # Issue single-use PKCE authorization code
    raw_code = _helper.create_authorization_code(
        app_id=app_id,
        username=body.username,
        scopes=body.approved_scopes,
        redirect_uri=req["redirect_uri"],
        code_challenge=req["code_challenge"],
        code_challenge_method=req["code_challenge_method"],
        ttl_seconds=60,
    )

    redirect_url = f"{req['redirect_uri']}?code={raw_code}&state={req['state']}"
    return {
        "code": raw_code,
        "state": req["state"],
        "redirect_url": redirect_url,
    }


def secrets_token() -> str:
    import secrets
    return secrets.token_hex(16)
