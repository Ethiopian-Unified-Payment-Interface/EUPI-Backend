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
  admin_users      — Admin Portal operator accounts.
  ledger_entries   — Append-only double-entry postings.
  fee_rules        — Versioned pricing rules; never edited in place.

Money columns are Numeric, never Float. Binary floating point cannot represent
0.10 exactly, and a payments ledger that drifts by a cent cannot be audited.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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

    # The national ID is never stored in plaintext. `fin` used to be a
    # plaintext, indexed, unique column — meaning anyone who obtained this
    # table obtained every citizen's Fayda number directly.
    #
    # Three columns replace it, each with one job:
    #   fin_encrypted   — Fernet ciphertext; the only place the value survives.
    #   fin_blind_index — keyed HMAC, so "one account per national ID" can be
    #                     enforced by an indexed equality lookup without
    #                     decrypting anything.
    #   fin_last4       — the masked suffix operators actually read. Stored
    #                     plainly so the admin analytics repository can render
    #                     a mask with no ability to decrypt at all.
    fin_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    fin_blind_index: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    fin_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="")

    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 255 chars: argon2id encoded hashes run ~95 chars; the old SHA-256 scheme
    # was exactly 64, which is why this column used to be String(64).
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failed_pin_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pin_locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserAppIdentityRecord(Base):
    """
    Per-application pseudonym. The only user identifier a developer ever sees.

    The unique constraint is on (username, app_id) so one pairing yields one
    stable pseudonym, while psu_id is separately unique so it can be resolved
    on its own. There is deliberately no index supporting "all pseudonyms for
    a username across apps" — that query is the correlation this table exists
    to prevent.
    """
    __tablename__ = "user_app_identities"

    psu_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("username", "app_id", name="uq_user_app_identity"),
    )


class ConsentRecord(Base):
    """
    A user's grant of one scope to one application.

    One row per scope rather than a bundled grant, so a user can withdraw a
    single permission without severing the whole integration.
    """
    __tablename__ = "consents"

    consent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FinVaultRecord(Base):
    """
    Encrypted national ID, separated from the user row.

    `fin_blind_index` is a keyed HMAC, not a plain hash: a 14-digit FIN has only
    a 10^14 keyspace and a bare digest of it would be brute-forceable offline
    by anyone holding this table.
    """
    __tablename__ = "fin_vault"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    fin_blind_index: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    fin_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LedgerEntryRecord(Base):
    """
    Persisted double-entry ledger posting. Append-only: never updated, never
    deleted. Corrections are new opposing entries.
    """
    __tablename__ = "ledger_entries"

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    transaction_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    account_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    # Numeric, never Float — binary floating point cannot represent 0.10
    # exactly and a ledger that drifts by a cent cannot be audited.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ETB")
    # Separates value that moved at a bank (mirror) from EUPI's own positions.
    # The two books balance independently and must never be netted together.
    is_mirror: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    bank_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    app_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class FeeRuleRecord(Base):
    """
    Persisted versioned fee rule. Append-only by (rule_id, version): a price
    change creates a new version and retires the old one, so every historical
    payment stays explainable.
    """
    __tablename__ = "fee_rules"

    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    bank_id: Mapped[str] = mapped_column(String(20), nullable=False, default="*")
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ETB")
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    fee_type: Mapped[str] = mapped_column(String(20), nullable=False)
    flat_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    percentage_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    revenue_share_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=4000)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AdminUserRecord(Base):
    """Persisted Admin Portal operator."""
    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


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

    __table_args__ = (
        # One link per account per profile. The service checks this too, but the
        # constraint is the backstop: without it a race between two concurrent
        # link requests writes both rows, and a duplicate silently inflates the
        # user's aggregated balance.
        UniqueConstraint(
            "username", "bank_id", "account_number", name="uq_linked_account"
        ),
    )


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
    environment: Mapped[str] = mapped_column(String(20), default="LIVE", nullable=False)
    allowed_scopes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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
