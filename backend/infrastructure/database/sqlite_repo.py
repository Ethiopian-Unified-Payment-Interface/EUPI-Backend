"""
SQLite Repository — Payment, Token & Webhook Persistence
=========================================================
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: ONLY layer allowed to touch the database.

Single SQLiteRepository class providing:
  - Full CRUD for Payment domain objects (serialise ↔ ORM model)
  - Consent token issuance tracking & revocation
  - Webhook event audit log
  - startup loader: restore in-memory payment cache from DB on server restart
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.domain.models.payment import (
    Payment,
    PaymentInitiateRequest,
    PaymentRail,
    PaymentStatus,
)
from backend.infrastructure.database.models import (
    Base,
    ConsentTokenRecord,
    PaymentRecord,
    WebhookEventRecord,
)


class SQLiteRepository:
    """
    SQLite-backed repository for all persistent gateway state.

    Instantiated once in main.py and injected wherever persistence is needed.
    Uses SQLAlchemy Core session management with explicit commit/rollback.
    """

    def __init__(self, db_url: str = settings.DATABASE_URL) -> None:
        self._engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},  # Required for SQLite + threading
            echo=settings.DEBUG,
        )
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine, autoflush=False)

    # ── Session Context Manager ────────────────────────────────────────────────

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        """Provide a transactional scope. Commits on success, rolls back on error."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ══════════════════════════════════════════════════════════════════════════
    # Payment CRUD
    # ══════════════════════════════════════════════════════════════════════════

    def save_payment(self, payment: Payment) -> None:
        """Insert or update a Payment. Safe to call on both create and update."""
        req = payment.initiate_request
        record = PaymentRecord(
            payment_id=payment.payment_id,
            status=payment.status.value,
            selected_rail=payment.selected_rail.value if payment.selected_rail else None,
            bank_order_reference=payment.bank_order_reference,
            consent_token=payment.consent_token,
            failure_reason=payment.failure_reason,
            webhook_url=payment.webhook_url,
            debtor_account_number=req.debtor_account_number,
            debtor_bank_id=req.debtor_bank_id,
            creditor_account_number=req.creditor_account_number,
            creditor_bank_id=req.creditor_bank_id,
            creditor_name=req.creditor_name,
            amount=req.amount,
            currency=req.currency,
            end_to_end_id=req.end_to_end_id,
            remittance_info=req.remittance_info,
            created_at=payment.created_at.replace(tzinfo=None),  # SQLite stores naive datetimes
            updated_at=payment.updated_at.replace(tzinfo=None),
        )
        with self._session() as session:
            session.merge(record)  # INSERT or UPDATE based on primary key

    def get_payment(self, payment_id: str) -> Payment | None:
        """Retrieve a single Payment by its gateway payment_id."""
        with self._session() as session:
            record = session.get(PaymentRecord, payment_id)
            return self._record_to_domain(record) if record else None

    def update_payment(self, payment: Payment) -> None:
        """Alias of save_payment for semantic clarity at the call site."""
        self.save_payment(payment)

    def load_all_payments(self) -> dict[str, Payment]:
        """
        Reload all persisted payments into memory.
        Called at server startup to restore in-memory state from the DB.
        """
        with self._session() as session:
            records = session.query(PaymentRecord).all()
            return {r.payment_id: self._record_to_domain(r) for r in records}

    def _record_to_domain(self, record: PaymentRecord) -> Payment:
        """Convert a PaymentRecord ORM object back into a Payment domain model."""
        req = PaymentInitiateRequest(
            debtor_account_number=record.debtor_account_number,
            debtor_bank_id=record.debtor_bank_id,
            creditor_account_number=record.creditor_account_number,
            creditor_bank_id=record.creditor_bank_id,
            creditor_name=record.creditor_name,
            amount=Decimal(str(record.amount)),
            currency=record.currency,
            end_to_end_id=record.end_to_end_id,
            remittance_info=record.remittance_info,
        )
        return Payment(
            payment_id=record.payment_id,
            status=PaymentStatus(record.status),
            initiate_request=req,
            selected_rail=PaymentRail(record.selected_rail) if record.selected_rail else None,
            bank_order_reference=record.bank_order_reference,
            consent_token=record.consent_token,
            failure_reason=record.failure_reason,
            webhook_url=record.webhook_url,
            created_at=record.created_at.replace(tzinfo=timezone.utc),
            updated_at=record.updated_at.replace(tzinfo=timezone.utc),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Consent Token Management
    # ══════════════════════════════════════════════════════════════════════════

    def save_token(
        self,
        jti: str,
        fin: str,
        kyc_level: str,
        scopes: list[str],
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        """Record a newly issued JWT in the database (for revocation tracking)."""
        record = ConsentTokenRecord(
            jti=jti,
            fin=fin,
            kyc_level=kyc_level,
            scopes=json.dumps(scopes),
            issued_at=issued_at.replace(tzinfo=None),
            expires_at=expires_at.replace(tzinfo=None),
            is_revoked=False,
        )
        with self._session() as session:
            session.merge(record)

    def is_token_revoked(self, jti: str) -> bool:
        """Return True if this JTI has been explicitly revoked."""
        with self._session() as session:
            record = session.get(ConsentTokenRecord, jti)
            return record.is_revoked if record else False

    def revoke_token(self, jti: str) -> None:
        """Revoke a token by JTI. Future requests with this token will be rejected."""
        with self._session() as session:
            record = session.get(ConsentTokenRecord, jti)
            if record:
                record.is_revoked = True

    # ══════════════════════════════════════════════════════════════════════════
    # Webhook Event Log
    # ══════════════════════════════════════════════════════════════════════════

    def create_webhook_event(
        self,
        payment_id: str,
        webhook_url: str,
        payload: dict,
    ) -> str:
        """
        Create a pending webhook delivery record.
        Returns the event_id for later status updates.
        """
        event_id = f"WH-{uuid.uuid4().hex[:16].upper()}"
        record = WebhookEventRecord(
            event_id=event_id,
            payment_id=payment_id,
            webhook_url=webhook_url,
            payload_json=json.dumps(payload),
            http_status_code=None,
            attempts=0,
            last_attempted_at=None,
            delivered=False,
            created_at=datetime.now(tz=timezone.utc).replace(tzinfo=None),
        )
        with self._session() as session:
            session.add(record)
        return event_id

    def mark_webhook_delivered(
        self,
        event_id: str,
        http_status_code: int,
        delivered: bool,
    ) -> None:
        """Update a webhook event after a delivery attempt."""
        with self._session() as session:
            record = session.get(WebhookEventRecord, event_id)
            if record:
                record.http_status_code = http_status_code
                record.delivered = delivered
                record.attempts = (record.attempts or 0) + 1
                record.last_attempted_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    def get_pending_webhooks(self) -> list[WebhookEventRecord]:
        """Return all undelivered webhook events for retry processing."""
        with self._session() as session:
            return session.query(WebhookEventRecord).filter(
                WebhookEventRecord.delivered == False  # noqa: E712
            ).all()
