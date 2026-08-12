"""
Domain Model: User
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SuperAppUser(BaseModel):
    """
    Super App Platform User.
    
    Represents a registered user of the Kifiya super app. Created when a
    customer completes Fayda eKYC verification and chooses a unique username.
    """

    user_id: str = Field(
        ...,
        description="Gateway-assigned unique ID (UUID format).",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    username: str = Field(
        ...,
        description="Unique handle chosen by the user (3-30 chars, alphanumeric + underscores).",
        examples=["abebe_girma"],
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
        default_factory=datetime.utcnow,
        description="UTC timestamp of account creation.",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the account is active.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "username": "abebe_girma",
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
