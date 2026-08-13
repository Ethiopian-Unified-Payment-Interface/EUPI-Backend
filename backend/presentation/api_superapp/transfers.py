"""
Presentation Layer: Super App P2P Transfer Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.domain.models.user import SuperAppUser
from backend.presentation.api_superapp.auth_deps import get_current_superapp_user
from backend.presentation.api_v1.payments import (
    PaymentResponse,
    _payment_store,
    _payment_to_response,
)

router = APIRouter(prefix="/superapp/transfers", tags=["Super App — P2P Transfers"])


# ── Request Schema ─────────────────────────────────────────────────────────────

class P2PTransferRequest(BaseModel):
    """Payload to initiate a handle-based peer-to-peer money transfer."""

    sender_username: str = Field(
        ...,
        description="Sender's username handle (e.g. 'abebe_girma'). The @eupi postfix is automatically handled.",
        examples=["abebe_girma"],
    )
    recipient_username: str = Field(
        ...,
        description="Recipient's username handle (e.g. 'selamawit_b'). The @eupi postfix is automatically handled.",
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
        "Requires an active session header. Resolves the recipient by username, finds the sender's default sending account "
        "and the recipient's default receiving account, checks for sufficient balance in the sending account, selects the "
        "optimal banking rail via Smart Router, and creates a Payment object in `PENDING` state.\n\n"
        "The resulting payment follows the standard PIS lifecycle "
        "(verify → order → callback) for settlement."
    ),
)
def initiate_transfer(
    body: P2PTransferRequest,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> PaymentResponse:
    from backend.main import get_superapp_transfer_service, get_repo
    from backend.domain.models.user import normalize_username
    service = get_superapp_transfer_service()
    repo = get_repo()

    if normalize_username(current_user.username) != normalize_username(body.sender_username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot initiate transfer on behalf of another user.",
        )

    try:
        payment = service.initiate_transfer(
            sender_username=body.sender_username,
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
