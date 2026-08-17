"""
Domain Model: Ledger
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.

Double-entry accounting for payments EUPI orchestrates and revenue EUPI earns.

What this ledger is — and is not
--------------------------------
EUPI operates on a **revenue-share** model: it never holds customer funds. The
money moves bank-to-bank; EUPI orchestrates and is paid a share of the fee the
bank collects.

That produces two distinct kinds of entry, and conflating them is the mistake
this module exists to prevent:

1. **Mirror entries** (`is_mirror=True`) — a record of value that moved *at the
   banks*. EUPI never controlled these funds. They exist so the platform can
   answer "what did we orchestrate?" and reconcile against bank statements.
   They are NOT a claim on anything.

2. **Revenue entries** (`is_mirror=False`) — EUPI's own books. When a fee is
   charged, EUPI accrues a receivable from the bank and recognises revenue.
   These are real balance-sheet positions.

Both balance independently. A reconciliation that nets the two together is
wrong, which is why every entry carries the flag.

The invariant
-------------
Within a single `transaction_ref`, signed amounts sum to exactly zero. Debits
are positive, credits negative. This is enforced in `LedgerTransaction` and
asserted in tests; nothing may write entries except through a balanced
transaction.

Money is `Decimal` throughout. Never float: 0.1 + 0.2 != 0.3 in binary floating
point, and a payments ledger that drifts by a hundredth is a ledger nobody can
audit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class TransactionType(str, Enum):
    """
    How a payment settles, which drives both pricing and operational risk.

    INTRA_BANK is the strategically important case: both accounts sit in the
    same core banking system, so it is an internal book transfer requiring no
    interbank settlement at all. It is cheaper, faster, and — critically — it
    can go live with a single bank agreement.

    CROSS_BANK requires interbank settlement (EthSwitch or bilateral), which
    is a materially larger operational and regulatory undertaking.
    """

    INTRA_BANK = "INTRA_BANK"
    CROSS_BANK = "CROSS_BANK"

    @classmethod
    def classify(cls, debtor_bank_id: str, creditor_bank_id: str) -> "TransactionType":
        """
        Determine settlement type from the two bank identifiers.

        Args:
            debtor_bank_id:   Originating bank.
            creditor_bank_id: Destination bank.

        Returns:
            INTRA_BANK when both sides are the same bank, CROSS_BANK otherwise.

        Examples:
            >>> TransactionType.classify("COOP", "COOP")
            <TransactionType.INTRA_BANK: 'INTRA_BANK'>
            >>> TransactionType.classify("COOP", "CBE")
            <TransactionType.CROSS_BANK: 'CROSS_BANK'>
        """
        normalised_debtor = (debtor_bank_id or "").strip().upper()
        normalised_creditor = (creditor_bank_id or "").strip().upper()
        if normalised_debtor and normalised_debtor == normalised_creditor:
            return cls.INTRA_BANK
        return cls.CROSS_BANK


class LedgerAccountType(str, Enum):
    """
    Classification of a ledger account.

    CUSTOMER and BANK_SETTLEMENT are mirror accounts — they track value that
    moved at a bank, not value EUPI holds. FEE_RECEIVABLE and FEE_REVENUE are
    EUPI's own books.
    """

    CUSTOMER = "CUSTOMER"
    """Mirror of a customer's bank account, keyed by bank + account number."""

    BANK_SETTLEMENT = "BANK_SETTLEMENT"
    """Mirror of a bank's aggregate position across payments EUPI orchestrated."""

    FEE_RECEIVABLE = "FEE_RECEIVABLE"
    """What a bank owes EUPI in accrued revenue share. A real asset."""

    FEE_REVENUE = "FEE_REVENUE"
    """EUPI's recognised fee income. A real income account."""

    @property
    def is_mirror(self) -> bool:
        """True when this account tracks funds EUPI never controlled."""
        return self in (LedgerAccountType.CUSTOMER, LedgerAccountType.BANK_SETTLEMENT)


class EntryDirection(str, Enum):
    """Side of a double-entry posting."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

    @property
    def sign(self) -> int:
        """+1 for a debit, -1 for a credit. Used to compute the zero-sum check."""
        return 1 if self is EntryDirection.DEBIT else -1


class LedgerAccount(BaseModel):
    """
    An account in EUPI's ledger.

    `account_ref` is the stable natural key: for a customer account it is
    `CUSTOMER:{bank_id}:{account_number}`, for a bank position
    `BANK_SETTLEMENT:{bank_id}`, and so on. Deriving it rather than allocating
    surrogate IDs means an entry can be posted without a prior lookup round-trip.
    """

    account_ref: str = Field(
        ...,
        description="Stable natural key for this account.",
        examples=["CUSTOMER:COOP:1000234567890"],
    )
    account_type: LedgerAccountType = Field(
        ...,
        description="Classification determining whether this is a mirror or a real position.",
    )
    bank_id: str | None = Field(
        default=None,
        description="Bank this account belongs to, where applicable.",
        examples=["COOP"],
    )
    currency: str = Field(
        default="ETB",
        description="ISO 4217 currency. Accounts are single-currency by design.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp of first use.",
    )

    @staticmethod
    def customer_ref(bank_id: str, account_number: str) -> str:
        """Build the account_ref for a customer's bank account."""
        return f"CUSTOMER:{bank_id.strip().upper()}:{account_number.strip()}"

    @staticmethod
    def bank_settlement_ref(bank_id: str) -> str:
        """Build the account_ref for a bank's settlement position."""
        return f"BANK_SETTLEMENT:{bank_id.strip().upper()}"

    @staticmethod
    def fee_receivable_ref(bank_id: str) -> str:
        """Build the account_ref for revenue share owed by a bank."""
        return f"FEE_RECEIVABLE:{bank_id.strip().upper()}"

    @staticmethod
    def fee_revenue_ref(currency: str = "ETB") -> str:
        """Build the account_ref for EUPI's fee income."""
        return f"FEE_REVENUE:{currency.strip().upper()}"


