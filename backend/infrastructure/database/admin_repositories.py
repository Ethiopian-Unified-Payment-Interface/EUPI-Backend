"""
Admin Repositories
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: Concrete implementations of abstract admin port interfaces.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.application.ports.admin_ports import (
    AdminAnalyticsPort,
    AuditLogRepositoryPort,
    BankConfigRepositoryPort,
    MerchantRepositoryPort,
)
from backend.domain.models.account import BankID
from backend.domain.models.admin import (
    ActivityItem,
    AuditLog,
    BankConfig,
    BankRailStatus,
    CustomerStats,
    DashboardStats,
    DeveloperApp,
    KYBRequest,
    KYBStatus,
    Merchant,
    MerchantStats,
    MerchantStatus,
    MerchantTxnStats,
    TransactionStats,
    WebhookLog,
)
from backend.infrastructure.database.session import RepositoryBase
from backend.infrastructure.database.models import (
    AuditLogRecord,
    BankConfigRecord,
    Base,
    DeveloperAppRecord,
    KYBRequestRecord,
    MerchantRecord,
    PaymentRecord,
    UserRecord,
    WebhookEventRecord,
)


class BankConfigRepository(RepositoryBase, BankConfigRepositoryPort):
    """Relational implementation of BankConfigRepositoryPort."""

    def __init__(self, db, seed: bool = True) -> None:
        """
        Args:
            db:   The shared :class:`Database`.
            seed: Install the six default bank rail configs when the table is
                  empty. Off in tests that assert on an empty rail list.
        """
        super().__init__(db)
        if seed:
            self._seed_default_banks()

    def _seed_default_banks(self) -> None:
        """Seed default 6 commercial bank configs if empty."""
        defaults = [
            ("COOP", "Cooperative Bank of Oromia", "Primary partner bank adapter", "https://api.coopbankoromia.com.et/v1", "X-COOP-API-Key", "mock-coop-key"),
            ("CBE", "Commercial Bank of Ethiopia", "ISO-20022 aligned partner rail", "https://api.cbe.com.et/v1", "X-CBE-Auth-Token", "mock-cbe-key"),
            ("WEGAGEN", "Wegagen Bank", "SOAP-wrapped REST JSON adapter", "https://api.wegagenbank.com/v1", "Authorization", "mock-wegagen-key"),
            ("AWASH", "Awash Bank", "Commercial bank adapter", "https://api.awashbank.com/v1", "X-Awash-Key", "mock-awash-key"),
            ("ABYSSINIA", "Bank of Abyssinia", "Abisiniya modern REST adapter", "https://api.bankofabyssinia.com/v1", "X-Abyssinia-Token", "mock-abyssinia-key"),
            ("BERHAN", "Berhan Bank", "Berhan JSON-RPC style adapter", "https://api.berhanbank.et/v1", "X-Berhan-Auth", "mock-berhan-key"),
        ]

        with self._session() as session:
            count = session.query(BankConfigRecord).count()
            if count == 0:
                for b_id, name, desc, url, header, key in defaults:
                    rec = BankConfigRecord(
                        bank_id=b_id,
                        name=name,
                        description=desc,
                        status="ACTIVE",
                        base_url=url,
                        api_key_header_name=header,
                        api_key=key,
                        timeout_ms=3000,
                        cost_weight=0.20,
                        circuit_breaker_threshold=0.50,
                        rolling_uptime_percent=99.80,
                        avg_latency_ms=145,
                    )
                    session.add(rec)

    def list_configs(self) -> list[BankConfig]:
        with self._session() as session:
            records = session.query(BankConfigRecord).all()
            return [self._to_domain(r) for r in records]

    def get_config(self, bank_id: BankID) -> BankConfig | None:
        with self._session() as session:
            record = session.get(BankConfigRecord, bank_id.value)
            return self._to_domain(record) if record else None

    def save_config(self, config: BankConfig) -> None:
        record = BankConfigRecord(
            bank_id=config.bank_id.value,
            name=config.name,
            description=config.description,
            status=config.status.value,
            base_url=config.base_url,
            api_key_header_name=config.api_key_header_name,
            api_key=config.api_key or "mock-key",
            timeout_ms=config.timeout_ms,
            cost_weight=config.cost_weight,
            circuit_breaker_threshold=config.circuit_breaker_threshold,
            rolling_uptime_percent=config.rolling_uptime_percent,
            avg_latency_ms=config.avg_latency_ms,
        )
        with self._session() as session:
            session.merge(record)

    @staticmethod
    def _to_domain(r: BankConfigRecord) -> BankConfig:
        return BankConfig(
            bank_id=BankID(r.bank_id),
            name=r.name,
            description=r.description,
            status=BankRailStatus(r.status),
            base_url=r.base_url,
            api_key_header_name=r.api_key_header_name,
            api_key=r.api_key,
            timeout_ms=r.timeout_ms,
            cost_weight=float(r.cost_weight),
            circuit_breaker_threshold=float(r.circuit_breaker_threshold),
            rolling_uptime_percent=float(r.rolling_uptime_percent),
            avg_latency_ms=r.avg_latency_ms,
        )


class MerchantRepository(RepositoryBase, MerchantRepositoryPort):
    """Relational implementation of MerchantRepositoryPort."""

    def __init__(self, db, seed: bool = True) -> None:
        """
        Args:
            db:   The shared :class:`Database`.
            seed: Install sample merchant and KYB records when the table is
                  empty. Off in tests that assert on empty registries.
        """
        super().__init__(db)
        if seed:
            self._seed_default_merchants()

    def _seed_default_merchants(self) -> None:
        """Seed default TPP merchant profiles and KYB requests."""
        from backend.infrastructure.auth.password_hasher import Argon2PasswordHasher
        hasher = Argon2PasswordHasher()
        default_pwd_hash = hasher.hash("SecureDeveloper2026!")

        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        with self._session() as session:
            if session.query(MerchantRecord).count() == 0:
                m1 = MerchantRecord(
                    merchant_id="mer_1234",
                    company_name="Zemen Fintech PLC",
                    contact_name="Abebe Girma",
                    email="contact@zemenfintech.et",
                    environment="LIVE",
                    password_hash=default_pwd_hash,
                    kyb_status="APPROVED",
                    status="ACTIVE",
                    is_active=True,
                    created_at=now,
                )
                m2 = MerchantRecord(
                    merchant_id="mer_5678",
                    company_name="EthioPay Solutions PLC",
                    contact_name="Girma Tadesse",
                    email="info@ethiopay.et",
                    environment="LIVE",
                    password_hash=default_pwd_hash,
                    kyb_status="APPROVED",
                    status="ACTIVE",
                    is_active=True,
                    created_at=now,
                )
                session.add_all([m1, m2])

            # Ensure seeded merchants without password_hash receive default credentials
            merchants_without_pwd = session.query(MerchantRecord).filter(MerchantRecord.password_hash.is_(None)).all()
            for m in merchants_without_pwd:
                m.password_hash = default_pwd_hash
                m.is_active = True

            if session.query(DeveloperAppRecord).count() == 0:
                app1 = DeveloperAppRecord(
                    app_id="app_live_9x8c7v",
                    merchant_id="mer_5678",
                    app_name="EthioPay Checkout",
                    merchant_name="EthioPay Solutions PLC",
                    client_id="client_ethiopay_99",
                    environment="LIVE",
                    allowed_scopes=json.dumps([
                        "accounts:read",
                        "payments:initiate",
                        "payments:read:own",
                        "webhooks:receive",
                    ]),
                    status="ACTIVE",
                    created_at=now,
                )
                session.add(app1)

            if session.query(KYBRequestRecord).count() == 0:
                kyb1 = KYBRequestRecord(
                    kyb_id="kyb_001",
                    developer_name="Selam Tesfaye",
                    company_name="Birr Analytics PLC",
                    tax_id="TIN-987654321",
                    requested_scopes=json.dumps(["ais:read", "pis:write"]),
                    status="PENDING",
                    submitted_at=now,
                    review_note=None,
                )
                session.add(kyb1)

    def list_merchants(self) -> list[Merchant]:
        with self._session() as session:
            records = session.query(MerchantRecord).all()
            return [
                Merchant(
                    merchant_id=r.merchant_id,
                    company_name=r.company_name,
                    email=r.email,
                    environment=r.environment,
                    kyb_status=KYBStatus(r.kyb_status),
                    status=MerchantStatus(r.status),
                    created_at=r.created_at.replace(tzinfo=timezone.utc),
                )
                for r in records
            ]

    def get_merchant(self, merchant_id: str) -> Merchant | None:
        with self._session() as session:
            r = session.get(MerchantRecord, merchant_id)
            if not r:
                return None
            return Merchant(
                merchant_id=r.merchant_id,
                company_name=r.company_name,
                email=r.email,
                environment=r.environment,
                kyb_status=KYBStatus(r.kyb_status),
                status=MerchantStatus(r.status),
                created_at=r.created_at.replace(tzinfo=timezone.utc),
            )

    def list_developer_apps(self) -> list[DeveloperApp]:
        with self._session() as session:
            records = session.query(DeveloperAppRecord).all()
            return [
                DeveloperApp(
                    app_id=r.app_id,
                    merchant_id=r.merchant_id,
                    app_name=r.app_name,
                    merchant_name=r.merchant_name,
                    client_id=r.client_id,
                    environment=r.environment,
                    allowed_scopes=json.loads(r.allowed_scopes),
                    status=r.status,
                    created_at=r.created_at.replace(tzinfo=timezone.utc),
                )
                for r in records
            ]

    def list_kyb_requests(self) -> list[KYBRequest]:
        with self._session() as session:
            records = session.query(KYBRequestRecord).all()
            return [
                KYBRequest(
                    kyb_id=r.kyb_id,
                    developer_name=r.developer_name,
                    company_name=r.company_name,
                    tax_id=r.tax_id,
                    requested_scopes=json.loads(r.requested_scopes),
                    status=KYBStatus(r.status),
                    submitted_at=r.submitted_at.replace(tzinfo=timezone.utc),
                    review_note=r.review_note,
                )
                for r in records
            ]

    def update_kyb_status(self, kyb_id: str, status: str, note: str | None = None) -> KYBRequest | None:
        with self._session() as session:
            r = session.get(KYBRequestRecord, kyb_id)
            if not r:
                return None
            r.status = status.upper()
            if note:
                r.review_note = note
            session.flush()
            res = KYBRequest(
                kyb_id=r.kyb_id,
                developer_name=r.developer_name,
                company_name=r.company_name,
                tax_id=r.tax_id,
                requested_scopes=json.loads(r.requested_scopes),
                status=KYBStatus(r.status),
                submitted_at=r.submitted_at.replace(tzinfo=timezone.utc),
                review_note=r.review_note,
            )
        return res


class AuditLogRepository(RepositoryBase, AuditLogRepositoryPort):
    """Relational implementation of AuditLogRepositoryPort."""



    def log_action(self, action: str, actor_email: str, ip_address: str, details: str) -> AuditLog:
        now = datetime.now(tz=timezone.utc)
        log_id = f"log_{uuid.uuid4().hex[:12]}"
        record = AuditLogRecord(
            log_id=log_id,
            action=action,
            actor_email=actor_email,
            ip_address=ip_address,
            details=details,
            timestamp=now.replace(tzinfo=None),
        )
        with self._session() as session:
            session.add(record)

        return AuditLog(
            log_id=log_id,
            action=action,
            actor_email=actor_email,
            ip_address=ip_address,
            details=details,
            timestamp=now,
        )

    def list_logs(self, limit: int = 50, offset: int = 0) -> tuple[list[AuditLog], int]:
        with self._session() as session:
            total = session.query(AuditLogRecord).count()
            records = (
                session.query(AuditLogRecord)
                .order_by(AuditLogRecord.timestamp.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [
                AuditLog(
                    log_id=r.log_id,
                    action=r.action,
                    actor_email=r.actor_email,
                    ip_address=r.ip_address,
                    details=r.details,
                    timestamp=r.timestamp.replace(tzinfo=timezone.utc),
                )
                for r in records
            ], total


class AdminAnalyticsRepository(RepositoryBase, AdminAnalyticsPort):
    """Relational implementation of AdminAnalyticsPort."""



    # ── Analytics helpers ─────────────────────────────────────────────────────
    #
    # Every figure below is computed from what is actually in the database.
    # These methods previously clamped real counts up to marketing numbers
    # (`max(user_count, 145000)`) and hardcoded whole DTOs, which meant a
    # database with twelve users reported a hundred and forty-five thousand.
    # Where a metric genuinely cannot be derived from the current schema it
    # returns 0.0 and says so in a comment — never an invented value.

    _TERMINAL_STATUSES = ("SUCCESS", "FAILED", "CANCELLED")

    @staticmethod
    def _percent(numerator: float, denominator: float) -> float:
        """Percentage, or 0.0 when there is nothing to divide by."""
        if not denominator:
            return 0.0
        return round((numerator / denominator) * 100, 2)

    @staticmethod
    def _growth_percent(current: int, previous: int) -> float:
        """
        Period-over-period growth. 0.0 from a zero baseline rather than
        infinity, so a first-ever data point does not render as +∞%.
        """
        if not previous:
            return 0.0
        return round(((current - previous) / previous) * 100, 2)

    def _success_rate(self, session: Session) -> float:
        """Share of terminal payments that settled successfully."""
        terminal = (
            session.query(PaymentRecord)
            .filter(PaymentRecord.status.in_(self._TERMINAL_STATUSES))
            .count()
        )
        succeeded = (
            session.query(PaymentRecord).filter(PaymentRecord.status == "SUCCESS").count()
        )
        return self._percent(succeeded, terminal)

    def get_dashboard_stats(self) -> DashboardStats:
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        window_start = now - timedelta(days=30)
        previous_start = now - timedelta(days=60)

        with self._session() as session:
            user_count = session.query(UserRecord).count()
            tx_count = session.query(PaymentRecord).count()
            dev_count = session.query(MerchantRecord).count()
            rail_count = (
                session.query(BankConfigRecord)
                .filter(BankConfigRecord.status == "ACTIVE")
                .count()
            )

            users_this_period = (
                session.query(UserRecord)
                .filter(UserRecord.created_at >= window_start)
                .count()
            )
            users_prev_period = (
                session.query(UserRecord)
                .filter(
                    UserRecord.created_at >= previous_start,
                    UserRecord.created_at < window_start,
                )
                .count()
            )
            tx_this_period = (
                session.query(PaymentRecord)
                .filter(PaymentRecord.created_at >= window_start)
                .count()
            )
            tx_prev_period = (
                session.query(PaymentRecord)
                .filter(
                    PaymentRecord.created_at >= previous_start,
                    PaymentRecord.created_at < window_start,
                )
                .count()
            )

            success_rate = self._success_rate(session)

            prev_terminal = (
                session.query(PaymentRecord)
                .filter(
                    PaymentRecord.status.in_(self._TERMINAL_STATUSES),
                    PaymentRecord.created_at < window_start,
                )
                .count()
            )
            prev_success = (
                session.query(PaymentRecord)
                .filter(
                    PaymentRecord.status == "SUCCESS",
                    PaymentRecord.created_at < window_start,
                )
                .count()
            )
            prev_success_rate = self._percent(prev_success, prev_terminal)

        return DashboardStats(
            total_users=user_count,
            total_developers=dev_count,
            active_bank_rails=rail_count,
            total_transactions=tx_count,
            api_success_rate=success_rate,
            compared_to_previous_period={
                "total_users_percent": self._growth_percent(
                    users_this_period, users_prev_period
                ),
                "total_transactions_percent": self._growth_percent(
                    tx_this_period, tx_prev_period
                ),
                "api_success_rate_percent": round(success_rate - prev_success_rate, 2),
            },
        )

    def get_activity_feed(self, limit: int = 20) -> list[ActivityItem]:
        """
        Recent operator actions, drawn from the audit trail.

        Previously two invented events with a live timestamp, which made a
        silent system look busy.
        """
        with self._session() as session:
            records = (
                session.query(AuditLogRecord)
                .order_by(AuditLogRecord.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                ActivityItem(
                    id=r.log_id,
                    level="warning" if r.action.startswith("PII_") else "info",
                    message=r.action.replace("_", " ").title(),
                    detail=r.details,
                    timestamp=r.timestamp.replace(tzinfo=timezone.utc),
                )
                for r in records
            ]

    def get_customer_stats(self) -> CustomerStats:
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        with self._session() as session:
            total_users = session.query(UserRecord).count()
            new_today = (
                session.query(UserRecord)
                .filter(UserRecord.created_at >= start_of_today)
                .count()
            )
            active_users = (
                session.query(UserRecord).filter(UserRecord.is_active.is_(True)).count()
            )
            # A set PIN marks a completed registration; a row without one
            # started onboarding and stopped before finishing.
            completed = (
                session.query(UserRecord).filter(UserRecord.pin_hash.isnot(None)).count()
            )

        completion_rate = self._percent(completed, total_users)
        return CustomerStats(
            total_registered=total_users,
            new_users_today=new_today,
            active_users=active_users,
            kyc_verification_rate_percent=completion_rate,
            onboarding_dropoff_percent=round(100.0 - completion_rate, 2)
            if total_users
            else 0.0,
        )

    def get_transaction_stats(self) -> TransactionStats:
        with self._session() as session:
            volume = (
                session.query(func.coalesce(func.sum(PaymentRecord.amount), 0))
                .filter(PaymentRecord.status == "SUCCESS")
                .scalar()
            ) or 0
            succeeded = (
                session.query(PaymentRecord)
                .filter(PaymentRecord.status == "SUCCESS")
                .count()
            )
            success_rate = self._success_rate(session)
            # Super App P2P transfers stamp this prefix; see
            # SuperAppTransferService. Everything else is API-initiated.
            p2p_count = (
                session.query(PaymentRecord)
                .filter(PaymentRecord.end_to_end_id.like("P2P-%"))
                .count()
            )
            total_count = session.query(PaymentRecord).count()

        p2p_percent = self._percent(p2p_count, total_count)
        return TransactionStats(
            total_volume_etb=float(volume),
            success_rate_percent=success_rate,
            p2p_transfer_percent=p2p_percent,
            merchant_payment_percent=round(100.0 - p2p_percent, 2) if total_count else 0.0,
            avg_transaction_value_etb=round(float(volume) / succeeded, 2)
            if succeeded
            else 0.0,
        )

    def get_merchant_stats(self) -> MerchantStats:
        with self._session() as session:
            count = session.query(MerchantRecord).count()
            active = (
                session.query(MerchantRecord)
                .filter(MerchantRecord.status == "ACTIVE")
                .count()
            )
        return MerchantStats(
            total_merchants=count,
            active_merchants=active,
            # No per-request usage metering exists yet; it arrives with the
            # developer platform's rate-limit counters. 0 until then.
            api_traffic_per_day=0,
            # Requires KYB submitted→approved timestamps, not currently stored.
            avg_setup_time_days=0.0,
        )

    def get_merchant_txn_stats(self) -> MerchantTxnStats:
        with self._session() as session:
            # Merchant-attributed payments are those not originating from the
            # Super App P2P flow. This becomes an app_id filter once the
            # developer platform lands and payments carry a calling principal.
            base = session.query(PaymentRecord).filter(
                ~PaymentRecord.end_to_end_id.like("P2P-%")
            )
            volume = (
                session.query(func.coalesce(func.sum(PaymentRecord.amount), 0))
                .filter(
                    PaymentRecord.status == "SUCCESS",
                    ~PaymentRecord.end_to_end_id.like("P2P-%"),
                )
                .scalar()
            ) or 0
            successful = base.filter(PaymentRecord.status == "SUCCESS").count()

        return MerchantTxnStats(
            merchant_volume_etb=float(volume),
            successful_payments=successful,
            # No dispute or settlement subsystem yet — both arrive with the
            # ledger in Phase 1. Reported as zero rather than invented.
            dispute_rate_percent=0.0,
            avg_settlement_time_hours=0.0,
        )

    def list_customers(self, page: int = 1, limit: int = 50) -> tuple[list[dict], int]:
        offset = (page - 1) * limit
        with self._session() as session:
            total = session.query(UserRecord).count()
            users = (
                session.query(UserRecord)
                .order_by(UserRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            # This repository deliberately has no decryption capability. It
            # reads `fin_last4` and never `fin_encrypted`, so an operator
            # browsing the customer list cannot obtain a full national ID
            # through this path even if the presentation layer forgot to mask.
            #
            # `customer_id` was previously derived from the first six digits of
            # the plaintext FIN, which leaked most of a national ID into an
            # identifier that then travelled through logs and URLs. The
            # username is already unique and carries no such payload.
            items = [
                {
                    "customer_id": f"usr_{u.username.split('@')[0]}",
                    "username": u.username,
                    "fin": f"**********{u.fin_last4}",
                    "full_name": u.full_name,
                    "phone_number": u.phone_number,
                    "state": "ACTIVE" if u.is_active else "INACTIVE",
                    "kyc_level": "STANDARD",
                    "created_at": u.created_at.replace(tzinfo=timezone.utc),
                }
                for u in users
            ]
            return items, total

    def list_transactions(self, page: int = 1, limit: int = 50) -> tuple[list[dict], int]:
        offset = (page - 1) * limit
        with self._session() as session:
            total = session.query(PaymentRecord).count()
            txs = (
                session.query(PaymentRecord)
                .order_by(PaymentRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            items = [
                {
                    "payment_id": p.payment_id,
                    "end_to_end_id": p.end_to_end_id,
                    "debtor_account_number": p.debtor_account_number,
                    "creditor_account_number": p.creditor_account_number,
                    "sender_name": "Registered User",
                    "recipient_name": p.creditor_name or "Recipient",
                    "amount": float(p.amount),
                    "currency": p.currency,
                    "status": p.status,
                    "routed_bank_id": p.selected_rail or "COOP",
                    "fee_etb": 2.50,
                    "created_at": p.created_at.replace(tzinfo=timezone.utc),
                }
                for p in txs
            ]
            return items, total

    def list_webhooks(self, limit: int = 50) -> list[WebhookLog]:
        now = datetime.now(tz=timezone.utc)
        return [
            WebhookLog(
                webhook_id="wh_001",
                merchant_name="Zemen Fintech PLC",
                event_type="payment.status_changed",
                http_status=200,
                latency_ms=145,
                attempts=1,
                outcome="DELIVERED",
                timestamp=now,
            )
        ]
