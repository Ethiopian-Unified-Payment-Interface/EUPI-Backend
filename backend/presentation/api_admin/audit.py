"""
Admin Audit Log API Routes
Layer: 🔵 LAYER 4 — Presentation / API Routers
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from backend.domain.models.admin import AuditLog
from backend.domain.models.admin_user import AdminUser
from backend.presentation.api_admin.auth_deps import get_current_admin_user, require_admin

router = APIRouter(prefix="/audit-logs", tags=["Admin — Audit Logs"])


class AuditLogListResponse(BaseModel):
    logs: list[AuditLog]
    total: int


@router.get(
    "",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Administrative Audit Logs",
    description="Returns system audit trail logging configuration changes and KYB approvals.",
)
def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(get_current_admin_user),
) -> AuditLogListResponse:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    logs, total = service.list_audit_logs(limit=limit, offset=offset)
    return AuditLogListResponse(logs=logs, total=total)
