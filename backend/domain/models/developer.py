"""
Domain Model: Developer & TPP Portal
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, EmailStr, Field


class DeveloperAccountStatus(str, Enum):
    """Lifecycle state of a developer portal user."""

    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    SANDBOX_ACTIVE = "SANDBOX_ACTIVE"
    PENDING_KYB = "PENDING_KYB"
    LIVE_ACTIVE = "LIVE_ACTIVE"
    SUSPENDED = "SUSPENDED"


class DeveloperProfile(BaseModel):
    """
    Developer user profile representing an authenticated TPP account.
    """

    developer_id: str = Field(..., description="Unique merchant/developer ID.")
    email: EmailStr = Field(..., description="Developer official contact email.")
    full_name: str = Field(..., description="Contact person full name.")
    phone_number: str = Field(..., description="E.164 phone number.")
    company_name: str = Field(..., description="Registered business / commercial entity name.")
    tax_id: str | None = Field(default=None, description="Tax Identification Number (TIN).")
    status: DeveloperAccountStatus = Field(default=DeveloperAccountStatus.SANDBOX_ACTIVE)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class SandboxAppCredentials(BaseModel):
    """
    Credentials returned once upon Sandbox provisioning or secret rotation.
    """

    app_id: str
    app_name: str
    client_id: str
    client_secret: str
    environment: str = "SANDBOX"
    allowed_scopes: list[str]
