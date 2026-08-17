"""
Super App Consent Management API Routes
Layer: 🔵 LAYER 4 — Presentation / API Routers

The screen where a person sees what they have shared and takes it back.

A consent framework a user cannot inspect and reverse in one action is not
consent, so these routes are part of the privacy design rather than an
administrative afterthought.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.application.use_cases.consent_service import (
    ConsentNotFoundError,
)
from backend.domain.models.consent import ConsentScope
from backend.domain.models.user import SuperAppUser
from backend.presentation.api_superapp.auth_deps import get_current_superapp_user

router = APIRouter(prefix="/superapp/consents", tags=["Super App — Consent & Privacy"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class ConsentItem(BaseModel):
    consent_id: str
    app_id: str
    scope: str
    scope_description: str = Field(
        ..., description="Plain-language explanation shown to the user."
    )
    status: str = Field(..., description="GRANTED, REVOKED, or EXPIRED.")
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class ConsentListResponse(BaseModel):
    consents: list[ConsentItem]
    total: int


class ScopeCatalogueItem(BaseModel):
    scope: str
    description: str
    restricted: bool = Field(
        ...,
        description="Restricted scopes require a licensing review and are never self-service.",
    )


class MessageResponse(BaseModel):
    message: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=ConsentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List My Consents",
    description=(
        "**Everything you have shared, and with whom.**\n\n"
        "Returns every grant this account has made to any application, including "
        "those already revoked or expired, so the history is auditable by the "
        "person it concerns."
    ),
)
def list_my_consents(
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> ConsentListResponse:
    from backend.main import get_consent_service

    grants = get_consent_service().list_user_consents(current_user.username)

    return ConsentListResponse(
        consents=[
            ConsentItem(
                consent_id=c.consent_id,
                app_id=c.app_id,
                scope=c.scope.value,
                scope_description=c.scope.description,
                # effective_status, not the stored value: a grant past its
                # expiry reads as EXPIRED even though the row still says GRANTED.
                status=c.effective_status.value,
                granted_at=c.granted_at,
                expires_at=c.expires_at,
                revoked_at=c.revoked_at,
            )
            for c in grants
        ],
        total=len(grants),
    )


@router.delete(
    "/{consent_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke a Consent",
    description=(
        "**Withdraw one permission.** Takes effect immediately — the next "
        "request from that application will no longer receive the field."
    ),
)
def revoke_consent(
    consent_id: str,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> MessageResponse:
    from backend.main import get_consent_service

    try:
        get_consent_service().revoke(consent_id, current_user.username)
    except ConsentNotFoundError as exc:
        # Same response whether the grant is missing or belongs to someone
        # else, so this cannot be used to probe for other users' consent IDs.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return MessageResponse(message="Permission withdrawn.")


@router.delete(
    "/apps/{app_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Disconnect an Application",
    description=(
        "**Withdraw every permission held by one application, in one action.**\n\n"
        "Revoking scopes one at a time risks leaving one behind; disconnecting "
        "should not depend on the user being thorough."
    ),
)
def disconnect_app(
    app_id: str,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> MessageResponse:
    from backend.main import get_consent_service

    revoked = get_consent_service().disconnect_app(current_user.username, app_id)
    return MessageResponse(
        message=f"Disconnected. {revoked} permission(s) withdrawn."
    )


@router.get(
    "/scopes",
    response_model=list[ScopeCatalogueItem],
    status_code=status.HTTP_200_OK,
    summary="Scope Catalogue",
    description=(
        "The permissions an application can request, with the plain-language "
        "wording shown on the consent screen."
    ),
)
def list_scopes() -> list[ScopeCatalogueItem]:
    return [
        ScopeCatalogueItem(
            scope=scope.value,
            description=scope.description,
            restricted=scope.is_restricted,
        )
        for scope in ConsentScope
    ]
