"""
Admin Customers & Transactions API Routes
Layer: Blue LAYER 4 — Presentation / API Routers
"""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from backend.domain.models.admin import CustomerStats, TransactionStats
from backend.presentation.api_admin.auth_deps import get_current_admin_user

router = APIRouter(prefix="/users", tags=["Admin — Customers & Transactions"])


class CustomerItem(BaseModel):
    customer_id: str
    username: str
    fin: str
    full_name: str
    phone_number: str
    state: str = "ACTIVE"
    kyc_level: str = "STANDARD"
    created_at: datetime


class CustomerListResponse(BaseModel):
    customers: list[CustomerItem]
    page: int
    limit: int
    total: int


class AdminTransactionItem(BaseModel):
    payment_id: str
    end_to_end_id: str
    debtor_account_number: str
    creditor_account_number: str
    sender_name: str
    recipient_name: str
    amount: float
    currency: str = "ETB"
    status: str
    routed_bank_id: str
    fee_etb: float = 2.50
    created_at: datetime


class TransactionListResponse(BaseModel):
    transactions: list[AdminTransactionItem]
    page: int
    limit: int
    total: int


@router.get(
    "/customers",
    response_model=CustomerListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Customers (Endpoint Users)",
)
def list_customers(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    admin: dict = Depends(get_current_admin_user),
) -> CustomerListResponse:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    raw_customers, total = service.list_customers(page=page, limit=limit)
    customers = [CustomerItem(**c) for c in raw_customers]

    return CustomerListResponse(
        customers=customers,
        page=page,
        limit=limit,
        total=total,
    )


@router.get(
    "/customers/stats",
    response_model=CustomerStats,
    status_code=status.HTTP_200_OK,
    summary="Get Customer Stats",
)
def get_customer_stats(
    admin: dict = Depends(get_current_admin_user),
) -> CustomerStats:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    return service.get_customer_stats()


@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List System-Wide Transactions",
)
def list_transactions(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    admin: dict = Depends(get_current_admin_user),
) -> TransactionListResponse:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    raw_txs, total = service.list_transactions(page=page, limit=limit)
    txs = [AdminTransactionItem(**t) for t in raw_txs]

    return TransactionListResponse(
        transactions=txs,
        page=page,
        limit=limit,
        total=total,
    )


@router.get(
    "/transactions/stats",
    response_model=TransactionStats,
    status_code=status.HTTP_200_OK,
    summary="Get Transaction Stats",
)
def get_transaction_stats(
    admin: dict = Depends(get_current_admin_user),
) -> TransactionStats:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    return service.get_transaction_stats()
