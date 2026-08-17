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
    pin: str = Field(
        ...,
        min_length=4,
        max_length=12,
        description=(
            "The sender's transaction PIN, re-entered to authorise this "
            "transfer. This is the payer's consent — a session token alone is "
            "deliberately not sufficient to move money."
        ),
        examples=["123456"],
    )
    client_reference: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional idempotency key. Send the same value when retrying and a "
            "duplicate submission is rejected instead of sending twice."
        ),
        examples=["app-txn-8f21c4"],
    )


# ── Route Handler ──────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send Money by Username",
    description=(
        "**Handle-Based P2P Transfer, authorised by the sender's PIN**\n\n"
        "Resolves the recipient by username, takes the sender's default *sending* "
        "account and the recipient's default *receiving* account, checks the "
        "balance, and runs the full PIS lifecycle — so the payment is submitted "
        "to the bank by the time this returns, in `ORDERED` status awaiting the "
        "bank's settlement callback.\n\n"
        "The `pin` field is required and is the payer's consent. The PIN is "
        "verified against the same argon2 hash and lockout counters as login, "
        "and a short-lived consent token derived from it drives the PIS flow. A "
        "session token by itself does not authorise a payment: it is a bearer "
        "credential valid for an hour, and accepting it would let a leaked token "
        "drain the account.\n\n"
        "Send `client_reference` and repeat it on retry to make the call idempotent."
    ),
)
def initiate_transfer(
    body: P2PTransferRequest,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> PaymentResponse:
    from backend.application.use_cases.user_registration_service import (
        InvalidPINError,
        PINLockedError,
    )
    from backend.domain.models.user import normalize_username
    from backend.main import get_repo, get_superapp_transfer_service

    service = get_superapp_transfer_service()
    repo = get_repo()

    if normalize_username(current_user.username) != normalize_username(body.sender_username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot initiate transfer on behalf of another user.",
        )

    # Idempotency, checked before anything happens.
    #
    # The unique constraint on end_to_end_id would also catch a duplicate, but
    # only at INSERT — by which point send_money has already ordered the payment
    # at the bank. A double-tapped button would therefore send the money twice
    # and merely fail to record the second. Returning the original payment here
    # is what actually makes a retry safe.
    if body.client_reference:
        existing = repo.get_payment_by_end_to_end_id(f"P2P-REF-{body.client_reference}")
        if existing is not None:
            return _payment_to_response(existing)

    try:
        payment = service.send_money(
            sender_username=body.sender_username,
            recipient_username=body.recipient_username,
            amount=body.amount,
            pin=body.pin,
            currency=body.currency,
            remittance_info=body.remittance_info,
            client_reference=body.client_reference,
        )
    except PINLockedError as exc:
        # 429 so the client shows a wait-and-retry state rather than prompting
        # for the PIN again, which would burn another attempt.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        )
    except InvalidPINError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _payment_store[payment.payment_id] = payment
    repo.save_payment(payment)

    return _payment_to_response(payment)
