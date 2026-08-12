"""
Presentation Layer: Payment Routes — POST /v1/payments/*
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)

Payments are persisted to SQLite via SQLiteRepository. An in-memory dict
serves as a fast lookup cache; SQLite is the source of truth and restores
the cache on server restart (via main.py lifespan).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/payments", tags=["Payment Initiation (PIS)"])
_bearer = HTTPBearer()

# In-memory cache — populated from SQLite on startup via main.py lifespan
_payment_store: dict = {}


# ── Request / Response schemas ─────────────────────────────────────────────────

class PaymentInitiateBody(BaseModel):
    debtor_account_number: str = Field(..., examples=["1000234567890"])
    debtor_bank_id: str = Field(..., examples=["COOP"])
    creditor_account_number: str = Field(..., examples=["1000987654321"])
    creditor_bank_id: str = Field(..., examples=["CBE"])
    creditor_name: str = Field(..., examples=["Selam Tesfaye"])
    amount: Decimal = Field(..., gt=0, examples=["2500.00"])
    currency: str = Field(default="ETB")
    end_to_end_id: str = Field(..., examples=["TPP-REF-20251101-00456"])
    remittance_info: str | None = Field(default=None, examples=["Invoice #INV-2025-001"])
    webhook_url: str | None = Field(default=None, examples=["https://tpp.example.com/callback"])


class PaymentVerifyBody(BaseModel):
    consent_token: str = Field(..., description="Signed gateway JWT from /auth/fayda/confirm.")


class PaymentCancelBody(BaseModel):
    reason: str = Field(default="Customer requested cancellation.")


class PaymentResponse(BaseModel):
    payment_id: str
    status: str
    selected_rail: str | None
    bank_order_reference: str | None
    failure_reason: str | None
    amount: Decimal
    currency: str
    debtor_bank_id: str
    creditor_bank_id: str
    creditor_name: str
    created_at: datetime
    updated_at: datetime


def _payment_to_response(payment) -> PaymentResponse:
    req = payment.initiate_request
    return PaymentResponse(
        payment_id=payment.payment_id,
        status=payment.status.value,
        selected_rail=payment.selected_rail.value if payment.selected_rail else None,
        bank_order_reference=payment.bank_order_reference,
        failure_reason=payment.failure_reason,
        amount=req.amount,
        currency=req.currency,
        debtor_bank_id=req.debtor_bank_id,
        creditor_bank_id=req.creditor_bank_id,
        creditor_name=req.creditor_name,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/initiate",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Step 1 — Initiate a payment (→ PENDING)",
    description=(
        "Creates a new payment object. The Smart Router selects the optimal rail "
        "based on live health checks, rolling uptime, latency, and transaction cost."
    ),
)
def initiate_payment(
    body: PaymentInitiateBody,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> PaymentResponse:
    from backend.main import get_pis_service, get_repo
    from backend.domain.models.payment import PaymentInitiateRequest
    pis = get_pis_service()
    repo = get_repo()
    req = PaymentInitiateRequest(**body.model_dump(exclude={"webhook_url"}))
    try:
        payment = pis.initiate_payment(request=req, webhook_url=body.webhook_url)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _payment_store[payment.payment_id] = payment
    # Catch duplicate end_to_end_id to return 409 instead of 500.
    try:
        repo.save_payment(payment)
    except IntegrityError:
        del _payment_store[payment.payment_id]  # roll back in-memory state too
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A payment with end_to_end_id '{req.end_to_end_id}' already exists. "
                   "Use a unique end_to_end_id for each payment (idempotency key).",
        )
    return _payment_to_response(payment)


@router.post(
    "/{payment_id}/verify",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Step 2 — Verify consent (→ VERIFIED)",
    description=(
        "Validates the customer's signed gateway JWT (from /auth/fayda/confirm). "
        "Performs full JWT signature + expiry + revocation check. "
        "Requires STANDARD KYC level."
    ),
)
def verify_payment(payment_id: str, body: PaymentVerifyBody) -> PaymentResponse:
    from backend.main import get_pis_service, get_repo
    payment = _get_or_404(payment_id)
    pis = get_pis_service()
    repo = get_repo()
    try:
        updated = pis.verify_payment(payment=payment, consent_token=body.consent_token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    _payment_store[payment_id] = updated
    repo.update_payment(updated)
    return _payment_to_response(updated)


@router.post(
    "/{payment_id}/order",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Step 3 — Submit order to bank rail (→ ORDERED)",
    description=(
        "Submits the debit instruction to the CBS adapter for the selected rail. "
        "Returns ORDERED on success or FAILED (with reason) on bank rejection."
    ),
)
def order_payment(payment_id: str) -> PaymentResponse:
    from backend.main import get_pis_service, get_repo
    payment = _get_or_404(payment_id)
    pis = get_pis_service()
    repo = get_repo()
    try:
        updated = pis.order_payment(payment=payment)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    _payment_store[payment_id] = updated
    repo.update_payment(updated)
    return _payment_to_response(updated)


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get payment status",
    description="Returns the current lifecycle state of a payment. Falls back to SQLite if not in cache.",
)
def get_payment(payment_id: str) -> PaymentResponse:
    # Try cache first, then DB
    payment = _payment_store.get(payment_id)
    if not payment:
        from backend.main import get_repo
        payment = get_repo().get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Payment '{payment_id}' not found.")
    return _payment_to_response(payment)


@router.post(
    "/{payment_id}/cancel",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a PENDING or VERIFIED payment",
    description="Cancels a payment before the ORDER step. Terminal states cannot be cancelled.",
)
def cancel_payment(payment_id: str, body: PaymentCancelBody) -> PaymentResponse:
    from backend.main import get_pis_service, get_repo
    payment = _get_or_404(payment_id)
    pis = get_pis_service()
    repo = get_repo()
    try:
        updated = pis.cancel_payment(payment=payment, reason=body.reason)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    _payment_store[payment_id] = updated
    repo.update_payment(updated)
    return _payment_to_response(updated)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_or_404(payment_id: str):
    payment = _payment_store.get(payment_id)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Payment '{payment_id}' not found.")
    return payment
