"""
Presentation Layer: Webhook Routes — POST /v1/callbacks
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.

Receives async bank callbacks after the ORDER step and drives the
payment to its terminal state (SUCCESS or FAILED).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/callbacks", tags=["Webhooks & Callbacks"])


# ── Request / Response schemas ─────────────────────────────────────────────────

class BankCallbackBody(BaseModel):
    """Payload sent by a bank rail after processing an ORDER."""

    payment_id: str = Field(
        ...,
        description="The Kifiya Gateway payment ID from the ORDER step.",
        examples=["PAY-A1B2C3D4E5F6G7H8"],
    )
    bank_order_reference: str = Field(
        ...,
        description="The bank's own order reference for reconciliation.",
        examples=["COOP-ORD-20251101-007"],
    )
    confirmed: bool = Field(
        ...,
        description="True if the bank confirms a successful credit to the beneficiary.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Reason for failure if confirmed=false.",
        examples=["Beneficiary account closed"],
    )


class CallbackAcknowledgement(BaseModel):
    """Simple acknowledgement returned to the bank after processing the callback."""

    payment_id: str
    final_status: str
    message: str


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=CallbackAcknowledgement,
    status_code=status.HTTP_200_OK,
    summary="Receive bank callback — finalize payment (→ SUCCESS or FAILED)",
    description=(
        "Called asynchronously by bank adapters after the ORDER step is processed. "
        "Drives the payment to its terminal state and fires the TPP webhook "
        "if a `webhook_url` was provided at initiation."
    ),
)
def receive_bank_callback(body: BankCallbackBody) -> CallbackAcknowledgement:
    from backend.application.use_cases.payment_settlement_service import (
        ConflictingSettlementError,
        PaymentNotFoundError,
    )
    from backend.main import get_payment_settlement_service

    try:
        final_payment = get_payment_settlement_service().settle(
            payment_id=body.payment_id,
            bank_confirmed=body.confirmed,
            bank_order_reference=body.bank_order_reference,
            failure_reason=body.failure_reason,
        )
    except PaymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConflictingSettlementError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return CallbackAcknowledgement(
        payment_id=final_payment.payment_id,
        final_status=final_payment.status.value,
        message=f"Payment finalized with status {final_payment.status.value}.",
    )
