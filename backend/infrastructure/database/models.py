"""
SQLAlchemy ORM Table Definitions
==================================
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: This module defines ONLY table structure. No business logic here.

Tables:
  payments         — Full lifecycle record for every PIS payment.
  consent_tokens   — Issued JWTs tracked for revocation support.
  webhook_events   — Async webhook delivery log per payment.
  users            — Super app platform user accounts.
  linked_accounts  — Bank accounts explicitly linked by super app users.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all gateway ORM models."""


class PaymentRecord(Base):
    """
    Persisted representation of a Payment domain object.
    Denormalised for simplicity: initiate_request fields stored as flat columns.
    """

    __tablename__ = "payments"

    # Identity
    payment_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Routing
    selected_rail: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_order_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Auth
    consent_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Outcome
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Callbacks
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── Initiate Request Fields (denormalised) ────────────────────────────────
    debtor_account_number: Mapped[str] = mapped_column(String(30), nullable=False)
    debtor_bank_id: Mapped[str] = mapped_column(String(20), nullable=False)
    creditor_account_number: Mapped[str] = mapped_column(String(30), nullable=False)
    creditor_bank_id: Mapped[str] = mapped_column(String(20), nullable=False)
    creditor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ETB")
    end_to_end_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    remittance_info: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ConsentTokenRecord(Base):
    """
    Tracks every gateway JWT ever issued.
    Used to support token revocation: even a cryptographically valid JWT is
    rejected if its JTI is present in this table with is_revoked=True.
    """

    __tablename__ = "consent_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)  # JWT "jti" claim
    fin: Mapped[str] = mapped_column(String(14), nullable=False, index=True)
    kyc_level: Mapped[str] = mapped_column(String(20), nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)          # JSON-encoded list
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class WebhookEventRecord(Base):
    """
    Audit log of every webhook delivery attempt to a TPP's callback URL.
    Future: a background worker retries failed events with exponential back-off.
    """

    __tablename__ = "webhook_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    webhook_url: Mapped[str] = mapped_column(String(512), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)     # JSON-encoded payload
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserRecord(Base):
    """Persisted super app user."""
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    fin: Mapped[str] = mapped_column(String(14), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pin_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class LinkedAccountRecord(Base):
    """Persisted linked bank account for a super app user."""
    __tablename__ = "linked_accounts"

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bank_id: Mapped[str] = mapped_column(String(20), nullable=False)
    account_number: Mapped[str] = mapped_column(String(30), nullable=False)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default_sending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_default_receiving: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BankConfigRecord(Base):
    """Persisted dynamic commercial bank rail configuration."""
    __tablename__ = "bank_configurations"

    bank_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_header_name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key: Mapped[str] = mapped_column(String(255), nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=3000, nullable=False)
    cost_weight: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)
    circuit_breaker_threshold: Mapped[float] = mapped_column(Float, default=0.50, nullable=False)
    rolling_uptime_percent: Mapped[float] = mapped_column(Float, default=99.80, nullable=False)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=145, nullable=False)


class MerchantRecord(Base):
    """Persisted TPP merchant profile."""
    __tablename__ = "merchants"

    merchant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), default="LIVE", nullable=False)
    kyb_status: Mapped[str] = mapped_column(String(20), default="APPROVED", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class DeveloperAppRecord(Base):
    """Persisted developer application for a merchant."""
    __tablename__ = "developer_apps"

    app_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_name: Mapped[str] = mapped_column(String(100), nullable=False)
    merchant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    redirect_uris: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    app_logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    environment: Mapped[str] = mapped_column(String(20), default="LIVE", nullable=False)
    allowed_scopes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserConsentRecord(Base):
    """
    Persisted consent grant from a Super App user to a Third-Party Application.
    Tracks granular scope approvals and explicit user revocation.
    """
    __tablename__ = "user_consents"

    consent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="GRANTED", nullable=False)  # GRANTED, REVOKED, EXPIRED
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthorizationCodeRecord(Base):
    """
    Single-use, short-lived OAuth 2.0 authorization codes for PKCE consent flow.
    """
    __tablename__ = "authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(10), default="S256", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KYBRequestRecord(Base):
    """Persisted merchant KYB verification request."""
    __tablename__ = "kyb_requests"

    kyb_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    developer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    company_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tax_id: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_scopes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLogRecord(Base):
    """Persisted administrative action audit log."""
    __tablename__ = "audit_logs"

    log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_email: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), default="127.0.0.1", nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
