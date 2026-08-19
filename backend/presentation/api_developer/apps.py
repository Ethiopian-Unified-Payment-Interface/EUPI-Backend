"""
Developer Portal App & Key Management Endpoints
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)

Allows authenticated developers to manage their applications, configure redirect URIs
and webhook URLs, and securely rotate client secrets.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.presentation.api_developer.auth_deps import (
    DeveloperPrincipal,
    get_current_developer,
)

router = APIRouter(prefix="/developer/apps", tags=["Developer Portal — Application Management"])


# ── Request / Response Schemas ────────────────────────────────────────────────

class CreateAppPayload(BaseModel):
    app_name: str = Field(..., min_length=2, max_length=100, examples=["EthioPay Mobile Checkout"])
    redirect_uris: list[str] | None = Field(
        default=["https://localhost:3000/callback"],
        description="Allowed OAuth2 authorization callback URIs.",
    )
    webhook_url: str | None = Field(default=None, description="HTTPS endpoint to receive payment settlement webhooks.")


class UpdateAppPayload(BaseModel):
    app_name: str | None = Field(default=None, min_length=2, max_length=100)
    redirect_uris: list[str] | None = None
    webhook_url: str | None = None


# ── Route Handlers ────────────────────────────────────────────────────────────

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="List all applications for the authenticated developer",
)
def list_apps(
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    apps = service.list_apps(principal.developer_id)
    return {"apps": apps}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new developer application",
    description="Creates a new application. Returns the plaintext client_secret ONCE.",
)
def create_app(
    body: CreateAppPayload,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        res = service.create_app(
            developer_id=principal.developer_id,
            app_name=body.app_name,
            redirect_uris=body.redirect_uris,
            webhook_url=body.webhook_url,
        )
        return res
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/{app_id}",
    status_code=status.HTTP_200_OK,
    summary="Get application details",
)
def get_app(
    app_id: str,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        return service.get_app(developer_id=principal.developer_id, app_id=app_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.put(
    "/{app_id}",
    status_code=status.HTTP_200_OK,
    summary="Update application settings",
)
def update_app(
    app_id: str,
    body: UpdateAppPayload,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        return service.update_app(
            developer_id=principal.developer_id,
            app_id=app_id,
            app_name=body.app_name,
            redirect_uris=body.redirect_uris,
            webhook_url=body.webhook_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/{app_id}/rotate-secret",
    status_code=status.HTTP_200_OK,
    summary="Rotate application client secret",
    description="Generates a new client_secret and returns it ONCE. The previous secret is immediately invalidated.",
)
def rotate_secret(
    app_id: str,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        return service.rotate_client_secret(
            developer_id=principal.developer_id,
            app_id=app_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete(
    "/{app_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete application",
)
def delete_app(
    app_id: str,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        service.delete_app(developer_id=principal.developer_id, app_id=app_id)
        return {"success": True, "message": f"Application '{app_id}' deleted successfully."}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
