"""
Domain Model: User
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class SuperAppUser(BaseModel):
    """
    Super App Platform User.
    
    Represents a registered user of the Kifiya super app. Created when a
    customer completes Fayda eKYC verification and chooses a unique username.
    """

    username: str = Field(
        ...,
        description="Unique platform handle with @eupi suffix. Acts as the primary key.",
        examples=["abebe_girma@eupi"],
    )
    fin: str = Field(
        ...,
        description="Fayda Identification Number (14-digit, links to national identity).",
        examples=["12345678901234"],
    )
    full_name: str = Field(
        ...,
        description="Full legal name from Fayda registry.",
        examples=["Abebe Girma"],
    )
    phone_number: str = Field(
        ...,
        description="E.164 phone number from registration.",
        examples=["+251911234567"],
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp of account creation.",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the account is active.",
    )
    pin_hash: str | None = Field(
        default=None,
        description=(
            "Salted argon2id hash of the user's 6-digit PIN. Never stored in "
            "plaintext, never serialized in API responses."
        ),
        exclude=True,  # Never serialized in API responses
    )
    failed_pin_attempts: int = Field(
        default=0,
        description="Consecutive failed PIN attempts. Reset to 0 on success.",
        exclude=True,
    )
    pin_locked_until: datetime | None = Field(
        default=None,
        description=(
            "UTC timestamp until which PIN authentication is refused. Set once "
            "failed attempts reach the configured threshold."
        ),
        exclude=True,
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "abebe_girma@eupi",
                "fin": "12345678901234",
                "full_name": "Abebe Girma",
                "phone_number": "+251911234567",
                "created_at": "2026-08-11T10:30:00Z",
                "is_active": True,
            }
        }
    }


class PublicUserProfile(BaseModel):
    """
    Public-facing user profile for peer-to-peer lookups.
    
    Contains only non-sensitive information safe to expose when resolving
    a transfer recipient by username. No financial data, no FIN.
    """

    username: str = Field(
        ...,
        description="Unique handle chosen by the user.",
        examples=["abebe_girma"],
    )
    full_name: str = Field(
        ...,
        description="Full legal name from Fayda registry.",
        examples=["Abebe Girma"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "abebe_girma",
                "full_name": "Abebe Girma",
            }
        }
    }


def normalize_username(username: str) -> str:
    """
    Ensure the username has the '@eupi' suffix internally.
    Accepts both 'abebe_girma' and 'abebe_girma@eupi'.
    """
    clean = username.strip().lower()
    if clean.endswith("@eupi"):
        return clean
    return f"{clean}@eupi"


def get_base_username(username: str) -> str:
    """Extract base handle without '@eupi' suffix."""
    clean = username.strip().lower()
    if clean.endswith("@eupi"):
        return clean[:-5]
    return clean
