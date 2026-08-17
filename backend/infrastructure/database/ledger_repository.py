"""
Ledger & Fee Rule Repositories
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: Concrete implementations of the ledger port interfaces.

Note the absence of any update or delete path for ledger entries. That is not
an oversight: an append-only table is what makes the ledger auditable, and the
easiest way to guarantee it is to provide no method that could do otherwise.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Generator

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.application.ports.ledger_port import (
    FeeRuleRepositoryPort,
    LedgerRepositoryPort,
)
from backend.domain.models.fee import FeeRule, FeeType
from backend.domain.models.ledger import (
    EntryDirection,
    LedgerEntry,
    LedgerTransaction,
    TransactionType,
)
from backend.infrastructure.database.session import RepositoryBase
from backend.infrastructure.database.models import Base, FeeRuleRecord, LedgerEntryRecord


def _bank_from_account_ref(account_ref: str) -> str | None:
    """
    Extract the bank identifier from an account_ref.

    Refs are structured `TYPE:BANK[:ACCOUNT]`, so the bank is the second
    segment where present. Denormalised onto the row at write time for
    reporting; this helper is what derives it.
    """
    parts = account_ref.split(":")
    return parts[1] if len(parts) >= 2 and parts[1] else None


class LedgerRepository(RepositoryBase, LedgerRepositoryPort):
    """Relational implementation of LedgerRepositoryPort."""



    def post_transaction(self, transaction: LedgerTransaction) -> None:
        """
        Write every entry of a balanced transaction in a single commit.

        The all-or-nothing commit is the point: a partial write leaves the
        ledger unbalanced, which cannot be repaired without manual accounting.
        """
        with self._session() as session:
            existing = (
                session.query(LedgerEntryRecord)
                .filter(LedgerEntryRecord.transaction_ref == transaction.transaction_ref)
                .count()
            )
            if existing:
                raise ValueError(
                    f"Transaction '{transaction.transaction_ref}' has already been posted. "
                    f"Ledger entries are immutable; post a reversal instead."
                )

            for entry in transaction.entries:
                session.add(
                    LedgerEntryRecord(
                        entry_id=entry.entry_id,
                        transaction_ref=entry.transaction_ref,
                        account_ref=entry.account_ref,
                        direction=entry.direction.value,
                        amount=entry.amount,
                        currency=entry.currency,
                        is_mirror=entry.is_mirror,
                        bank_id=_bank_from_account_ref(entry.account_ref),
                        payment_id=entry.payment_id,
                        app_id=entry.app_id,
                        description=entry.description,
                        transaction_type=transaction.transaction_type.value,
                        created_at=entry.created_at.replace(tzinfo=None),
                    )
                )

    def get_entries_for_payment(self, payment_id: str) -> list[LedgerEntry]:
        with self._session() as session:
            records = (
                session.query(LedgerEntryRecord)
                .filter(LedgerEntryRecord.payment_id == payment_id)
                .order_by(LedgerEntryRecord.created_at.asc())
                .all()
            )
            return [self._to_domain(r) for r in records]

    def get_entries_for_transaction(self, transaction_ref: str) -> list[LedgerEntry]:
        with self._session() as session:
            records = (
                session.query(LedgerEntryRecord)
                .filter(LedgerEntryRecord.transaction_ref == transaction_ref)
                .order_by(LedgerEntryRecord.created_at.asc())
                .all()
            )
            return [self._to_domain(r) for r in records]

    def transaction_exists(self, transaction_ref: str) -> bool:
        with self._session() as session:
            return (
                session.query(LedgerEntryRecord)
                .filter(LedgerEntryRecord.transaction_ref == transaction_ref)
                .count()
                > 0
            )

    def get_account_balance(self, account_ref: str) -> Decimal:
        """Net signed balance: debits positive, credits negative."""
        with self._session() as session:
            debits = (
                session.query(func.coalesce(func.sum(LedgerEntryRecord.amount), 0))
                .filter(
                    LedgerEntryRecord.account_ref == account_ref,
                    LedgerEntryRecord.direction == EntryDirection.DEBIT.value,
                )
                .scalar()
            ) or Decimal("0")
            credits = (
                session.query(func.coalesce(func.sum(LedgerEntryRecord.amount), 0))
                .filter(
                    LedgerEntryRecord.account_ref == account_ref,
                    LedgerEntryRecord.direction == EntryDirection.CREDIT.value,
                )
                .scalar()
            ) or Decimal("0")
            return Decimal(str(debits)) - Decimal(str(credits))

    def get_revenue_summary(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Decimal]:
        """
        Accrued revenue per bank, from the receivable side only.

        Reads FEE_RECEIVABLE debits rather than FEE_REVENUE credits because the
        receivable carries the bank attribution — revenue is a single pooled
        account and cannot be split per bank.
        """
        with self._session() as session:
            query = (
                session.query(
                    LedgerEntryRecord.bank_id,
                    func.coalesce(func.sum(LedgerEntryRecord.amount), 0),
                )
                .filter(
                    LedgerEntryRecord.is_mirror.is_(False),
                    LedgerEntryRecord.direction == EntryDirection.DEBIT.value,
                    LedgerEntryRecord.account_ref.like("FEE_RECEIVABLE:%"),
                )
            )
            query = self._apply_window(query, start, end)
            rows = query.group_by(LedgerEntryRecord.bank_id).all()
            return {
                bank_id: Decimal(str(total))
                for bank_id, total in rows
                if bank_id is not None
            }

    def get_mirror_volume(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Decimal]:
        """
        Orchestrated volume per bank.

        Counts credit legs only. Each payment produces one credit (funds
        leaving the debtor) and one debit (funds arriving at the creditor);
        summing both would double-count every transfer.
        """
        with self._session() as session:
            query = (
                session.query(
                    LedgerEntryRecord.bank_id,
                    func.coalesce(func.sum(LedgerEntryRecord.amount), 0),
                )
                .filter(
                    LedgerEntryRecord.is_mirror.is_(True),
                    LedgerEntryRecord.direction == EntryDirection.CREDIT.value,
                )
            )
            query = self._apply_window(query, start, end)
            rows = query.group_by(LedgerEntryRecord.bank_id).all()
            return {
                bank_id: Decimal(str(total))
                for bank_id, total in rows
                if bank_id is not None
            }

    @staticmethod
    def _apply_window(query, start: datetime | None, end: datetime | None):
        """Apply an optional half-open [start, end) window on created_at."""
        if start is not None:
            query = query.filter(
                LedgerEntryRecord.created_at >= start.replace(tzinfo=None)
            )
        if end is not None:
            query = query.filter(LedgerEntryRecord.created_at < end.replace(tzinfo=None))
        return query

    @staticmethod
    def _to_domain(record: LedgerEntryRecord) -> LedgerEntry:
        return LedgerEntry(
            entry_id=record.entry_id,
            transaction_ref=record.transaction_ref,
            account_ref=record.account_ref,
            direction=EntryDirection(record.direction),
            amount=Decimal(str(record.amount)),
            currency=record.currency,
            is_mirror=record.is_mirror,
            payment_id=record.payment_id,
            app_id=record.app_id,
            description=record.description,
            created_at=record.created_at.replace(tzinfo=timezone.utc),
        )


class FeeRuleRepository(RepositoryBase, FeeRuleRepositoryPort):
    """Relational implementation of FeeRuleRepositoryPort."""



    def create(self, rule: FeeRule) -> None:
        with self._session() as session:
            if session.get(FeeRuleRecord, (rule.rule_id, rule.version)) is not None:
                raise ValueError(
                    f"Fee rule '{rule.rule_id}' version {rule.version} already exists. "
                    f"Rule versions are immutable; publish a new version instead."
                )
            session.add(
                FeeRuleRecord(
                    rule_id=rule.rule_id,
                    version=rule.version,
                    description=rule.description,
                    bank_id=rule.bank_id,
                    transaction_type=rule.transaction_type.value,
                    currency=rule.currency,
                    min_amount=rule.min_amount,
                    max_amount=rule.max_amount,
                    fee_type=rule.fee_type.value,
                    flat_fee=rule.flat_fee,
                    percentage_bps=rule.percentage_bps,
                    min_fee=rule.min_fee,
                    max_fee=rule.max_fee,
                    revenue_share_bps=rule.revenue_share_bps,
                    is_active=rule.is_active,
                    effective_from=rule.effective_from.replace(tzinfo=None),
                    created_at=rule.created_at.replace(tzinfo=None),
                )
            )

    def list_active(self) -> list[FeeRule]:
        with self._session() as session:
            records = (
                session.query(FeeRuleRecord)
                .filter(FeeRuleRecord.is_active.is_(True))
                .all()
            )
            return [self._to_domain(r) for r in records]

    def list_all(self) -> list[FeeRule]:
        with self._session() as session:
            records = (
                session.query(FeeRuleRecord)
                .order_by(FeeRuleRecord.rule_id.asc(), FeeRuleRecord.version.desc())
                .all()
            )
            return [self._to_domain(r) for r in records]

    def get_version(self, rule_id: str, version: int) -> FeeRule | None:
        with self._session() as session:
            record = session.get(FeeRuleRecord, (rule_id, version))
            return self._to_domain(record) if record else None

    def latest_version(self, rule_id: str) -> int:
        with self._session() as session:
            highest = (
                session.query(func.max(FeeRuleRecord.version))
                .filter(FeeRuleRecord.rule_id == rule_id)
                .scalar()
            )
            return int(highest or 0)

    def deactivate(self, rule_id: str, version: int) -> None:
        """
        Retire a version. The row is kept — deleting it would make every
        payment priced under it unexplainable.
        """
        with self._session() as session:
            record = session.get(FeeRuleRecord, (rule_id, version))
            if record is None:
                raise ValueError(f"Fee rule '{rule_id}' version {version} not found.")
            record.is_active = False

    @staticmethod
    def _to_domain(record: FeeRuleRecord) -> FeeRule:
        return FeeRule(
            rule_id=record.rule_id,
            version=record.version,
            description=record.description,
            bank_id=record.bank_id,
            transaction_type=TransactionType(record.transaction_type),
            currency=record.currency,
            min_amount=Decimal(str(record.min_amount)),
            max_amount=Decimal(str(record.max_amount)) if record.max_amount is not None else None,
            fee_type=FeeType(record.fee_type),
            flat_fee=Decimal(str(record.flat_fee)),
            percentage_bps=record.percentage_bps,
            min_fee=Decimal(str(record.min_fee)) if record.min_fee is not None else None,
            max_fee=Decimal(str(record.max_fee)) if record.max_fee is not None else None,
            revenue_share_bps=record.revenue_share_bps,
            is_active=record.is_active,
            effective_from=record.effective_from.replace(tzinfo=timezone.utc),
            created_at=record.created_at.replace(tzinfo=timezone.utc),
        )
