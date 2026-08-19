"""
Developer Portal Transaction Explorer & Analytics Endpoints
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)

Allows authenticated developers to search tenant-scoped payments, inspect telemetry
analytics, and review active consent grant distributions with zero PII exposure.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.presentation.api_developer.auth_deps import (
    DeveloperPrincipal,
    get_current_developer,
)

router = APIRouter(prefix="/developer", tags=["Developer Portal — Explorer & Analytics"])


@router.get(
    "/apps/{app_id}/payments",
    status_code=status.HTTP_200_OK,
    summary="Search tenant-scoped payments for an application",
)
def list_app_payments(
    app_id: str,
    status_filter: str | None = Query(default=None, alias="status", description="Optional filter: PENDING, ORDERED, SUCCESS, FAILED"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        return service.list_app_payments(
            developer_id=principal.developer_id,
            app_id=app_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/apps/{app_id}/analytics",
    status_code=status.HTTP_200_OK,
    summary="Get application transaction metrics and volume analytics",
)
def get_app_analytics(
    app_id: str,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        return service.get_app_analytics(
            developer_id=principal.developer_id,
            app_id=app_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/apps/{app_id}/consents",
    status_code=status.HTTP_200_OK,
    summary="Get active consent grants summary and pseudonym distribution",
    description="Returns active consent grant breakdown. Zero citizen PII is exposed.",
)
def get_app_consents(
    app_id: str,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        return service.get_app_consents_summary(
            developer_id=principal.developer_id,
            app_id=app_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
