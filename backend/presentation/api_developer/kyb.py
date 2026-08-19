"""
Developer Portal KYB Verification Pipeline Endpoints
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)

Allows authenticated developers to submit company business details and documents
for production compliance review, and track their verification state.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.presentation.api_developer.auth_deps import (
    DeveloperPrincipal,
    get_current_developer,
)

router = APIRouter(prefix="/developer", tags=["Developer Portal — KYB Verification"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SubmitKYBPayload(BaseModel):
    company_name: str = Field(..., min_length=2, examples=["EthioPay Solutions PLC"])
    tax_id: str = Field(..., min_length=5, examples=["TIN-0012345678"])
    requested_scopes: list[str] = Field(
        default=["accounts:read", "payments:initiate", "payments:read:own", "webhooks:receive"],
        description="Array of API scopes requested for production access.",
    )
    scope_justification: str | None = Field(
        default=None,
        description="Business justification required when requesting restricted scopes.",
    )


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/kyb-requests",
    status_code=status.HTTP_201_CREATED,
    summary="Submit KYB verification for production (live) credentials",
)
def submit_kyb(
    body: SubmitKYBPayload,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        res = service.submit_kyb_request(
            developer_id=principal.developer_id,
            company_name=body.company_name,
            tax_id=body.tax_id,
            requested_scopes=body.requested_scopes,
            scope_justification=body.scope_justification,
        )
        return res
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/kyb-status",
    status_code=status.HTTP_200_OK,
    summary="Get current KYB verification status and review notes",
)
def get_kyb_status(
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        return service.get_kyb_status(developer_id=principal.developer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
