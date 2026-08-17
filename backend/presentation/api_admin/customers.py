"""
Admin Customers & Transactions API Routes
Layer: Blue LAYER 4 — Presentation / API Routers
"""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from backend.domain.models.admin import CustomerStats, TransactionStats
from backend.domain.models.admin_user import AdminUser
from backend.domain.pii import mask_account_number, mask_fin, mask_phone
from backend.presentation.api_admin.auth_deps import get_current_admin_user, require_admin

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
    pii_masked: bool = True


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
    reveal_pii: bool = Query(
        default=False,
        description=(
            "Return unmasked national ID and phone numbers. Requires the ADMIN "
            "role; every reveal is written to the audit log."
        ),
    ),
    admin: AdminUser = Depends(get_current_admin_user),
) -> CustomerListResponse:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    raw_customers, total = service.list_customers(page=page, limit=limit)

    # Masked unless an ADMIN explicitly asks. A READ_ONLY operator passing
    # reveal_pii=true silently gets masked values rather than a 403 — the list
    # is still useful to them, and there is nothing to escalate.
    unmask = reveal_pii and admin.role.can_reveal_pii
    if unmask:
        _audit_pii_reveal(admin, scope=f"customers page={page} limit={limit}")

    customers = [
        CustomerItem(
            **{
                **c,
                "fin": c["fin"] if unmask else mask_fin(c.get("fin")),
                "phone_number": (
                    c["phone_number"] if unmask else mask_phone(c.get("phone_number"))
                ),
            },
            pii_masked=not unmask,
        )
        for c in raw_customers
    ]

    return CustomerListResponse(
        customers=customers,
        page=page,
        limit=limit,
        total=total,
    )


def _audit_pii_reveal(admin: AdminUser, scope: str) -> None:
    """
    Record an unmasked-PII read in the audit trail.

    Best-effort: an audit backend problem must not deny an authorised operator
    their data, but it is logged loudly so the gap is visible.
    """
    import logging

    try:
        from backend.main import get_admin_analytics_service

        get_admin_analytics_service().record_audit_log(
            action="PII_REVEALED",
            actor_email=admin.email,
            details=f"Unmasked customer PII viewed: {scope}",
        )
    except Exception:  # noqa: BLE001 — never block the read on audit failure
        logging.getLogger(__name__).exception(
            "Failed to write PII reveal audit entry for %s", admin.email
        )


@router.get(
    "/customers/stats",
    response_model=CustomerStats,
    status_code=status.HTTP_200_OK,
    summary="Get Customer Stats",
)
def get_customer_stats(
    admin: AdminUser = Depends(get_current_admin_user),
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
    admin: AdminUser = Depends(get_current_admin_user),
) -> TransactionListResponse:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    raw_txs, total = service.list_transactions(page=page, limit=limit)

    # Account numbers are always masked here. Operations needs to identify a
    # transaction, not to be able to transcribe the accounts behind it.
    txs = [
        AdminTransactionItem(
            **{
                **t,
                "debtor_account_number": mask_account_number(
                    t.get("debtor_account_number")
                ),
                "creditor_account_number": mask_account_number(
                    t.get("creditor_account_number")
                ),
            }
        )
        for t in raw_txs
    ]

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
    admin: AdminUser = Depends(get_current_admin_user),
) -> TransactionStats:
    from backend.main import get_admin_analytics_service
    service = get_admin_analytics_service()
    return service.get_transaction_stats()
