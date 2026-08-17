"""
Admin Developers & Merchants API Routes
Layer: 🔵 LAYER 4 — Presentation / API Routers
"""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.domain.models.admin import (
    DeveloperApp,
    KYBRequest,
    KYBStatus,
    Merchant,
    MerchantStats,
    MerchantTxnStats,
    WebhookLog,
)
from backend.domain.models.admin_user import AdminUser
from backend.presentation.api_admin.auth_deps import get_current_admin_user, require_admin

router = APIRouter(prefix="/developers", tags=["Admin — Developers & Merchants"])


class ReviewKYBPayload(BaseModel):
    status: KYBStatus = Field(..., description="Approved or Rejected status.")
    review_note: str | None = Field(default=None, description="Admin review notes.")


class ReviewKYBResponse(BaseModel):
    success: bool = True
    kyb_id: str
    status: KYBStatus
    message: str = "KYB request reviewed successfully."


class MerchantTxnItem(BaseModel):
    merchant_transaction_id: str
    merchant_id: str
    merchant_name: str
    customer_name: str
    amount: float
    currency: str = "ETB"
    status: str = "SUCCESS"
    created_at: datetime


@router.get(
    "/merchants",
    response_model=dict[str, list[Merchant]],
    status_code=status.HTTP_200_OK,
    summary="List Registered Merchants",
)
def list_merchants(
    admin: AdminUser = Depends(get_current_admin_user),
) -> dict[str, list[Merchant]]:
    from backend.main import get_admin_merchant_service
    service = get_admin_merchant_service()
    merchants = service.list_merchants()
    return {"merchants": merchants}


@router.get(
    "/merchants/stats",
    response_model=MerchantStats,
    status_code=status.HTTP_200_OK,
    summary="Get Merchant Stats",
)
def get_merchant_stats(
    admin: AdminUser = Depends(get_current_admin_user),
) -> MerchantStats:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    return service.get_merchant_stats()


@router.get(
    "/merchant-transactions",
    response_model=dict[str, list[MerchantTxnItem]],
    status_code=status.HTTP_200_OK,
    summary="List Merchant Transactions",
)
def list_merchant_transactions(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    admin: AdminUser = Depends(get_current_admin_user),
) -> dict[str, list[MerchantTxnItem]]:
    now = datetime.now(tz=timezone.utc)
    txs = [
        MerchantTxnItem(
            merchant_transaction_id="mtxn_8f92b1a",
            merchant_id="mer_1234",
            merchant_name="Zemen Fintech PLC",
            customer_name="Abebe Girma Tadesse",
            amount=4500.00,
            currency="ETB",
            status="SUCCESS",
            created_at=now,
        )
    ]
    return {"transactions": txs}


@router.get(
    "/merchant-transactions/stats",
    response_model=MerchantTxnStats,
    status_code=status.HTTP_200_OK,
    summary="Get Merchant Transaction Stats",
)
def get_merchant_txn_stats(
    admin: AdminUser = Depends(get_current_admin_user),
) -> MerchantTxnStats:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    return service.get_merchant_txn_stats()


@router.get(
    "/apps",
    response_model=dict[str, list[DeveloperApp]],
    status_code=status.HTTP_200_OK,
    summary="List Developer Applications",
)
def list_developer_apps(
    admin: AdminUser = Depends(get_current_admin_user),
) -> dict[str, list[DeveloperApp]]:
    from backend.main import get_admin_merchant_service
    service = get_admin_merchant_service()
    apps = service.list_apps()
    return {"applications": apps}


@router.get(
    "/kyb-requests",
    response_model=dict[str, list[KYBRequest]],
    status_code=status.HTTP_200_OK,
    summary="List KYB Requests",
)
def list_kyb_requests(
    admin: AdminUser = Depends(get_current_admin_user),
) -> dict[str, list[KYBRequest]]:
    from backend.main import get_admin_merchant_service
    service = get_admin_merchant_service()
    reqs = service.list_kyb_requests()
    return {"kyb_requests": reqs}


@router.put(
    "/kyb-requests/{kyb_id}",
    response_model=ReviewKYBResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve or Reject KYB Request",
)
def review_kyb_request(
    kyb_id: str,
    body: ReviewKYBPayload,
    admin: AdminUser = Depends(require_admin),
) -> ReviewKYBResponse:
    from backend.main import get_admin_merchant_service
    service = get_admin_merchant_service()
    try:
        updated = service.review_kyb_request(
            kyb_id=kyb_id,
            status=body.status.value,
            note=body.review_note,
            actor_email=admin.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return ReviewKYBResponse(
        kyb_id=kyb_id,
        status=updated.status,
        message=f"KYB request '{kyb_id}' updated to {updated.status.value}.",
    )


@router.get(
    "/webhooks",
    response_model=dict[str, list[WebhookLog]],
    status_code=status.HTTP_200_OK,
    summary="List Webhook Deliveries Log",
)
def list_webhooks(
    limit: int = Query(default=50, ge=1, le=100),
    admin: AdminUser = Depends(get_current_admin_user),
) -> dict[str, list[WebhookLog]]:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    logs = service.list_webhooks(limit=limit)
    return {"webhooks": logs}
