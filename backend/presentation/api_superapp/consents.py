"""
Presentation Layer: Super App Privacy & Consents Management Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call repository/use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.domain.models.user import SuperAppUser, normalize_username
from backend.presentation.api_superapp.auth_deps import get_current_superapp_user

router = APIRouter(
    prefix="/superapp/consents",
    tags=["Super App — Privacy & Consents"],
)

SCOPE_CATALOGUE = [
    {
        "scope": "accounts:read",
        "name": "Account Information",
        "description": "View linked account numbers, available balances, and basic account metadata.",
        "category": "ACCOUNT",
        "is_sensitive": false,
    },
    {
        "scope": "payments:initiate",
        "name": "Payment Initiation",
        "description": "Initiate P2P transfers and third-party merchant payments on your behalf.",
        "category": "PAYMENT",
        "is_sensitive": true,
    },
    {
        "scope": "identity:read:fin",
        "name": "National ID (FIN) Verification",
        "description": "Access your 14-digit Fayda FIN and verified full name for identity verification.",
        "category": "IDENTITY",
        "is_sensitive": true,
    },
]


class ScopeItemResponse(BaseModel):
    scope: str
    name: str
    description: str
    category: str
    is_sensitive: bool


class ConsentItemResponse(BaseModel):
    consent_id: str
    app_id: str
    app_name: str
    merchant_name: str
    app_logo_url: str | None = None
    scope: str
    scope_description: str
    status: str
    granted_at: str
    expires_at: str | None = None
    revoked_at: str | None = None


@router.get(
    "",
    response_model=list[ConsentItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Get all connected app permissions for the authenticated user",
)
def get_my_consents(
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> list[ConsentItemResponse]:
    from backend.main import get_repo
    repo = get_repo()
    username = normalize_username(current_user.username)
    raw = repo.get_user_consents(username=username)
    return [ConsentItemResponse(**item) for item in raw]


@router.get(
    "/scopes",
    response_model=list[ScopeItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Get full scope catalogue with human-readable descriptions",
)
def get_scope_catalogue() -> list[ScopeItemResponse]:
    return [ScopeItemResponse(**item) for item in SCOPE_CATALOGUE]


@router.delete(
    "/{consent_id}",
    status_code=status.HTTP_200_OK,
    summary="Revoke a single consent scope by consent_id",
)
def revoke_consent(
    consent_id: str,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> dict[str, Any]:
    from backend.main import get_repo
    repo = get_repo()
    username = normalize_username(current_user.username)
    success = repo.revoke_user_consent(username=username, consent_id=consent_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Consent record '{consent_id}' not found for user.",
        )
    return {"message": f"Consent '{consent_id}' has been revoked.", "status": "REVOKED"}


@router.delete(
    "/apps/{app_id}",
    status_code=status.HTTP_200_OK,
    summary="Revoke all active permissions granted to a third-party application",
)
def disconnect_app(
    app_id: str,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> dict[str, Any]:
    from backend.main import get_repo
    repo = get_repo()
    username = normalize_username(current_user.username)
    success = repo.revoke_user_app_consents(username=username, app_id=app_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active consents found for application '{app_id}'.",
        )
    return {"message": f"All permissions for application '{app_id}' have been revoked.", "status": "DISCONNECTED"}
