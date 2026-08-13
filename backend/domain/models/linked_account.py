"""
Domain Model: Linked Account
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from backend.domain.models.account import BankID


class AccountDirection(str, Enum):
    """Direction role for a default linked account."""

    SENDING = "SENDING"      # Default account for outgoing transfers
    RECEIVING = "RECEIVING"  # Default account for incoming transfers


class LinkedAccount(BaseModel):
    """
    A bank account explicitly linked by a super app user.
    
    Unlike AIS (which fans out to all banks automatically), super app users
    manually discover and link specific bank accounts. Linked accounts are
    persisted in the gateway's database and used for peer-to-peer transfers.
    """

    link_id: str = Field(
        ...,
        description="Gateway-assigned unique link identifier (UUID format).",
        examples=["6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
    )
    username: str = Field(
        ...,
        description="References SuperAppUser.username (the owner of this linked account).",
        examples=["abebe_girma@eupi"],
    )
    bank_id: BankID = Field(
        ...,
        description="Which bank this account belongs to.",
    )
    account_number: str = Field(
        ...,
        description="Full account number at the bank.",
        examples=["1000123456789"],
    )
    account_name: str = Field(
        ...,
        description="Name on the account (from bank verification).",
        examples=["Abebe Girma"],
    )
    is_default_sending: bool = Field(
        default=False,
        description="Whether this is the default for outgoing transfers.",
    )
    is_default_receiving: bool = Field(
        default=False,
        description="Whether this is the default for incoming transfers.",
    )
    linked_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the account was linked.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "link_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "username": "abebe_girma@eupi",
                "bank_id": "COOP",
                "account_number": "1000123456789",
                "account_name": "Abebe Girma",
                "is_default_sending": True,
                "is_default_receiving": False,
                "linked_at": "2026-08-11T12:00:00Z",
            }
        }
    }
