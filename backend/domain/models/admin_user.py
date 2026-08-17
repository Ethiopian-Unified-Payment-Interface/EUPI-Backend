"""
Domain Model: Admin User
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.

Operator identities for the Admin Portal. Distinct from `SuperAppUser`:
admins are Kifiya staff authenticating with email + password, not citizens
authenticating with Fayda eKYC + PIN. The two never share a credential store,
a token type, or an authorisation path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class AdminRole(str, Enum):
    """
    Operator role driving Admin API authorisation.

    Deliberately coarse. A richer permission matrix is warranted once the
    developer platform lands and more operator personas exist (KYB reviewer,
    finance, support) — but a two-role model that is actually enforced beats a
    fine-grained one that is not.
    """

    ADMIN = "ADMIN"
    """Full access: configuration writes, KYB decisions, PII reveal."""

    READ_ONLY = "READ_ONLY"
    """View-only. Cannot mutate configuration or reveal unmasked PII."""

    @property
    def can_write(self) -> bool:
        """Whether this role may mutate platform configuration."""
        return self is AdminRole.ADMIN

    @property
    def can_reveal_pii(self) -> bool:
        """Whether this role may view unmasked national ID numbers."""
        return self is AdminRole.ADMIN


class AdminUser(BaseModel):
    """
    A Kifiya operator with access to the Admin Portal.

    `password_hash` is excluded from serialisation so an AdminUser can never
    leak a credential by being returned from a route handler.
    """

    email: str = Field(
        ...,
        description="Login email. Unique, and the actor recorded in audit logs.",
        examples=["admin@kifiya.com"],
    )
    full_name: str = Field(
        ...,
        description="Operator's display name.",
        examples=["Meseret Alemu"],
    )
    role: AdminRole = Field(
        default=AdminRole.READ_ONLY,
        description="Authorisation role. Defaults to the least privilege.",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the operator may authenticate. Disable rather than delete.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp of account creation.",
    )
    last_login_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the most recent successful login.",
    )
    password_hash: str | None = Field(
        default=None,
        description="Salted argon2id hash of the operator's password.",
        exclude=True,  # Never serialized in API responses
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "admin@kifiya.com",
                "full_name": "Meseret Alemu",
                "role": "ADMIN",
                "is_active": True,
                "created_at": "2026-08-11T10:30:00Z",
                "last_login_at": "2026-08-15T08:12:00Z",
            }
        }
    }
