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

router = APIRouter(prefix="/callbacks", tags=["🔔 Webhooks & Callbacks"])


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
    from backend.main import get_pis_service
    from backend.presentation.api_v1.payments import _payment_store

    payment = _payment_store.get(body.payment_id)
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment '{body.payment_id}' not found.",
        )

    pis = get_pis_service()
    try:
        final_payment = pis.process_callback(
            payment=payment,
            bank_confirmed=body.confirmed,
            failure_reason=body.failure_reason,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    _payment_store[body.payment_id] = final_payment

    # TODO: enqueue async POST to the TPP's webhook_url.
    if final_payment.webhook_url:
        pass

    return CallbackAcknowledgement(
        payment_id=final_payment.payment_id,
        final_status=final_payment.status.value,
        message=f"Payment finalized with status {final_payment.status.value}.",
    )
