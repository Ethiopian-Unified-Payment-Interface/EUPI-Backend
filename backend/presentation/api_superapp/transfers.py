"""
Presentation Layer: Super App P2P Transfer Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.presentation.api_v1.payments import (
    PaymentResponse,
    _payment_store,
    _payment_to_response,
)

router = APIRouter(prefix="/superapp/transfers", tags=["Super App — P2P Transfers"])


# ── Request Schema ─────────────────────────────────────────────────────────────

class P2PTransferRequest(BaseModel):
    """Payload to initiate a handle-based peer-to-peer money transfer."""

    sender_user_id: str = Field(
        ...,
        description="Sender's Super App user ID.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    recipient_username: str = Field(
        ...,
        description="Recipient's unique handle (looked up to find their default receiving account).",
        examples=["selamawit_b"],
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        description="Transfer amount in ETB.",
        examples=["500.00"],
    )
    currency: str = Field(
        default="ETB",
        description="ISO currency code.",
        examples=["ETB"],
    )
    remittance_info: str | None = Field(
        default=None,
        description="Optional payment description or note.",
        examples=["Lunch split"],
    )


# ── Route Handler ──────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send Money by Username",
    description=(
        "**Handle-Based P2P Transfer**\n\n"
        "Resolves the recipient by username, finds the sender's default sending account "
        "and the recipient's default receiving account, selects the optimal banking rail "
        "via Smart Router, and creates a Payment object in `PENDING` state.\n\n"
        "The resulting payment follows the standard PIS lifecycle "
        "(verify → order → callback) for settlement."
    ),
)
def initiate_transfer(body: P2PTransferRequest) -> PaymentResponse:
    from backend.main import get_superapp_transfer_service, get_repo
    service = get_superapp_transfer_service()
    repo = get_repo()

    try:
        payment = service.initiate_transfer(
            sender_user_id=body.sender_user_id,
            recipient_username=body.recipient_username,
            amount=body.amount,
            currency=body.currency,
            remittance_info=body.remittance_info,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _payment_store[payment.payment_id] = payment
    repo.save_payment(payment)

    return _payment_to_response(payment)
