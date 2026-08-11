"""
Domain Model: Transaction
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.

Represents a single financial transaction normalised to an ISO 20022-inspired
schema. Bank adapters translate their proprietary transaction formats to this
standard before returning data to the application layer.

Reference: ISO 20022 camt.053 (BankToCustomerStatement) simplified for MVP.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    """ISO 20022-aligned debit/credit classification."""

    CREDIT = "CRDT"  # Money coming IN to the account
    DEBIT = "DBIT"   # Money going OUT of the account


class TransactionStatus(str, Enum):
    """Lifecycle status of a transaction record."""

    BOOKED = "BOOKED"       # Settled and final
    PENDING = "PENDING"     # Authorised but not yet cleared
    REJECTED = "REJECTED"   # Declined by the bank or gateway


class TransactionChannel(str, Enum):
    """The channel through which the transaction was initiated."""

    ATM = "ATM"
    MOBILE = "MOBILE"
    INTERNET = "INTERNET"
    BRANCH = "BRANCH"
    POS = "POS"
    GATEWAY = "GATEWAY"   # Initiated via Kifiya Open Gateway


class RemittanceInfo(BaseModel):
    """
    Structured remittance / reference information attached to a transaction.
    Aligned with ISO 20022 RemittanceInformation.
    """

    end_to_end_id: str = Field(
        ...,
        description="End-to-end unique ID assigned by the originating party.",
        examples=["PAY-20251101-00123"],
    )
    unstructured: Optional[str] = Field(
        default=None,
        description="Free-text payment reference or narration.",
        examples=["School fees payment Term 2"],
    )


class Transaction(BaseModel):
    """
    Unified Transaction Domain Model — ISO 20022-inspired.

    Covers up to 1 year of transaction history as required by the AIS spec.
    Bank adapters MUST map their proprietary statement entries to this schema.
    """

    transaction_id: str = Field(
        ...,
        description="Gateway-assigned unique transaction identifier.",
        examples=["TXN-01HZK3M2V9Q4WBXY"],
    )
    account_id: str = Field(
        ...,
        description="The account_id this transaction belongs to.",
        examples=["01HZK3M2V9Q4WBXYPND7FJ3R5T"],
    )
    bank_id: str = Field(
        ...,
        description="The bank rail that originated this transaction.",
        examples=["COOP"],
    )
    transaction_type: TransactionType = Field(
        ...,
        description="Debit (DBIT) or Credit (CRDT) classification.",
    )
    status: TransactionStatus = Field(
        default=TransactionStatus.BOOKED,
        description="Current settlement status of the transaction.",
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        description="Transaction amount (always positive; direction conveyed by transaction_type).",
        examples=["500.00"],
    )
    currency: str = Field(
        default="ETB",
        description="ISO 4217 currency code.",
        examples=["ETB"],
    )
    value_date: datetime = Field(
        ...,
        description="Date the transaction was posted to the account (UTC).",
    )
    booking_date: datetime = Field(
        ...,
        description="Date the funds were actually moved / settled (UTC).",
    )
    channel: Optional[TransactionChannel] = Field(
        default=None,
        description="Channel via which the transaction was initiated.",
    )
    counterparty_name: Optional[str] = Field(
        default=None,
        description="Name of the sending or receiving party.",
        examples=["Tigist Haile"],
    )
    counterparty_account: Optional[str] = Field(
        default=None,
        description="Masked account number of the counterparty.",
        examples=["****5678"],
    )
    remittance_info: Optional[RemittanceInfo] = Field(
        default=None,
        description="Structured remittance / reference information.",
    )
    bank_transaction_code: Optional[str] = Field(
        default=None,
        description="Bank's own proprietary transaction code for audit trail.",
        examples=["CBE-TRF-01"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "transaction_id": "TXN-01HZK3M2V9Q4WBXY",
                "account_id": "01HZK3M2V9Q4WBXYPND7FJ3R5T",
                "bank_id": "COOP",
                "transaction_type": "CRDT",
                "status": "BOOKED",
                "amount": "500.00",
                "currency": "ETB",
                "value_date": "2025-11-01T08:00:00Z",
                "booking_date": "2025-11-01T08:05:00Z",
                "channel": "MOBILE",
                "counterparty_name": "Tigist Haile",
                "counterparty_account": "****5678",
                "remittance_info": {
                    "end_to_end_id": "PAY-20251101-00123",
                    "unstructured": "School fees payment Term 2",
                },
                "bank_transaction_code": "COOP-MOB-TRF",
            }
        }
    }
