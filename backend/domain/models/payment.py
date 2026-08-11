"""
Domain Model: Payment
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.

Encodes the complete Payment Initiation Service (PIS) lifecycle as a state machine.
The 4-step flow is: PENDING → VERIFIED → ORDERED → SUCCESS (or FAILED/CANCELLED).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PaymentStatus(str, Enum):
    """
    PIS 4-step lifecycle state machine.

    Transitions:
        PENDING   — Payment object created; awaiting OTP/Fayda consent verification.
        VERIFIED  — Consent confirmed; cleared to proceed to fund reservation.
        ORDERED   — Debit order submitted to the originating bank rail.
        SUCCESS   — Credit confirmed on the destination account. Terminal state.
        FAILED    — Rejected by bank rail or router. Terminal state.
        CANCELLED — Revoked by the customer before ORDER step. Terminal state.
    """

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    ORDERED = "ORDERED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentRail(str, Enum):
    """The banking rail / network used to route the payment."""

    COOP = "COOP"
    CBE = "CBE"
    WEGAGEN = "WEGAGEN"
    AWASH = "AWASH"
    ETHIOPIAN_EFT = "ETHIOPIAN_EFT"  # National EFT interbank rail


class PaymentInitiateRequest(BaseModel):
    """
    Value object representing the data needed to initiate a new payment.
    Submitted by the TPP (Third-Party Provider) via the PIS endpoint.
    """

    debtor_account_number: str = Field(
        ...,
        description="Source account number from which funds will be debited.",
        examples=["1000234567890"],
    )
    debtor_bank_id: str = Field(
        ...,
        description="The originating bank rail BankID.",
        examples=["COOP"],
    )
    creditor_account_number: str = Field(
        ...,
        description="Destination account number to receive the credit.",
        examples=["1000987654321"],
    )
    creditor_bank_id: str = Field(
        ...,
        description="The destination bank rail BankID.",
        examples=["CBE"],
    )
    creditor_name: str = Field(
        ...,
        description="Full legal name of the payment beneficiary.",
        examples=["Selam Tesfaye"],
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        description="Payment amount (ETB). Must be positive.",
        examples=["2500.00"],
    )
    currency: str = Field(
        default="ETB",
        description="ISO 4217 currency code. ETB by default.",
    )
    end_to_end_id: str = Field(
        ...,
        description="TPP-assigned unique payment reference (idempotency key).",
        examples=["TPP-REF-20251101-00456"],
    )
    remittance_info: Optional[str] = Field(
        default=None,
        description="Optional free-text payment narration.",
        examples=["Invoice #INV-2025-001"],
    )


class Payment(BaseModel):
    """
    Unified Payment Domain Model — full PIS lifecycle entity.

    Created on INITIATE, mutated through VERIFY, ORDER, and terminal states.
    The smart router populates selected_rail after routing decision.
    """

    payment_id: str = Field(
        ...,
        description="Gateway-assigned unique payment identifier (ULID recommended).",
        examples=["01HZK5X3N8P7QRTYUVWZ234ABC"],
    )
    status: PaymentStatus = Field(
        default=PaymentStatus.PENDING,
        description="Current lifecycle state of the payment.",
    )
    initiate_request: PaymentInitiateRequest = Field(
        ...,
        description="The original initiation request payload; immutable after creation.",
    )
    selected_rail: Optional[PaymentRail] = Field(
        default=None,
        description="Bank rail selected by the Smart Router after routing evaluation.",
    )
    consent_token: Optional[str] = Field(
        default=None,
        description="Opaque Fayda consent token issued after OTP verification.",
    )
    bank_order_reference: Optional[str] = Field(
        default=None,
        description="Reference ID returned by the bank after the ORDER step.",
        examples=["COOP-ORD-20251101-007"],
    )
    failure_reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason for FAILED or CANCELLED status.",
        examples=["Insufficient funds"],
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="TPP-provided callback URL for async status notifications.",
        examples=["https://tpp.example.com/callbacks/payment"],
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the payment was first initiated.",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the most recent status transition.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "payment_id": "01HZK5X3N8P7QRTYUVWZ234ABC",
                "status": "PENDING",
                "initiate_request": {
                    "debtor_account_number": "1000234567890",
                    "debtor_bank_id": "COOP",
                    "creditor_account_number": "1000987654321",
                    "creditor_bank_id": "CBE",
                    "creditor_name": "Selam Tesfaye",
                    "amount": "2500.00",
                    "currency": "ETB",
                    "end_to_end_id": "TPP-REF-20251101-00456",
                    "remittance_info": "Invoice #INV-2025-001",
                },
                "selected_rail": "COOP",
                "consent_token": None,
                "bank_order_reference": None,
                "failure_reason": None,
                "webhook_url": "https://tpp.example.com/callbacks/payment",
                "created_at": "2025-11-01T10:00:00Z",
                "updated_at": "2025-11-01T10:00:00Z",
            }
        }
    }
