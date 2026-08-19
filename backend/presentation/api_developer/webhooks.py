"""
Developer Portal Webhook Inspector & Manual Retry Endpoints
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)

Allows authenticated developers to inspect real-time webhook delivery logs,
review HTTP response codes and payloads, and trigger manual test retries.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.presentation.api_developer.auth_deps import (
    DeveloperPrincipal,
    get_current_developer,
)

router = APIRouter(prefix="/developer", tags=["Developer Portal — Webhook Inspector"])


@router.get(
    "/apps/{app_id}/webhooks",
    status_code=status.HTTP_200_OK,
    summary="Get recent webhook delivery logs for an application",
)
def list_app_webhooks(
    app_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        logs = service.list_app_webhooks(
            developer_id=principal.developer_id,
            app_id=app_id,
            limit=limit,
        )
        return {"webhook_events": logs}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/webhooks/{event_id}/retry",
    status_code=status.HTTP_200_OK,
    summary="Manually retry a webhook event delivery",
)
def retry_webhook(
    event_id: str,
    principal: DeveloperPrincipal = Depends(get_current_developer),
) -> dict[str, Any]:
    from backend.main import get_developer_auth_service
    service = get_developer_auth_service()
    try:
        res = service.retry_webhook_event(
            developer_id=principal.developer_id,
            event_id=event_id,
        )
        return res
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
