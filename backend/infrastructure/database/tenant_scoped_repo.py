"""
Tenant Scoping Architecture — AppScope & TenantScopedRepository
===============================================================
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: Multi-tenant data isolation. Automatically scope queries by app_id.

Why tenant scoping
-------------------
In a multi-tenant developer platform, querying payments or webhooks by ID alone
is a severe vulnerability: a developer holding payment_id PAY-123 could read or
modify another developer's payment if the query lacks WHERE app_id = :app_id.

TenantScopedRepository guarantees that every query executed through it includes
app_id scoping by construction, eliminating cross-tenant data leaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from backend.domain.models.payment import Payment
from backend.infrastructure.database.models import PaymentRecord, WebhookEventRecord
from backend.infrastructure.database.session import Database, RepositoryBase
from backend.infrastructure.database.payment_repository import PaymentRepository


@dataclass(frozen=True)
class AppScope:
    """
    Identifies the active tenant context for a developer application request.
    """

    app_id: str
    environment: str = "SANDBOX"


class TenantScopedRepository(RepositoryBase):
    """
    Base repository for multi-tenant data access scoped to a specific AppScope.
    """

    def __init__(self, db: Database, app_scope: AppScope) -> None:
        super().__init__(db)
        self._app_scope = app_scope

    @property
    def app_id(self) -> str:
        return self._app_scope.app_id

    @property
    def environment(self) -> str:
        return self._app_scope.environment


class TenantPaymentRepository(TenantScopedRepository):
    """
    Tenant-scoped payment repository wrapper.

    Enforces WHERE app_id = self.app_id on every payment lookup, update, and listing.
    """

    def __init__(self, db: Database, app_scope: AppScope) -> None:
        super().__init__(db, app_scope)
        self._underlying = PaymentRepository(db)

    def save_payment(self, payment: Payment) -> None:
        """Insert or update a payment stamped with the tenant's app_id."""
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
            app_id=self.app_id,  # Stamped with tenant app_id
            created_at=payment.created_at.replace(tzinfo=None),
            updated_at=payment.updated_at.replace(tzinfo=None),
        )
        with self._session() as session:
            session.merge(record)

    def get_payment(self, payment_id: str) -> Payment | None:
        """Retrieve a payment by payment_id, enforcing app_id = self.app_id scoping."""
        with self._session() as session:
            record = (
                session.query(PaymentRecord)
                .filter(
                    PaymentRecord.payment_id == payment_id,
                    PaymentRecord.app_id == self.app_id,
                )
                .first()
            )
            return self._underlying._record_to_domain(record) if record else None

    def get_payment_by_end_to_end_id(self, end_to_end_id: str) -> Payment | None:
        """
        Retrieve a payment by end_to_end_id within this tenant's app_id scope.
        Allows distinct developer apps to reuse internal reference IDs.
        """
        with self._session() as session:
            record = (
                session.query(PaymentRecord)
                .filter(
                    PaymentRecord.end_to_end_id == end_to_end_id,
                    PaymentRecord.app_id == self.app_id,
                )
                .first()
            )
            return self._underlying._record_to_domain(record) if record else None

    def list_payments(self, limit: int = 50) -> list[Payment]:
        """List payments initiated by this developer application, newest first."""
        with self._session() as session:
            records = (
                session.query(PaymentRecord)
                .filter(PaymentRecord.app_id == self.app_id)
                .order_by(PaymentRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            return [self._underlying._record_to_domain(r) for r in records]
