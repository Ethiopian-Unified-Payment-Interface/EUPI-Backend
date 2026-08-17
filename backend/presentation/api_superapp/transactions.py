"""
Super App Transaction History API Routes
Layer: 🔵 LAYER 4 — Presentation / API Routers

The authenticated user's own payment history, assembled from the accounts they
have linked. Added so the app's activity list reflects real payments instead of
hardcoded placeholders.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.domain.models.user import SuperAppUser
from backend.presentation.api_superapp.auth_deps import get_current_superapp_user

router = APIRouter(prefix="/superapp/transactions", tags=["Super App — Transactions"])


class TransactionItem(BaseModel):
    payment_id: str
    end_to_end_id: str
    counterparty_name: str = Field(
        ..., description="The other side of the payment, from this user's perspective."
    )
    amount: Decimal
    currency: str
    status: str
    is_credit: bool = Field(
        ...,
        description="True when money came in, false when it went out.",
    )
    bank_id: str = Field(
        ...,
        description=(
            "The bank holding this user's account for this payment — not the "
            "rail the Smart Router selected. Answers 'which of my accounts "
            "moved?', which is what a transaction history is for."
        ),
    )
    masked_account: str = Field(
        ..., description="This user's account, masked to the last four digits."
    )
    remittance_info: str | None
    created_at: datetime


class TransactionListResponse(BaseModel):
    transactions: list[TransactionItem]
    total: int


@router.get(
    "",
    response_model=TransactionListResponse,
    status_code=status.HTTP_200_OK,
    summary="My Transaction History",
    description=(
        "**Payments involving this user's linked accounts.**\n\n"
        "Direction is resolved per payment: a transfer out of a linked account "
        "is a debit, one into it is a credit. A user with no linked accounts "
        "gets an empty list, never another user's history."
    ),
)
def list_my_transactions(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> TransactionListResponse:
    from backend.domain.pii import mask_account_number
    from backend.main import get_account_linking_service, get_repo

    links = get_account_linking_service().list_linked_accounts(current_user.username)
    account_numbers = [link.account_number for link in links]

    # No linked accounts means no history. The repository returns an empty
    # list rather than an unfiltered query, so this cannot degrade into
    # "every payment on the platform".
    payments = get_repo().list_payments_for_accounts(account_numbers, limit=limit)

    owned = set(account_numbers)
    items: list[TransactionItem] = []

    for payment in payments:
        request = payment.initiate_request
        is_credit = request.creditor_account_number in owned

        # The account this user owns, and the party on the other side.
        own_account = (
            request.creditor_account_number if is_credit else request.debtor_account_number
        )

        # Outgoing payments carry the beneficiary's name, so show it. Incoming
        # ones do not — PaymentRecord stores `creditor_name` but no debtor
        # name — so the only available identifier is the sender's account
        # number, and that is masked rather than shown in full. Displaying
        # another party's complete account number to a user is a disclosure
        # they never consented to, and it is enough to attempt a transfer with.
        #
        # Resolving incoming payments to a sender name needs a debtor_name on
        # PaymentRecord; until then a masked account is the honest answer.
        counterparty = (
            f"From {mask_account_number(request.debtor_account_number)}"
            if is_credit
            else request.creditor_name
        )

        items.append(
            TransactionItem(
                payment_id=payment.payment_id,
                end_to_end_id=request.end_to_end_id,
                counterparty_name=counterparty,
                amount=request.amount,
                currency=request.currency,
                status=payment.status.value,
                is_credit=is_credit,
                # The bank holding *this user's* account, not the rail the
                # Smart Router picked to carry the payment.
                #
                # Reporting `selected_rail` here answered the wrong question: a
                # transfer out of a CBE account routed over COOP appeared in the
                # sender's own history as "COOP", so the history disagreed with
                # the account the send screen said it was debiting. The routed
                # rail is an implementation detail of settlement; what a user
                # needs to know is which of their accounts moved.
                bank_id=(
                    request.creditor_bank_id if is_credit else request.debtor_bank_id
                ),
                masked_account=mask_account_number(own_account),
                remittance_info=request.remittance_info,
                created_at=payment.created_at,
            )
        )

    return TransactionListResponse(transactions=items, total=len(items))
