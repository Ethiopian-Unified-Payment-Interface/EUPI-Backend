"""
Domain Model: Account
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.

Represents a unified, bank-agnostic account object as returned by any bank adapter
after normalisation. All bank-specific field names are mapped to this standard schema.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Currency(str, Enum):
    """ISO 4217 currency codes supported by the gateway."""

    ETB = "ETB"  # Ethiopian Birr — primary currency
    USD = "USD"
    EUR = "EUR"


class BankID(str, Enum):
    """Canonical identifiers for each supported banking rail."""

    COOP = "COOP"         # Cooperative Bank of Oromia
    CBE = "CBE"           # Commercial Bank of Ethiopia
    WEGAGEN = "WEGAGEN"   # Wegagen Bank
    AWASH = "AWASH"       # Awash Bank
    ABYSSINIA = "ABYSSINIA"  # Bank of Abyssinia (Abisiniya)
    BERHAN = "BERHAN"     # Berhan Bank


class AccountType(str, Enum):
    """Standardised account classifications."""

    SAVINGS = "SAVINGS"
    CURRENT = "CURRENT"
    LOAN = "LOAN"
    FIXED_DEPOSIT = "FIXED_DEPOSIT"


class Account(BaseModel):
    """
    Unified Account Domain Model.

    This is the canonical representation of a bank account across all
    integrated banking rails. Bank adapters MUST map their proprietary
    response payloads to this schema before returning to the application layer.
    """

    account_id: str = Field(
        ...,
        description="Gateway-assigned unique account identifier (ULID format recommended).",
        examples=["01HZK3M2V9Q4WBXYPND7FJ3R5T"],
    )
    bank_id: BankID = Field(
        ...,
        description="The originating bank rail.",
    )
    account_number: str = Field(
        ...,
        description="The masked account number as returned by the bank (last 4 digits visible).",
        examples=["****1234"],
    )
    account_type: AccountType = Field(
        ...,
        description="Type classification of the account.",
    )
    currency: Currency = Field(
        default=Currency.ETB,
        description="ISO 4217 currency code of the account.",
    )
    available_balance: Decimal = Field(
        ...,
        ge=0,
        description="Current spendable balance (net of holds and pending debits).",
        examples=["12500.75"],
    )
    ledger_balance: Decimal = Field(
        ...,
        ge=0,
        description="Total book balance including pending items.",
        examples=["12750.00"],
    )
    account_name: str = Field(
        ...,
        description="Full legal name on the account, sourced from the bank's KYC records.",
        examples=["Abebe Girma"],
    )
    iban: Optional[str] = Field(
        default=None,
        description="International Bank Account Number, if issued by the bank.",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the account is open and operationally active.",
    )
    last_updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the last balance refresh from the bank rail.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "account_id": "01HZK3M2V9Q4WBXYPND7FJ3R5T",
                "bank_id": "COOP",
                "account_number": "****1234",
                "account_type": "SAVINGS",
                "currency": "ETB",
                "available_balance": "12500.75",
                "ledger_balance": "12750.00",
                "account_name": "Abebe Girma",
                "iban": None,
                "is_active": True,
                "last_updated_at": "2025-11-01T10:30:00Z",
            }
        }
    }
