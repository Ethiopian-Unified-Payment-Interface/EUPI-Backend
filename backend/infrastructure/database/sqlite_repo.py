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

    def get_payments_for_user(
        self,
        account_numbers: list[str],
        limit: int = 20,
    ) -> list[dict]:
        """
        Return recent payments where the user's linked accounts appear as debtor or creditor.

        Designed for GET /v1/superapp/transactions.  Queries the payments table
        directly — no bank CBS calls, no re-authentication required.  The caller
        supplies every account number the session user has linked; this method
        returns all payments that touched any of them.

        is_credit is True when the creditor_account_number belongs to the user
        (money arrived), False when the debtor_account_number belongs to the user
        (money left).  When both sides are the same user this will render as a
        credit, which is the safer default for a self-transfer edge case.

        Returns a list of plain dicts shaped for the SuperApp dashboard — not
        full Payment domain objects, since this is a read-only projection.
        """
        if not account_numbers:
            return []

        with self._session() as session:
            from sqlalchemy import or_
            acct_set = set(account_numbers)
            records = (
                session.query(PaymentRecord)
                .filter(
                    or_(
                        PaymentRecord.debtor_account_number.in_(acct_set),
                        PaymentRecord.creditor_account_number.in_(acct_set),
                    )
                )
                .order_by(PaymentRecord.created_at.desc())
                .limit(limit)
                .all()
            )

            result = []
            for r in records:
                is_credit = r.creditor_account_number in acct_set
                result.append({
                    "payment_id": r.payment_id,
                    "amount": str(r.amount),
                    "currency": r.currency,
                    "status": r.status,
                    "is_credit": is_credit,
                    "counterparty_name": r.creditor_name if not is_credit else None,
                    "counterparty_bank": (
                        r.creditor_bank_id if not is_credit else r.debtor_bank_id
                    ),
                    "remittance_info": r.remittance_info,
                    "created_at": r.created_at.isoformat() + "Z",
                })
            return result

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
            else:
                now = datetime.now()
                session.add(ConsentTokenRecord(
                    jti=jti,
                    fin="",
                    kyc_level="STANDARD",
                    scopes="[]",
                    issued_at=now,
                    expires_at=now,
                    is_revoked=True,
                ))

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

    # ══════════════════════════════════════════════════════════════════════════
    # User Consents Management (Super App Privacy & OAuth)
    # ══════════════════════════════════════════════════════════════════════════

    def get_user_consents(self, username: str) -> list[dict]:
        """Return all consent records granted by a Super App user, with app metadata."""
        import uuid
        from backend.infrastructure.database.models import UserConsentRecord, DeveloperAppRecord

        SCOPE_DESCRIPTIONS = {
            "accounts:read": "View linked account numbers, balances, and basic profile info.",
            "payments:initiate": "Initiate transfers and payments on your behalf.",
            "identity:read:fin": "Read National ID (FIN) and verified identity details.",
        }

        with self._session() as session:
            records = (
                session.query(UserConsentRecord, DeveloperAppRecord)
                .join(DeveloperAppRecord, UserConsentRecord.app_id == DeveloperAppRecord.app_id)
                .filter(UserConsentRecord.username == username)
                .all()
            )

            result = []
            for consent_rec, app_rec in records:
                result.append({
                    "consent_id": consent_rec.consent_id,
                    "app_id": app_rec.app_id,
                    "app_name": app_rec.app_name,
                    "merchant_name": app_rec.merchant_name,
                    "app_logo_url": getattr(app_rec, "app_logo_url", None),
                    "scope": consent_rec.scope,
                    "scope_description": SCOPE_DESCRIPTIONS.get(
                        consent_rec.scope, consent_rec.scope
                    ),
                    "status": consent_rec.status,
                    "granted_at": consent_rec.granted_at.isoformat() + "Z",
                    "expires_at": consent_rec.expires_at.isoformat() + "Z" if consent_rec.expires_at else None,
                    "revoked_at": consent_rec.revoked_at.isoformat() + "Z" if consent_rec.revoked_at else None,
                })
            return result

    def revoke_user_consent(self, username: str, consent_id: str) -> bool:
        """Revoke a single consent scope for a user."""
        from backend.infrastructure.database.models import UserConsentRecord
        with self._session() as session:
            record = (
                session.query(UserConsentRecord)
                .filter(
                    UserConsentRecord.consent_id == consent_id,
                    UserConsentRecord.username == username,
                )
                .first()
            )
            if not record:
                return False
            record.status = "REVOKED"
            record.revoked_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            return True

    def revoke_user_app_consents(self, username: str, app_id: str) -> bool:
        """Revoke all active permissions granted to a specific application."""
        from backend.infrastructure.database.models import UserConsentRecord
        with self._session() as session:
            records = (
                session.query(UserConsentRecord)
                .filter(
                    UserConsentRecord.app_id == app_id,
                    UserConsentRecord.username == username,
                    UserConsentRecord.status == "GRANTED",
                )
                .all()
            )
            if not records:
                return False
            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            for r in records:
                r.status = "REVOKED"
                r.revoked_at = now
            return True

    def grant_user_consent(self, username: str, app_id: str, scope: str) -> dict:
        """Record or update a user consent grant."""
        import uuid
        from backend.infrastructure.database.models import UserConsentRecord
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        consent_id = f"CNS-{uuid.uuid4().hex[:8].upper()}"

        with self._session() as session:
            existing = (
                session.query(UserConsentRecord)
                .filter(
                    UserConsentRecord.username == username,
                    UserConsentRecord.app_id == app_id,
                    UserConsentRecord.scope == scope,
                )
                .first()
            )
            if existing:
                existing.status = "GRANTED"
                existing.granted_at = now
                existing.revoked_at = None
                return {"consent_id": existing.consent_id, "status": "GRANTED"}
            else:
                record = UserConsentRecord(
                    consent_id=consent_id,
                    username=username,
                    app_id=app_id,
                    scope=scope,
                    status="GRANTED",
                    granted_at=now,
                )
                session.add(record)
                return {"consent_id": consent_id, "status": "GRANTED"}
