"""
Admin Dashboard API Routes
Layer: 🔵 LAYER 4 — Presentation / API Routers
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from backend.domain.models.admin import ActivityItem, DashboardStats
from backend.domain.models.admin_user import AdminUser
from backend.presentation.api_admin.auth_deps import get_current_admin_user, require_admin

router = APIRouter(prefix="/dashboard", tags=["Admin — Dashboard & Analytics"])


@router.get(
    "/stats",
    response_model=DashboardStats,
    status_code=status.HTTP_200_OK,
    summary="Get Dashboard Stats",
    description="Returns high-level KPI stat cards for total users, developers, bank rails, and transactions.",
)
def get_dashboard_stats(
    admin: AdminUser = Depends(get_current_admin_user),
) -> DashboardStats:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    return service.get_dashboard_stats()


@router.get(
    "/activity",
    response_model=dict[str, list[ActivityItem]],
    status_code=status.HTTP_200_OK,
    summary="Get Recent Activity Feed",
    description="Returns recent system activity feed items.",
)
def get_activity_feed(
    limit: int = Query(default=20, ge=1, le=100),
    admin: AdminUser = Depends(get_current_admin_user),
) -> dict[str, list[ActivityItem]]:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    items = service.get_activity_feed(limit=limit)
    return {"items": items}
