"""
Ports: LedgerRepositoryPort, FeeRuleRepositoryPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.fee import FeeRule
from backend.domain.models.ledger import LedgerEntry, LedgerTransaction


class LedgerRepositoryPort(ABC):
    """
    Abstract Driven Port: Ledger persistence.

    Note the deliberate absence of update and delete. Ledger entries are
    immutable; a correction is a new opposing transaction. An implementation
    that offers a way to edit a posted entry has broken the audit trail this
    whole subsystem exists to provide.
    """

    @abstractmethod
    def post_transaction(self, transaction: LedgerTransaction) -> None:
        """
        Persist every entry of a balanced transaction atomically.

        All entries commit together or none do. A partially written
        transaction is an unbalanced ledger, which is unrecoverable without
        manual intervention.

        Args:
            transaction: A balanced :class:`~domain.models.ledger.LedgerTransaction`.
                         Its constructor has already enforced the zero-sum
                         invariant.

        Raises:
            ValueError: If `transaction_ref` has already been posted. Posting
                        is idempotent by reference, not by content.
        """
        ...

    @abstractmethod
    def get_entries_for_payment(self, payment_id: str) -> list[LedgerEntry]:
        """
        Retrieve every entry produced by one payment.

        Args:
            payment_id: The payment identifier.

        Returns:
            All entries, oldest first. Empty when the payment posted nothing.
        """
        ...

    @abstractmethod
    def get_entries_for_transaction(self, transaction_ref: str) -> list[LedgerEntry]:
        """
        Retrieve the entries of one transaction.

        Args:
            transaction_ref: The transaction reference.

        Returns:
            All entries sharing that reference.
        """
        ...

    @abstractmethod
    def transaction_exists(self, transaction_ref: str) -> bool:
        """
        Whether a transaction reference has already been posted.

        Used to make posting idempotent — a retried callback must not
        double-post a payment.

        Args:
            transaction_ref: The reference to check.

        Returns:
            True when entries already exist for that reference.
        """
        ...

    @abstractmethod
    def get_account_balance(self, account_ref: str) -> Decimal:
        """
        Net signed balance of an account.

        Args:
            account_ref: The account's natural key.

        Returns:
            Sum of signed amounts — debits positive, credits negative.
            Zero for an account with no entries.
        """
        ...

    @abstractmethod
    def get_revenue_summary(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Decimal]:
        """
        Accrued revenue share per bank over a period.

        Counts only real revenue entries; mirror entries are excluded, since
        they represent value EUPI never held.

        Args:
            start: Inclusive lower bound, or None for no lower bound.
            end:   Exclusive upper bound, or None for no upper bound.

        Returns:
            Mapping of bank_id to accrued revenue.
        """
        ...

    @abstractmethod
    def get_mirror_volume(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Decimal]:
        """
        Orchestrated payment volume per bank over a period.

        Counts only mirror entries — this is throughput, not income.

        Args:
            start: Inclusive lower bound, or None for no lower bound.
            end:   Exclusive upper bound, or None for no upper bound.

        Returns:
            Mapping of bank_id to gross volume moved.
        """
        ...


class FeeRuleRepositoryPort(ABC):
    """
    Abstract Driven Port: Fee rule persistence.

    Rules are versioned and append-only. `deactivate` retires a version rather
    than deleting it, because a deleted rule makes every payment it priced
    unexplainable.
    """

    @abstractmethod
    def create(self, rule: FeeRule) -> None:
        """
        Persist a new fee rule version.

        Args:
            rule: The rule to store.

        Raises:
            ValueError: If this (rule_id, version) pair already exists.
        """
        ...

    @abstractmethod
    def list_active(self) -> list[FeeRule]:
        """
        Every currently active rule, used to price a payment.

        Returns:
            All active rules across all versions.
        """
        ...

    @abstractmethod
    def list_all(self) -> list[FeeRule]:
        """
        Every rule including retired versions, for the admin portal and audit.

        Returns:
            All rules, newest version first.
        """
        ...

    @abstractmethod
    def get_version(self, rule_id: str, version: int) -> FeeRule | None:
        """
        Retrieve one exact rule version.

        This is how a historical payment's price is explained: the payment
        stores rule_id and version, and this returns precisely what priced it.

        Args:
            rule_id: The rule identifier.
            version: The exact version.

        Returns:
            The rule, or None if that version was never created.
        """
        ...

    @abstractmethod
    def latest_version(self, rule_id: str) -> int:
        """
        Highest version number recorded for a rule.

        Args:
            rule_id: The rule identifier.

        Returns:
            The latest version, or 0 when the rule has never existed.
        """
        ...

    @abstractmethod
    def deactivate(self, rule_id: str, version: int) -> None:
        """
        Retire a rule version without deleting it.

        Args:
            rule_id: The rule identifier.
            version: The version to retire.
        """
        ...
