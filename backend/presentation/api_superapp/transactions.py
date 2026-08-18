"""
Presentation Layer: Super App Transaction History Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.domain.models.user import SuperAppUser
from backend.presentation.api_superapp.auth_deps import get_current_superapp_user

router = APIRouter(
    prefix="/superapp/transactions",
    tags=["Super App — Transaction History"],
)


class TransactionItem(BaseModel):
    """A single transaction as seen from the Super App dashboard."""
    payment_id: str
    amount: Decimal
    currency: str = "ETB"
    status: str
    is_credit: bool
    counterparty_name: str | None = None
    counterparty_bank: str | None = None
    remittance_info: str | None = None
    created_at: datetime


class TransactionListResponse(BaseModel):
    transactions: list[TransactionItem]
    total: int


@router.get(
    "",
    response_model=TransactionListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get transaction history for the authenticated user",
    description=(
        "Returns recent P2P transfers where the authenticated user's linked accounts "
        "appear as sender or recipient. Requires active session. "
        "Results are sorted by most recent first."
    ),
)
def get_my_transactions(
    limit: int = Query(default=20, ge=1, le=100, description="Max number of transactions to return."),
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> TransactionListResponse:
    from backend.main import get_repo, get_account_linking_service
    from backend.domain.models.user import normalize_username

    repo = get_repo()
    link_service = get_account_linking_service()

    # Get all linked account numbers for this user
    username = normalize_username(current_user.username)
    links = link_service.list_linked_accounts(username=username)
    account_numbers = [link.account_number for link in links]

    if not account_numbers:
        return TransactionListResponse(transactions=[], total=0)

    raw = repo.get_payments_for_user(account_numbers=account_numbers, limit=limit)
    items = [TransactionItem(**row) for row in raw]
    return TransactionListResponse(transactions=items, total=len(items))
