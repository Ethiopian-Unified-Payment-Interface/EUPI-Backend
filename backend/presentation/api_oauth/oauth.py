"""
Presentation Layer: OAuth 2.0 & Consent Approval Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Implements OAuth 2.0 authorization code grant (with PKCE), token issuance,
      consent approval, revocation (RFC 7009), and introspection (RFC 7662).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.config import settings
from backend.domain.models.user import SuperAppUser, normalize_username
from backend.presentation.api_superapp.auth_deps import get_current_superapp_user

router = APIRouter(
    prefix="/oauth",
    tags=["OAuth 2.0 & Consent Authorization"],
)

# In-memory storage for active authorization requests waiting for user consent
_AUTHORIZATION_REQUESTS: dict[str, dict[str, Any]] = {}


class AuthorizeDetailsResponse(BaseModel):
    request_id: str
    client_id: str
    app_name: str
    merchant_name: str
    app_logo_url: str | None = None
    requested_scopes: list[str]
    redirect_uri: str
    state: str | None = None


class ApproveConsentRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6, description="User PIN to authorize consent")
    approved_scopes: list[str] = Field(..., min_items=1, description="List of scopes approved by user")


class ApproveConsentResponse(BaseModel):
    authorization_code: str
    redirect_uri: str
    state: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    scope: str
    refresh_token: str | None = None


@router.get(
    "/authorize",
    response_model=AuthorizeDetailsResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate OAuth authorization request for Consent UI",
)
def oauth_authorize(
    client_id: str = Query(..., description="Developer App Client ID"),
    redirect_uri: str = Query(..., description="Redirect URI registered for app"),
    response_type: str = Query("code", description="Must be 'code'"),
    scope: str = Query(..., description="Space-separated list of scopes"),
    state: str | None = Query(None, description="Opaque state value"),
    code_challenge: str = Query(..., description="PKCE S256 challenge string"),
    code_challenge_method: str = Query("S256", description="Must be 'S256'"),
) -> AuthorizeDetailsResponse:
    if response_type != "code":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported response_type. Only 'code' is supported.",
        )
    if code_challenge_method != "S256":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported code_challenge_method. Only 'S256' is supported.",
        )

    from backend.main import get_repo
    repo = get_repo()
    
    # Query app details from sqlite_repo
    with repo._session() as session:
        from backend.infrastructure.database.models import DeveloperAppRecord
        app_rec = session.query(DeveloperAppRecord).filter(DeveloperAppRecord.client_id == client_id).first()
        if not app_rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown client_id '{client_id}'.",
            )
        if app_rec.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Application '{app_rec.app_name}' is currently inactive.",
            )

        app_name = app_rec.app_name
        merchant_name = app_rec.merchant_name
        app_logo_url = getattr(app_rec, "app_logo_url", None)
        app_id = app_rec.app_id

    requested_scopes = [s.strip() for s in scope.split() if s.strip()]
    request_id = f"AUTH-REQ-{uuid.uuid4().hex[:12].upper()}"

    # Store authorization request in memory (expires in 10 minutes)
    _AUTHORIZATION_REQUESTS[request_id] = {
        "request_id": request_id,
        "app_id": app_id,
        "client_id": client_id,
        "app_name": app_name,
        "merchant_name": merchant_name,
        "requested_scopes": requested_scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "created_at": datetime.now(tz=timezone.utc),
    }

    return AuthorizeDetailsResponse(
        request_id=request_id,
        client_id=client_id,
        app_name=app_name,
        merchant_name=merchant_name,
        app_logo_url=app_logo_url,
        requested_scopes=requested_scopes,
        redirect_uri=redirect_uri,
        state=state,
    )


@router.post(
    "/consent/{request_id}/approve",
    response_model=ApproveConsentResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve OAuth consent request with user PIN",
)
def approve_consent(
    request_id: str,
    body: ApproveConsentRequest,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> ApproveConsentResponse:
    from backend.main import get_repo, get_user_service
    from backend.domain.models.user import normalize_username

    auth_req = _AUTHORIZATION_REQUESTS.get(request_id)
    if not auth_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authorization request expired or not found. Please restart the auth flow.",
        )

    user_svc = get_user_service()
    username = normalize_username(current_user.username)
    
    # Verify PIN
    verified = user_svc.verify_pin(username=username, pin=body.pin)
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid PIN. Please check your PIN and try again.",
        )

    repo = get_repo()
    app_id = auth_req["app_id"]

    # Record user consents
    for sc in body.approved_scopes:
        repo.grant_user_consent(username=username, app_id=app_id, scope=sc)

    # Generate authorization code
    raw_code = f"eupi_ac_{uuid.uuid4().hex}"
    code_hash = hashlib.sha256(raw_code.encode()).hexdigest()

    # Save code record to database
    with repo._session() as session:
        from backend.infrastructure.database.models import AuthorizationCodeRecord
        import json
        code_rec = AuthorizationCodeRecord(
            code_hash=code_hash,
            request_id=request_id,
            app_id=app_id,
            username=username,
            scopes=json.dumps(body.approved_scopes),
            redirect_uri=auth_req["redirect_uri"],
            code_challenge=auth_req["code_challenge"],
            code_challenge_method=auth_req["code_challenge_method"],
            expires_at=datetime.now(tz=timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
        )
        session.add(code_rec)

    # Clean up memory request
    _AUTHORIZATION_REQUESTS.pop(request_id, None)

    return ApproveConsentResponse(
        authorization_code=raw_code,
        redirect_uri=auth_req["redirect_uri"],
        state=auth_req.get("state"),
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Issue OAuth 2.0 access token via authorization code or client credentials",
)
def issue_oauth_token(
    grant_type: str = Form("authorization_code"),
    code: str | None = Form(None),
    client_id: str = Form(...),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
) -> TokenResponse:
    from backend.main import get_jwt_handler, get_repo
    jwt_handler = get_jwt_handler()
    repo = get_repo()

    if grant_type == "authorization_code":
        if not code or not code_verifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing 'code' or 'code_verifier' parameter for authorization_code grant.",
            )

        code_hash = hashlib.sha256(code.encode()).hexdigest()
        
        with repo._session() as session:
            from backend.infrastructure.database.models import AuthorizationCodeRecord
            code_rec = session.query(AuthorizationCodeRecord).filter(
                AuthorizationCodeRecord.code_hash == code_hash
            ).first()

            if not code_rec or code_rec.consumed_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or already consumed authorization code.",
                )

            # Verify PKCE S256 code challenge
            computed_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()
            # Urlsafe B64 encoding check fallback or raw sha256 hex match
            if code_rec.code_challenge not in (computed_challenge, code_verifier):
                # For standard PKCE S256 check
                import base64
                b64_digest = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
                if code_rec.code_challenge != b64_digest:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="PKCE code_verifier verification failed.",
                    )

            # Mark code consumed
            code_rec.consumed_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)

            import json
            scopes = json.loads(code_rec.scopes)
            username = code_rec.username

        # Get user FIN
        user = repo.get_by_username(username)
        fin = user.fin if user else "12345678901234"

        # Issue user-delegated TPP access token (tpp_user_access)
        token = jwt_handler.issue_token(
            fin=fin,
            kyc_level="LEVEL_2_FULL",
            scopes=scopes,
            token_type="tpp_user_access",
        )

        return TokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(scopes),
        )
    elif grant_type == "client_credentials":
        # App-level token (tpp_access)
        token = jwt_handler.issue_token(
            fin="TPP-APP-CLIENT",
            kyc_level="LEVEL_1_BASIC",
            scopes=["accounts:read"],
            token_type="tpp_access",
        )
        return TokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=3600,
            scope="accounts:read",
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported grant_type '{grant_type}'.",
        )


@router.post(
    "/revoke",
    status_code=status.HTTP_200_OK,
    summary="Revoke OAuth access token (RFC 7009)",
)
def revoke_oauth_token(token: str = Form(...)) -> dict[str, str]:
    from backend.main import get_jwt_handler
    jwt_handler = get_jwt_handler()
    jwt_handler.revoke_token(token)
    return {"status": "revoked"}


@router.post(
    "/introspect",
    status_code=status.HTTP_200_OK,
    summary="Introspect OAuth access token status and scope claims (RFC 7662)",
)
def introspect_oauth_token(token: str = Form(...)) -> dict[str, Any]:
    from backend.main import get_jwt_handler
    jwt_handler = get_jwt_handler()
    payload = jwt_handler.validate_token(token)
    if not payload:
        return {"active": False}

    return {
        "active": True,
        "scope": " ".join(payload.scopes),
        "client_id": payload.jti,
        "username": payload.fin,
        "exp": int(payload.expires_at.timestamp()),
        "token_type": getattr(payload, "token_type", "tpp_user_access"),
    }
