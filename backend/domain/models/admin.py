"""
Domain Model: Admin & Web Portal Entities
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend.domain.models.account import BankID


class BankRailStatus(str, Enum):
    """Operational status of a commercial bank rail adapter."""
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    INACTIVE = "INACTIVE"


class KYBStatus(str, Enum):
    """KYB (Know Your Business) verification status for merchants."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MerchantStatus(str, Enum):
    """Account status for TPP merchants."""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class BankConfig(BaseModel):
    """Dynamically configurable commercial bank rail parameters."""
    bank_id: BankID = Field(..., description="Unique bank rail code enum.")
    name: str = Field(..., description="Full commercial bank name.")
    description: str = Field(..., description="Adapter purpose and detail.")
    status: BankRailStatus = Field(default=BankRailStatus.ACTIVE, description="Rail operational status.")
    base_url: str = Field(..., description="Target CBS API base URL.")
    api_key_header_name: str = Field(..., description="HTTP header name used for authentication.")
    api_key: str | None = Field(default=None, description="API Key or Secret Token (masked in responses).", exclude=True)
    timeout_ms: int = Field(default=3000, description="HTTP timeout threshold in milliseconds.")
    cost_weight: float = Field(default=0.20, description="Fee/cost score weighting (0.0 to 1.0).")
    circuit_breaker_threshold: float = Field(default=0.50, description="Min uptime percentage before excluding rail.")
    rolling_uptime_percent: float = Field(default=99.8, description="Calculated rolling uptime score.")
    avg_latency_ms: int = Field(default=145, description="Average response latency in milliseconds.")


class Merchant(BaseModel):
    """Third-Party Provider (TPP) merchant profile."""
    merchant_id: str = Field(..., description="Unique merchant ID (UUID format).")
    company_name: str = Field(..., description="Registered legal business name.")
    email: str = Field(..., description="Contact email address.")
    environment: str = Field(default="LIVE", description="Active environment (SANDBOX or LIVE).")
    kyb_status: KYBStatus = Field(default=KYBStatus.APPROVED, description="Know Your Business verification state.")
    status: MerchantStatus = Field(default=MerchantStatus.ACTIVE, description="Merchant account status.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Registration timestamp.")


class DeveloperApp(BaseModel):
    """Merchant developer application credentials & scopes."""
    app_id: str = Field(..., description="Unique application ID.")
    merchant_id: str = Field(..., description="Owner merchant ID.")
    app_name: str = Field(..., description="Display application name.")
    merchant_name: str = Field(..., description="Owner company name.")
    client_id: str = Field(..., description="OAuth client ID.")
    environment: str = Field(default="LIVE", description="Target environment.")
    allowed_scopes: list[str] = Field(default_factory=lambda: ["ais:read", "pis:write"], description="Assigned API scopes.")
    status: str = Field(default="ACTIVE", description="App status.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp.")


class KYBRequest(BaseModel):
    """Merchant KYB onboarding request."""
    kyb_id: str = Field(..., description="Unique KYB request ID.")
    developer_name: str = Field(..., description="Submitting developer name.")
    company_name: str = Field(..., description="Company name.")
    tax_id: str = Field(..., description="Tax Identification Number (TIN).")
    requested_scopes: list[str] = Field(default_factory=list, description="Requested API scopes.")
    status: KYBStatus = Field(default=KYBStatus.PENDING, description="Review status.")
    submitted_at: datetime = Field(default_factory=datetime.utcnow, description="Submission timestamp.")
    review_note: str | None = Field(default=None, description="Admin review notes.")


class WebhookLog(BaseModel):
    """Log record of webhook delivery attempt."""
    webhook_id: str = Field(..., description="Unique log ID.")
    merchant_name: str = Field(..., description="Recipient merchant name.")
    event_type: str = Field(..., description="Event type string.")
    http_status: int = Field(..., description="HTTP status response code.")
    latency_ms: int = Field(..., description="Delivery latency in milliseconds.")
    attempts: int = Field(default=1, description="Delivery retry attempt count.")
    outcome: str = Field(..., description="Delivery outcome (DELIVERED or FAILED).")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp.")


class AuditLog(BaseModel):
    """Administrative action audit trail entry."""
    log_id: str = Field(..., description="Unique audit log ID.")
    action: str = Field(..., description="Action code (e.g. BANK_RAIL_UPDATED, KYB_APPROVED).")
    actor_email: str = Field(..., description="Email of the admin who performed the action.")
    ip_address: str = Field(default="127.0.0.1", description="Client IP address.")
    details: str = Field(..., description="Detailed description of the change.")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="UTC timestamp of the action.")


# ── Analytics & Stats DTOs ───────────────────────────────────────────────────

class DashboardStats(BaseModel):
    """High-level KPI metrics for the Admin Dashboard."""
    total_users: int
    total_developers: int
    active_bank_rails: int
    total_transactions: int
    api_success_rate: float
    compared_to_previous_period: dict[str, float]


class ActivityItem(BaseModel):
    """System activity feed event item."""
    id: str
    level: str  # "info", "success", "warning", "error"
    message: str
    detail: str
    timestamp: datetime


class CustomerStats(BaseModel):
    """KPI metrics for Super App customer onboarding."""
    total_registered: int
    new_users_today: int
    active_users: int
    kyc_verification_rate_percent: float
    onboarding_dropoff_percent: float


class TransactionStats(BaseModel):
    """System-wide transaction KPIs."""
    total_volume_etb: float
    success_rate_percent: float
    p2p_transfer_percent: float
    merchant_payment_percent: float
    avg_transaction_value_etb: float


class MerchantStats(BaseModel):
    """KPI metrics for TPP merchants."""
    total_merchants: int
    active_merchants: int
    api_traffic_per_day: int
    avg_setup_time_days: float


class MerchantTxnStats(BaseModel):
    """KPI metrics for merchant payments."""
    merchant_volume_etb: float
    successful_payments: int
    dispute_rate_percent: float
    avg_settlement_time_hours: float
