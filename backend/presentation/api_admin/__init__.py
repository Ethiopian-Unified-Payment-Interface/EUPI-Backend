"""
Admin API Router Package
Layer: 🔵 LAYER 4 — Presentation / API Routers
"""

from fastapi import APIRouter

from backend.presentation.api_admin.audit import router as audit_router
from backend.presentation.api_admin.banks import router as banks_router
from backend.presentation.api_admin.customers import router as customers_router
from backend.presentation.api_admin.dashboard import router as dashboard_router
from backend.presentation.api_admin.merchants import router as merchants_router

admin_router = APIRouter(prefix="/v1/admin")

admin_router.include_router(dashboard_router)
admin_router.include_router(banks_router)
admin_router.include_router(customers_router)
admin_router.include_router(merchants_router)
admin_router.include_router(audit_router)