class LedgerEntry(BaseModel):
    """
    A single immutable posting.

    Entries are never updated or deleted. A correction is a new, opposing
    entry — an audit trail that can be rewritten is not an audit trail.
    """

    entry_id: str = Field(
        ...,
        description="Unique identifier for this posting.",
    )
    transaction_ref: str = Field(
        ...,
        description=(
            "Groups the entries of one balanced transaction. Usually the "
            "payment_id, suffixed for distinct entry sets (e.g. ':fee')."
        ),
        examples=["pay_01HZK5X3:principal"],
    )
    account_ref: str = Field(
        ...,
        description="Account this entry posts against.",
    )
    direction: EntryDirection = Field(
        ...,
        description="DEBIT or CREDIT.",
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        description="Always positive. Direction carries the sign.",
        examples=["2500.00"],
    )
    currency: str = Field(
        default="ETB",
        description="ISO 4217 currency code.",
    )
    is_mirror: bool = Field(
        ...,
        description=(
            "True when this records value that moved at a bank rather than a "
            "position EUPI holds. Mirror and real entries must never be netted."
        ),
    )
    payment_id: str | None = Field(
        default=None,
        description="Payment that produced this entry, where applicable.",
    )
    app_id: str | None = Field(
        default=None,
        description=(
            "Developer application that initiated the underlying payment. "
            "Null for Super App originated activity. Drives tenant isolation "
            "once the developer platform lands."
        ),
    )
    description: str = Field(
        default="",
        description="Human-readable narration for operators reading the ledger.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp of the posting.",
    )

    @field_validator("amount")
    @classmethod
    def _quantise(cls, value: Decimal) -> Decimal:
        """
        Normalise to two decimal places.

        Stored precision must be deterministic; otherwise 100 and 100.00
        compare unequal and a balanced transaction can fail its own check.
        """
        return value.quantize(Decimal("0.01"))

    @property
    def signed_amount(self) -> Decimal:
        """Amount with the direction's sign applied. Debits positive."""
        return self.amount * self.direction.sign


class LedgerTransaction(BaseModel):
    """
    A balanced set of entries posted atomically.

    Construction enforces the core invariant, so it is impossible to build an
    unbalanced transaction and therefore impossible to persist one — the
    repository accepts nothing else.
    """

    transaction_ref: str = Field(
        ...,
        description="Identifier shared by every entry in this transaction.",
    )
    transaction_type: TransactionType = Field(
        ...,
        description="Whether the underlying payment settles intra- or cross-bank.",
    )
    entries: list[LedgerEntry] = Field(
        ...,
        min_length=2,
        description="At least two entries — a single-sided posting is not double-entry.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp of the transaction.",
    )

    @model_validator(mode="after")
    def _must_balance(self) -> "LedgerTransaction":
        """
        Enforce that signed amounts sum to zero, per currency and per book.

        Mirror and real entries are checked separately: they are independent
        books that happen to be recorded together, and a mirror leg must never
        be allowed to offset a revenue leg.
        """
        for is_mirror in (True, False):
            book = [e for e in self.entries if e.is_mirror is is_mirror]
            if not book:
                continue

            by_currency: dict[str, Decimal] = {}
            for entry in book:
                by_currency[entry.currency] = (
                    by_currency.get(entry.currency, Decimal("0")) + entry.signed_amount
                )

            for currency, total in by_currency.items():
                if total != Decimal("0"):
                    book_name = "mirror" if is_mirror else "revenue"
                    raise ValueError(
                        f"Unbalanced {book_name} entries in transaction "
                        f"'{self.transaction_ref}' for {currency}: "
                        f"signed total is {total}, expected 0. "
                        f"Every debit needs a matching credit."
                    )

        # All entries must agree on which transaction they belong to.
        mismatched = {e.transaction_ref for e in self.entries} - {self.transaction_ref}
        if mismatched:
            raise ValueError(
                f"Entries reference foreign transaction_refs {sorted(mismatched)}; "
                f"expected all to be '{self.transaction_ref}'."
            )

        return self

    def total_for(self, account_ref: str) -> Decimal:
        """Net signed movement against one account within this transaction."""
        return sum(
            (e.signed_amount for e in self.entries if e.account_ref == account_ref),
            Decimal("0"),
        )
