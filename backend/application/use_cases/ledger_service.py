"""
Use Case: Ledger Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Builds and posts the balanced transactions that record settled payments and
accrued revenue. This is the only place in the system that writes to the ledger.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from backend.application.ports.ledger_port import LedgerRepositoryPort
from backend.domain.models.fee import FeeQuote
from backend.domain.models.ledger import (
    EntryDirection,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    TransactionType,
)

logger = logging.getLogger(__name__)


class LedgerService:
    """
    Double-entry posting for payments and revenue.

    Injected dependencies (constructor injection / Dependency Inversion):
      - ledger_repo: Persistence for balanced transactions.
    """

    def __init__(self, ledger_repo: LedgerRepositoryPort) -> None:
        self._ledger_repo = ledger_repo

    # ── Posting ───────────────────────────────────────────────────────────────

    def record_settled_payment(
        self,
        payment_id: str,
        debtor_bank_id: str,
        debtor_account_number: str,
        creditor_bank_id: str,
        creditor_account_number: str,
        amount: Decimal,
        currency: str,
        fee_quote: FeeQuote | None = None,
        app_id: str | None = None,
    ) -> LedgerTransaction | None:
        """
        Record a payment that reached SUCCESS.

        Posts up to two balanced entry sets:

        **Principal** (mirror) — value that moved at the banks. The debtor's
        account is credited (funds left it) and the creditor's debited (funds
        arrived). EUPI never held this money; these entries exist to answer
        "what did we orchestrate?" and to reconcile against bank statements.

        **Fee** (real) — only when `fee_quote` is supplied. EUPI accrues a
        receivable against the bank and recognises revenue. Note this books
        *EUPI's share*, not the whole customer fee: the bank keeps the rest and
        it never touches EUPI's books.

        Posting is idempotent by `payment_id`. A retried callback returns None
        rather than double-posting — this guard is the difference between a
        flaky webhook and a corrupted ledger.

        Args:
            payment_id:              Payment being recorded.
            debtor_bank_id:          Originating bank.
            debtor_account_number:   Source account.
            creditor_bank_id:        Destination bank.
            creditor_account_number: Destination account.
            amount:                  Principal amount moved.
            currency:                ISO 4217 code.
            fee_quote:               Pricing, if the payment was priced.
            app_id:                  Developer app that initiated it, if any.

        Returns:
            The posted transaction, or None when it was already recorded.
        """
        principal_ref = f"{payment_id}:principal"

        if self._ledger_repo.transaction_exists(principal_ref):
            logger.info(
                "Ledger entries already exist for payment; skipping re-post.",
                extra={"payment_id": payment_id},
            )
            return None

        transaction_type = TransactionType.classify(debtor_bank_id, creditor_bank_id)
        entries: list[LedgerEntry] = []

        # ── Principal: mirror of the bank-side movement ───────────────────────
        debtor_ref = LedgerAccount.customer_ref(debtor_bank_id, debtor_account_number)
        creditor_ref = LedgerAccount.customer_ref(creditor_bank_id, creditor_account_number)

        entries.append(
            self._entry(
                transaction_ref=principal_ref,
                account_ref=debtor_ref,
                direction=EntryDirection.CREDIT,  # funds left this account
                amount=amount,
                currency=currency,
                is_mirror=True,
                payment_id=payment_id,
                app_id=app_id,
                description=f"Payment {payment_id} debited from {debtor_bank_id}",
            )
        )
        entries.append(
            self._entry(
                transaction_ref=principal_ref,
                account_ref=creditor_ref,
                direction=EntryDirection.DEBIT,  # funds arrived here
                amount=amount,
                currency=currency,
                is_mirror=True,
                payment_id=payment_id,
                app_id=app_id,
                description=f"Payment {payment_id} credited to {creditor_bank_id}",
            )
        )

        # ── Fee: EUPI's own books ────────────────────────────────────────────
        if fee_quote is not None and fee_quote.eupi_revenue > 0:
            receivable_ref = LedgerAccount.fee_receivable_ref(fee_quote.bank_id)
            revenue_ref = LedgerAccount.fee_revenue_ref(fee_quote.currency)

            entries.append(
                self._entry(
                    transaction_ref=principal_ref,
                    account_ref=receivable_ref,
                    direction=EntryDirection.DEBIT,  # the bank now owes us
                    amount=fee_quote.eupi_revenue,
                    currency=fee_quote.currency,
                    is_mirror=False,
                    payment_id=payment_id,
                    app_id=app_id,
                    description=(
                        f"Revenue share receivable from {fee_quote.bank_id} "
                        f"(rule {fee_quote.rule_id} v{fee_quote.rule_version})"
                    ),
                )
            )
            entries.append(
                self._entry(
                    transaction_ref=principal_ref,
                    account_ref=revenue_ref,
                    direction=EntryDirection.CREDIT,  # income recognised
                    amount=fee_quote.eupi_revenue,
                    currency=fee_quote.currency,
                    is_mirror=False,
                    payment_id=payment_id,
                    app_id=app_id,
                    description=f"Fee revenue on payment {payment_id}",
                )
            )

        # Construction enforces the zero-sum invariant; an unbalanced set
        # raises here rather than reaching the database.
        transaction = LedgerTransaction(
            transaction_ref=principal_ref,
            transaction_type=transaction_type,
            entries=entries,
            created_at=datetime.now(tz=timezone.utc),
        )

        self._ledger_repo.post_transaction(transaction)

        logger.info(
            "Posted ledger transaction",
            extra={
                "payment_id": payment_id,
                "transaction_type": transaction_type.value,
                "entry_count": len(entries),
            },
        )
        return transaction

    def record_reversal(self, payment_id: str, reason: str) -> LedgerTransaction | None:
        """
        Reverse a previously settled payment.

        Posts an opposing entry for each original entry rather than deleting
        anything. A reversed payment leaves two visible transactions — the
        original and its reversal — which is what an auditor needs to see.

        Args:
            payment_id: The payment to reverse.
            reason:     Why, recorded in each entry's description.

        Returns:
            The reversal transaction, or None if there was nothing to reverse
            or it was already reversed.
        """
        original = self._ledger_repo.get_entries_for_transaction(f"{payment_id}:principal")
        if not original:
            logger.warning(
                "Reversal requested for a payment with no ledger entries.",
                extra={"payment_id": payment_id},
            )
            return None

        reversal_ref = f"{payment_id}:reversal"
        if self._ledger_repo.transaction_exists(reversal_ref):
            logger.info("Payment already reversed.", extra={"payment_id": payment_id})
            return None

        opposite = {
            EntryDirection.DEBIT: EntryDirection.CREDIT,
            EntryDirection.CREDIT: EntryDirection.DEBIT,
        }

        entries = [
            self._entry(
                transaction_ref=reversal_ref,
                account_ref=source.account_ref,
                direction=opposite[source.direction],
                amount=source.amount,
                currency=source.currency,
                is_mirror=source.is_mirror,
                payment_id=payment_id,
                app_id=source.app_id,
                description=f"Reversal of {source.entry_id}: {reason}",
            )
            for source in original
        ]

        transaction = LedgerTransaction(
            transaction_ref=reversal_ref,
            transaction_type=TransactionType.INTRA_BANK,
            entries=entries,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._ledger_repo.post_transaction(transaction)

        logger.info(
            "Posted reversal", extra={"payment_id": payment_id, "reason": reason}
        )
        return transaction

    # ── Reporting ─────────────────────────────────────────────────────────────

    def get_payment_entries(self, payment_id: str) -> list[LedgerEntry]:
        """Every ledger entry produced by one payment, oldest first."""
        return self._ledger_repo.get_entries_for_payment(payment_id)

    def get_account_balance(self, account_ref: str) -> Decimal:
        """Net signed balance of one account. Debits positive."""
        return self._ledger_repo.get_account_balance(account_ref)

    def get_reconciliation(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, dict[str, Decimal]]:
        """
        Per-bank position for a period.

        Reports orchestrated volume and accrued revenue **separately**, because
        they are different books: volume is money that moved at the banks and
        revenue is money owed to EUPI. Netting them produces a number that
        means nothing.

        This is the first report a bank partner will audit, which is why it is
        built now rather than after the first invoice.

        Args:
            start: Inclusive lower bound, or None.
            end:   Exclusive upper bound, or None.

        Returns:
            Mapping of bank_id to `{"orchestrated_volume": …, "accrued_revenue": …}`.
        """
        volume = self._ledger_repo.get_mirror_volume(start, end)
        revenue = self._ledger_repo.get_revenue_summary(start, end)

        return {
            bank_id: {
                "orchestrated_volume": volume.get(bank_id, Decimal("0")),
                "accrued_revenue": revenue.get(bank_id, Decimal("0")),
            }
            for bank_id in sorted(set(volume) | set(revenue))
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _entry(
        transaction_ref: str,
        account_ref: str,
        direction: EntryDirection,
        amount: Decimal,
        currency: str,
        is_mirror: bool,
        payment_id: str | None,
        app_id: str | None,
        description: str,
    ) -> LedgerEntry:
        """Build one entry with a fresh identifier and UTC timestamp."""
        return LedgerEntry(
            entry_id=f"le_{uuid.uuid4().hex[:20]}",
            transaction_ref=transaction_ref,
            account_ref=account_ref,
            direction=direction,
            amount=amount,
            currency=currency.strip().upper(),
            is_mirror=is_mirror,
            payment_id=payment_id,
            app_id=app_id,
            description=description,
            created_at=datetime.now(tz=timezone.utc),
        )
