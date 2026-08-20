"""
Simulated Core Banking Engine
=============================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters

The stateful core behind every bank adapter. One instance is shared by all six
rails: they are separate banks, but they are separate banks inside one
simulator, which is what lets a cross-bank transfer move money in a single
atomic step.

What this replaced
------------------
`transfer()` used to format an order reference and return it. `get_balance()`
used to invent a figure from a per-process RNG. Nothing was stored, so a P2P
payment never debited or credited anything and a balance could not change no
matter how much money "moved". This engine makes the movement real, within the
sandbox.

Nothing here is money
---------------------
EUPI is a pass-through orchestrator and holds no customer funds. These balances
belong to the *simulated banks*. They are fixtures, never liabilities, and
anything that shows one to a human has to say so.

Correctness properties
----------------------
**Atomic.** Debit, credit, fee, journal, and the order record all commit in one
transaction. There is no window in which one side moved and the other did not.

**Serialised per account.** Both account rows are locked before either balance
is read, in a fixed key order so two opposing transfers cannot deadlock. The
balance check happens inside that lock, which is what actually prevents a
double spend — the advisory check the transfer service performs beforehand is
racy by construction and cannot.

**Idempotent.** `end_to_end_id` is the primary key of the order table, so a
replayed transfer collides at INSERT inside the same transaction that would
have moved the money. Replaying returns the original order reference; reusing
the reference for a *different* transfer is a caller bug and is rejected.

**Value-conserving.** Fees post to a per-bank income account rather than
vanishing, so the sum of every simulated balance never changes. A test asserts
exactly that, and it is the cheapest detector for a half-applied transfer.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.application.ports.bank_port import (
    AccountNotFoundError,
    DuplicateTransferError,
    InactiveAccountError,
    InsufficientFundsError,
)
from backend.domain.models.account import AccountType, BankID
from backend.infrastructure.adapters.banks.simulation import catalogue
from backend.infrastructure.database.models import (
    SimulatedBankAccountRecord,
    SimulatedBankEntryRecord,
    SimulatedTransferOrderRecord,
)
from backend.infrastructure.database.session import Database, RepositoryBase

logger = logging.getLogger(__name__)

_ZERO = Decimal("0.00")
_CENTS = Decimal("0.01")

# The bank's own fee income account. Prefixed so it can never collide with a
# customer account number, and excluded from every customer-facing lookup: a
# caller must not be able to read or pay into a bank's internal book.
FEE_INCOME_ACCOUNT = "__FEE_INCOME__"
_INTERNAL_ACCOUNTS = frozenset({FEE_INCOME_ACCOUNT})

# Order lifecycle inside the simulated bank.
ORDER_POSTED = "POSTED"
ORDER_SETTLED = "SETTLED"
ORDER_REVERSED = "REVERSED"

# Journal entry classification.
ENTRY_OPENING = "OPENING"
ENTRY_TRANSFER = "TRANSFER"
ENTRY_FEE = "FEE"
ENTRY_REVERSAL = "REVERSAL"

# Bank-statement direction: funds left, funds arrived. This is the opposite
# sign convention to EUPI's own `ledger_entries`, deliberately — one is a
# statement, the other is double-entry bookkeeping.
DEBIT = "DEBIT"
CREDIT = "CREDIT"


@dataclass(frozen=True)
class AccountSnapshot:
    """An account's position at one moment, free of ORM identity."""

    bank_id: BankID
    account_number: str
    account_name: str
    account_type: AccountType
    branch_code: str
    currency: str
    available_balance: Decimal
    ledger_balance: Decimal
    is_active: bool
    updated_at: datetime


@dataclass(frozen=True)
class EntrySnapshot:
    """One movement on a statement."""

    entry_id: str
    bank_id: BankID
    account_number: str
    direction: str
    amount: Decimal
    currency: str
    balance_after: Decimal
    entry_type: str
    counterparty_bank_id: str | None
    counterparty_account: str | None
    counterparty_name: str | None
    end_to_end_id: str | None
    order_reference: str | None
    narration: str
    booked_at: datetime


@dataclass(frozen=True)
class DueOrder:
    """A posted transfer whose settlement confirmation is now due."""

    end_to_end_id: str
    order_reference: str
    debtor_bank_id: str
    debtor_account_number: str
    creditor_bank_id: str
    creditor_account_number: str
    amount: Decimal
    fee_amount: Decimal
    currency: str
    attempts: int


class SimulatedCoreBankingEngine(RepositoryBase):
    """
    The simulated banks' shared core banking system.

    Constructed once per process in the composition root and injected into
    every bank adapter, so all six rails read and write the same books.
    """

    def __init__(self, db: Database, settlement_delay_seconds: float = 3.0) -> None:
        """
        Args:
            db:                       Shared engine and session factory.
            settlement_delay_seconds: How long the bank takes to confirm a
                                      posted transfer. Settlement is
                                      asynchronous at a real bank; keeping a
                                      delay here means a payment in flight
                                      looks the same in the sandbox as it will
                                      in production.
        """
        super().__init__(db)
        self._settlement_delay = timedelta(seconds=max(settlement_delay_seconds, 0.0))

    # ══════════════════════════════════════════════════════════════════════════
    # Provisioning
    # ══════════════════════════════════════════════════════════════════════════

    def provision(self) -> int:
        """
        Open every catalogue account that does not exist yet.

        Safe to run on every boot: accounts already open are left untouched, so
        this never resets a balance someone is mid-demo with. Each new account
        gets an opening-balance journal entry, which keeps the invariant that
        an account's balance equals the sum of its own journal.

        Returns:
            The number of accounts opened by this call.
        """
        opened = 0
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        with self._session() as session:
            existing = {
                (record.bank_id, record.account_number)
                for record in session.execute(
                    select(
                        SimulatedBankAccountRecord.bank_id,
                        SimulatedBankAccountRecord.account_number,
                    )
                ).all()
            }

            for seed in catalogue.all_seeds():
                key = (seed.bank_id.value, seed.account_number)
                if key in existing:
                    continue

                session.add(
                    SimulatedBankAccountRecord(
                        bank_id=seed.bank_id.value,
                        account_number=seed.account_number,
                        account_name=seed.account_name,
                        account_type=seed.account_type.value,
                        currency=seed.currency,
                        branch_code=seed.branch_code,
                        available_balance=seed.opening_balance,
                        ledger_balance=seed.opening_balance,
                        is_active=True,
                        opened_at=now,
                        updated_at=now,
                    )
                )
                session.add(
                    self._entry(
                        bank_id=seed.bank_id.value,
                        account_number=seed.account_number,
                        direction=CREDIT,
                        amount=seed.opening_balance,
                        currency=seed.currency,
                        balance_after=seed.opening_balance,
                        entry_type=ENTRY_OPENING,
                        narration="Opening balance",
                        booked_at=now,
                    )
                )
                opened += 1

            # Each bank's own fee income book. Without it a collected fee would
            # simply disappear from the simulator and the total of all balances
            # would drift down by the fee on every transfer.
            for bank_id in catalogue.BANK_PROFILES:
                if (bank_id.value, FEE_INCOME_ACCOUNT) in existing:
                    continue
                session.add(
                    SimulatedBankAccountRecord(
                        bank_id=bank_id.value,
                        account_number=FEE_INCOME_ACCOUNT,
                        account_name=f"{bank_id.value} FEE INCOME",
                        account_type=AccountType.CURRENT.value,
                        currency="ETB",
                        branch_code="INTERNAL",
                        available_balance=_ZERO,
                        ledger_balance=_ZERO,
                        is_active=True,
                        opened_at=now,
                        updated_at=now,
                    )
                )

        if opened:
            logger.info("Simulated core banking: opened %d account(s).", opened)
        return opened

    # ══════════════════════════════════════════════════════════════════════════
    # Account information
    # ══════════════════════════════════════════════════════════════════════════

    def get_account(self, bank_id: BankID, account_number: str) -> AccountSnapshot:
        """
        Read one account's current position.

        Args:
            bank_id:        Bank holding the account.
            account_number: Account number to read.

        Returns:
            The account's current position.

        Raises:
            AccountNotFoundError: The account does not exist at this bank.
        """
        number = self._customer_account(bank_id, account_number)
        with self._session() as session:
            record = session.get(
                SimulatedBankAccountRecord, (bank_id.value, number)
            )
            if record is None and len(number) == 14 and number.isdigit():
                from backend.infrastructure.mock_data.fayda_registry import get_identity
                identity = get_identity(number)
                if identity:
                    name_upper = identity["full_name"].strip().upper()
                    record = (
                        session.query(SimulatedBankAccountRecord)
                        .filter(
                            SimulatedBankAccountRecord.bank_id == bank_id.value,
                            func.upper(SimulatedBankAccountRecord.account_name) == name_upper,
                        )
                        .first()
                    )
            if record is None:
                raise AccountNotFoundError(
                    f"Account '{number}' does not exist at {bank_id.value}."
                )
            return self._to_snapshot(record)

    def get_entries(
        self,
        bank_id: BankID,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
        limit: int = 200,
    ) -> list[EntrySnapshot]:
        """
        Statement entries for one account within a window, newest first.

        Args:
            bank_id:        Bank holding the account.
            account_number: Account to report on.
            from_date:      Inclusive lower bound.
            to_date:        Inclusive upper bound.
            limit:          Maximum entries returned.

        Returns:
            The account's real movements. A freshly provisioned account has
            exactly one: its opening balance. Statements show what happened
            rather than plausible-looking invented history, which is the point
            of having books at all.

        Raises:
            AccountNotFoundError: The account does not exist at this bank.
        """
        number = self._customer_account(bank_id, account_number)
        start = _naive_utc(from_date)
        end = _naive_utc(to_date)

        with self._session() as session:
            if session.get(SimulatedBankAccountRecord, (bank_id.value, number)) is None:
                raise AccountNotFoundError(
                    f"Account '{number}' does not exist at {bank_id.value}."
                )

            records = (
                session.execute(
                    select(SimulatedBankEntryRecord)
                    .where(
                        SimulatedBankEntryRecord.bank_id == bank_id.value,
                        SimulatedBankEntryRecord.account_number == number,
                        SimulatedBankEntryRecord.booked_at >= start,
                        SimulatedBankEntryRecord.booked_at <= end,
                    )
                    .order_by(SimulatedBankEntryRecord.booked_at.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [self._to_entry_snapshot(r) for r in records]

    # ══════════════════════════════════════════════════════════════════════════
    # Movement
    # ══════════════════════════════════════════════════════════════════════════

    def transfer(
        self,
        debtor_bank_id: BankID,
        debtor_account: str,
        creditor_bank_id: BankID,
        creditor_account: str,
        amount: Decimal,
        currency: str,
        end_to_end_id: str,
        order_reference: str,
        fee_amount: Decimal | None = None,
        remittance_info: str | None = None,
    ) -> str:
        """
        Move money, atomically, and record the order for later settlement.

        The debtor is debited `amount + fee_amount`; the creditor is credited
        `amount`; the fee lands in the debtor bank's fee income book. All of it
        commits together or none of it does.

        Args:
            debtor_bank_id:   Bank holding the source account.
            debtor_account:   Source account number.
            creditor_bank_id: Bank holding the destination account.
            creditor_account: Destination account number.
            amount:           Amount reaching the beneficiary. Positive.
            currency:         ISO 4217 code; must match both accounts.
            end_to_end_id:    Idempotency key. Replaying it returns the
                              original order reference without moving money.
            order_reference:  The bank's reference for a *new* order. Ignored
                              on a replay, which returns the original.
            fee_amount:       Fee the bank collects from the debtor.
            remittance_info:  Narration recorded on both legs.

        Returns:
            The order reference for this transfer.

        Raises:
            AccountNotFoundError:   Either account is unknown to its bank.
            InactiveAccountError:   Either account is not open for business.
            InsufficientFundsError: The debtor cannot cover amount plus fee.
            DuplicateTransferError: `end_to_end_id` was already used for a
                                    materially different transfer.
        """
        principal = _money(amount)
        fee = _money(fee_amount or _ZERO)
        if principal <= _ZERO:
            raise ValueError("Transfer amount must be positive.")
        if fee < _ZERO:
            raise ValueError("Fee cannot be negative.")

        debtor_number = self._customer_account(debtor_bank_id, debtor_account)
        creditor_number = self._customer_account(creditor_bank_id, creditor_account)
        code = currency.strip().upper()
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        with self._session() as session:
            replayed = self._replayed_reference(
                session,
                end_to_end_id=end_to_end_id,
                debtor_bank_id=debtor_bank_id.value,
                debtor_account=debtor_number,
                creditor_bank_id=creditor_bank_id.value,
                creditor_account=creditor_number,
                amount=principal,
                fee=fee,
            )
            if replayed is not None:
                return replayed

            debtor, creditor = self._lock_pair(
                session,
                (debtor_bank_id.value, debtor_number),
                (creditor_bank_id.value, creditor_number),
            )
            fee_book = (
                self._lock_one(session, debtor_bank_id.value, FEE_INCOME_ACCOUNT)
                if fee > _ZERO
                else None
            )

            self._assert_usable(debtor, debtor_bank_id, code)
            self._assert_usable(creditor, creditor_bank_id, code)

            total_debit = principal + fee
            if debtor.available_balance < total_debit:
                raise InsufficientFundsError(
                    f"Account '{debtor_number}' at {debtor_bank_id.value} holds "
                    f"{debtor.available_balance} {code} but the transfer requires "
                    f"{total_debit} {code} ({principal} plus {fee} fee)."
                )

            narration = remittance_info or f"Transfer {end_to_end_id}"

            self._apply(debtor, -principal, now)
            session.add(
                self._entry(
                    bank_id=debtor.bank_id,
                    account_number=debtor.account_number,
                    direction=DEBIT,
                    amount=principal,
                    currency=code,
                    balance_after=debtor.available_balance,
                    entry_type=ENTRY_TRANSFER,
                    counterparty_bank_id=creditor.bank_id,
                    counterparty_account=creditor.account_number,
                    counterparty_name=creditor.account_name,
                    end_to_end_id=end_to_end_id,
                    order_reference=order_reference,
                    narration=narration,
                    booked_at=now,
                )
            )

            if fee > _ZERO and fee_book is not None:
                self._apply(debtor, -fee, now)
                session.add(
                    self._entry(
                        bank_id=debtor.bank_id,
                        account_number=debtor.account_number,
                        direction=DEBIT,
                        amount=fee,
                        currency=code,
                        balance_after=debtor.available_balance,
                        entry_type=ENTRY_FEE,
                        end_to_end_id=end_to_end_id,
                        order_reference=order_reference,
                        narration=f"Transfer fee for {end_to_end_id}",
                        booked_at=now,
                    )
                )
                self._apply(fee_book, fee, now)
                session.add(
                    self._entry(
                        bank_id=fee_book.bank_id,
                        account_number=FEE_INCOME_ACCOUNT,
                        direction=CREDIT,
                        amount=fee,
                        currency=code,
                        balance_after=fee_book.available_balance,
                        entry_type=ENTRY_FEE,
                        end_to_end_id=end_to_end_id,
                        order_reference=order_reference,
                        narration=f"Fee collected on {end_to_end_id}",
                        booked_at=now,
                    )
                )

            self._apply(creditor, principal, now)
            session.add(
                self._entry(
                    bank_id=creditor.bank_id,
                    account_number=creditor.account_number,
                    direction=CREDIT,
                    amount=principal,
                    currency=code,
                    balance_after=creditor.available_balance,
                    entry_type=ENTRY_TRANSFER,
                    counterparty_bank_id=debtor.bank_id,
                    counterparty_account=debtor.account_number,
                    counterparty_name=debtor.account_name,
                    end_to_end_id=end_to_end_id,
                    order_reference=order_reference,
                    narration=narration,
                    booked_at=now,
                )
            )

            session.add(
                SimulatedTransferOrderRecord(
                    end_to_end_id=end_to_end_id,
                    order_reference=order_reference,
                    debtor_bank_id=debtor.bank_id,
                    debtor_account_number=debtor.account_number,
                    creditor_bank_id=creditor.bank_id,
                    creditor_account_number=creditor.account_number,
                    amount=principal,
                    fee_amount=fee,
                    currency=code,
                    status=ORDER_POSTED,
                    settle_after=now + self._settlement_delay,
                    attempts=0,
                    created_at=now,
                )
            )

            try:
                session.flush()
            except IntegrityError as exc:
                # Two concurrent submissions of the same reference. The loser's
                # whole transaction rolls back, so no money moved on this path;
                # the winner's is already committed or about to be.
                raise DuplicateTransferError(
                    f"Transfer '{end_to_end_id}' is already being processed."
                ) from exc

        logger.info(
            "Simulated CBS posted transfer",
            extra={
                "end_to_end_id": end_to_end_id,
                "order_reference": order_reference,
                "debtor_bank": debtor_bank_id.value,
                "creditor_bank": creditor_bank_id.value,
                "amount": str(principal),
                "fee": str(fee),
            },
        )
        return order_reference

    # ══════════════════════════════════════════════════════════════════════════
    # Settlement — driven by the callback worker
    # ══════════════════════════════════════════════════════════════════════════

    def claim_due_orders(self, limit: int = 25) -> list[DueOrder]:
        """
        Take ownership of posted orders whose settlement delay has elapsed.

        Rows are claimed with `SKIP LOCKED` where the database supports it, so
        several application workers can run this loop without two of them
        confirming the same transfer.

        Args:
            limit: Maximum orders to claim in one pass.

        Returns:
            The claimed orders, with their attempt counter already incremented.
        """
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        with self._session() as session:
            statement = (
                select(SimulatedTransferOrderRecord)
                .where(
                    SimulatedTransferOrderRecord.status == ORDER_POSTED,
                    SimulatedTransferOrderRecord.settle_after <= now,
                )
                .order_by(SimulatedTransferOrderRecord.settle_after.asc())
                .limit(limit)
            )
            if self._supports_row_locks:
                statement = statement.with_for_update(skip_locked=True)

            records = session.execute(statement).scalars().all()
            claimed = []
            for record in records:
                record.attempts += 1
                claimed.append(
                    DueOrder(
                        end_to_end_id=record.end_to_end_id,
                        order_reference=record.order_reference,
                        debtor_bank_id=record.debtor_bank_id,
                        debtor_account_number=record.debtor_account_number,
                        creditor_bank_id=record.creditor_bank_id,
                        creditor_account_number=record.creditor_account_number,
                        amount=_money(record.amount),
                        fee_amount=_money(record.fee_amount),
                        currency=record.currency,
                        attempts=record.attempts,
                    )
                )
            return claimed

    def mark_settled(self, end_to_end_id: str) -> None:
        """Record that the bank confirmed the transfer. Terminal."""
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        with self._session() as session:
            record = session.get(SimulatedTransferOrderRecord, end_to_end_id)
            if record is None or record.status != ORDER_POSTED:
                return
            record.status = ORDER_SETTLED
            record.settled_at = now

    def reverse(self, end_to_end_id: str, reason: str) -> bool:
        """
        Back out a posted transfer the bank subsequently rejected.

        Posts opposing entries rather than editing the originals: the account
        history has to show that money moved and came back, because that is
        what happened and it is what the customer's statement would show.

        Args:
            end_to_end_id: The transfer to reverse.
            reason:        Why, recorded on the order and in each narration.

        Returns:
            True if the transfer was reversed, False if it was not in a
            reversible state — already settled, already reversed, or unknown.
        """
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        with self._session() as session:
            order = session.get(SimulatedTransferOrderRecord, end_to_end_id)
            if order is None or order.status != ORDER_POSTED:
                return False

            principal = _money(order.amount)
            fee = _money(order.fee_amount)
            total = principal + fee

            debtor, creditor = self._lock_pair(
                session,
                (order.debtor_bank_id, order.debtor_account_number),
                (order.creditor_bank_id, order.creditor_account_number),
            )

            self._apply(creditor, -principal, now)
            session.add(
                self._entry(
                    bank_id=creditor.bank_id,
                    account_number=creditor.account_number,
                    direction=DEBIT,
                    amount=principal,
                    currency=order.currency,
                    balance_after=creditor.available_balance,
                    entry_type=ENTRY_REVERSAL,
                    counterparty_bank_id=debtor.bank_id,
                    counterparty_account=debtor.account_number,
                    end_to_end_id=end_to_end_id,
                    order_reference=order.order_reference,
                    narration=f"Reversal of {end_to_end_id}: {reason}",
                    booked_at=now,
                )
            )

            if fee > _ZERO:
                fee_book = self._lock_one(
                    session, order.debtor_bank_id, FEE_INCOME_ACCOUNT
                )
                self._apply(fee_book, -fee, now)
                session.add(
                    self._entry(
                        bank_id=fee_book.bank_id,
                        account_number=FEE_INCOME_ACCOUNT,
                        direction=DEBIT,
                        amount=fee,
                        currency=order.currency,
                        balance_after=fee_book.available_balance,
                        entry_type=ENTRY_REVERSAL,
                        end_to_end_id=end_to_end_id,
                        order_reference=order.order_reference,
                        narration=f"Fee refunded on {end_to_end_id}",
                        booked_at=now,
                    )
                )

            self._apply(debtor, total, now)
            session.add(
                self._entry(
                    bank_id=debtor.bank_id,
                    account_number=debtor.account_number,
                    direction=CREDIT,
                    amount=total,
                    currency=order.currency,
                    balance_after=debtor.available_balance,
                    entry_type=ENTRY_REVERSAL,
                    counterparty_bank_id=creditor.bank_id,
                    counterparty_account=creditor.account_number,
                    end_to_end_id=end_to_end_id,
                    order_reference=order.order_reference,
                    narration=f"Reversal of {end_to_end_id}: {reason}",
                    booked_at=now,
                )
            )

            order.status = ORDER_REVERSED
            order.failure_reason = reason
            order.settled_at = now

        logger.warning(
            "Simulated CBS reversed transfer",
            extra={"end_to_end_id": end_to_end_id, "reason": reason},
        )
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # Diagnostics
    # ══════════════════════════════════════════════════════════════════════════

    def total_balance(self) -> Decimal:
        """
        The sum of every simulated balance, including bank fee income.

        Constant across any number of transfers, because a transfer only moves
        value between accounts the simulator owns. A change means a leg
        committed without its counterpart.
        """
        with self._session() as session:
            balances = (
                session.execute(select(SimulatedBankAccountRecord.available_balance))
                .scalars()
                .all()
            )
            return sum((_money(b) for b in balances), _ZERO)

    # ══════════════════════════════════════════════════════════════════════════
    # Internals
    # ══════════════════════════════════════════════════════════════════════════

    @property
    def _supports_row_locks(self) -> bool:
        """
        Whether the dialect implements `SELECT ... FOR UPDATE`.

        SQLite does not, and emitting the clause would be a syntax error. Its
        exclusivity comes from elsewhere: `Database` starts every SQLite
        transaction as IMMEDIATE, so the write lock is already held before the
        first balance is read. Without that the read-modify-write below would
        be open to a lost update, which is why the two must stay in step.
        """
        return self._db.dialect != "sqlite"

    def _lock_pair(
        self,
        session: Session,
        first: tuple[str, str],
        second: tuple[str, str],
    ) -> tuple[SimulatedBankAccountRecord, SimulatedBankAccountRecord]:
        """
        Lock two accounts in a fixed order and return them in the order asked.

        Sorting the keys before locking is what stops two opposing transfers —
        A to B and B to A, at the same moment — from each holding one row and
        waiting for the other. Without it the deadlock is rare, real, and
        appears only under the concurrency that a payment system exists to
        handle.
        """
        keys = sorted({first, second})
        locked = {key: self._lock_one(session, *key) for key in keys}
        return locked[first], locked[second]

    def _lock_one(
        self, session: Session, bank_id: str, account_number: str
    ) -> SimulatedBankAccountRecord:
        """Fetch one account row for update, or raise if the bank has no such account."""
        statement = select(SimulatedBankAccountRecord).where(
            SimulatedBankAccountRecord.bank_id == bank_id,
            SimulatedBankAccountRecord.account_number == account_number,
        )
        if self._supports_row_locks:
            statement = statement.with_for_update()

        record = session.execute(statement).scalar_one_or_none()
        if record is None:
            raise AccountNotFoundError(
                f"Account '{account_number}' does not exist at {bank_id}."
            )
        return record

    @staticmethod
    def _assert_usable(
        record: SimulatedBankAccountRecord, bank_id: BankID, currency: str
    ) -> None:
        """Reject an account that cannot take part in a transfer."""
        if not record.is_active:
            raise InactiveAccountError(
                f"Account '{record.account_number}' at {bank_id.value} is not active."
            )
        if record.currency != currency:
            raise InactiveAccountError(
                f"Account '{record.account_number}' at {bank_id.value} is held in "
                f"{record.currency}, not {currency}."
            )

    @staticmethod
    def _apply(
        record: SimulatedBankAccountRecord, delta: Decimal, now: datetime
    ) -> None:
        """
        Move an account's balance by a signed amount.

        Available and ledger balances move together: the simulator books
        immediately and has no concept of a hold.
        """
        record.available_balance = _money(_money(record.available_balance) + delta)
        record.ledger_balance = _money(_money(record.ledger_balance) + delta)
        record.updated_at = now

    def _replayed_reference(
        self,
        session: Session,
        *,
        end_to_end_id: str,
        debtor_bank_id: str,
        debtor_account: str,
        creditor_bank_id: str,
        creditor_account: str,
        amount: Decimal,
        fee: Decimal,
    ) -> str | None:
        """
        Resolve a resubmitted `end_to_end_id`.

        Returns the original order reference when the resubmission is identical,
        which makes a retry a no-op rather than a second payment. Raises when
        the same reference names a *different* transfer: silently returning the
        first one would confirm a payment that never happened, and moving the
        money would break the idempotency the caller was relying on.
        """
        existing = session.get(SimulatedTransferOrderRecord, end_to_end_id)
        if existing is None:
            return None

        identical = (
            existing.debtor_bank_id == debtor_bank_id
            and existing.debtor_account_number == debtor_account
            and existing.creditor_bank_id == creditor_bank_id
            and existing.creditor_account_number == creditor_account
            and _money(existing.amount) == amount
            and _money(existing.fee_amount) == fee
        )
        if not identical:
            raise DuplicateTransferError(
                f"Reference '{end_to_end_id}' was already used for a different "
                f"transfer. An idempotency key cannot be reused."
            )

        logger.info(
            "Simulated CBS replayed transfer; no money moved",
            extra={
                "end_to_end_id": end_to_end_id,
                "order_reference": existing.order_reference,
            },
        )
        return existing.order_reference

    @staticmethod
    def _customer_account(bank_id: BankID, account_number: str) -> str:
        """
        Normalise a caller-supplied account number and refuse internal books.

        A bank's fee income account is not addressable from outside; treating
        it as unknown is the same answer a real CBS would give.
        """
        number = account_number.strip()
        if number in _INTERNAL_ACCOUNTS:
            raise AccountNotFoundError(
                f"Account '{number}' does not exist at {bank_id.value}."
            )
        return number

    @staticmethod
    def _entry(
        *,
        bank_id: str,
        account_number: str,
        direction: str,
        amount: Decimal,
        currency: str,
        balance_after: Decimal,
        entry_type: str,
        narration: str,
        booked_at: datetime,
        counterparty_bank_id: str | None = None,
        counterparty_account: str | None = None,
        counterparty_name: str | None = None,
        end_to_end_id: str | None = None,
        order_reference: str | None = None,
    ) -> SimulatedBankEntryRecord:
        """Build one journal row."""
        return SimulatedBankEntryRecord(
            entry_id=f"sim_{uuid.uuid4().hex[:20]}",
            bank_id=bank_id,
            account_number=account_number,
            direction=direction,
            amount=_money(amount),
            currency=currency,
            balance_after=_money(balance_after),
            entry_type=entry_type,
            counterparty_bank_id=counterparty_bank_id,
            counterparty_account=counterparty_account,
            counterparty_name=counterparty_name,
            end_to_end_id=end_to_end_id,
            order_reference=order_reference,
            narration=narration,
            booked_at=booked_at,
        )

    @staticmethod
    def _to_snapshot(record: SimulatedBankAccountRecord) -> AccountSnapshot:
        """Detach an account row into a plain value."""
        return AccountSnapshot(
            bank_id=BankID(record.bank_id),
            account_number=record.account_number,
            account_name=record.account_name,
            account_type=AccountType(record.account_type),
            branch_code=record.branch_code,
            currency=record.currency,
            available_balance=_money(record.available_balance),
            ledger_balance=_money(record.ledger_balance),
            is_active=record.is_active,
            updated_at=record.updated_at.replace(tzinfo=timezone.utc),
        )

    @staticmethod
    def _to_entry_snapshot(record: SimulatedBankEntryRecord) -> EntrySnapshot:
        """Detach a journal row into a plain value."""
        return EntrySnapshot(
            entry_id=record.entry_id,
            bank_id=BankID(record.bank_id),
            account_number=record.account_number,
            direction=record.direction,
            amount=_money(record.amount),
            currency=record.currency,
            balance_after=_money(record.balance_after),
            entry_type=record.entry_type,
            counterparty_bank_id=record.counterparty_bank_id,
            counterparty_account=record.counterparty_account,
            counterparty_name=record.counterparty_name,
            end_to_end_id=record.end_to_end_id,
            order_reference=record.order_reference,
            narration=record.narration,
            booked_at=record.booked_at.replace(tzinfo=timezone.utc),
        )


def _money(value: Decimal | float | int | str) -> Decimal:
    """Normalise to two decimal places so stored and computed values compare equal."""
    return Decimal(str(value)).quantize(_CENTS)


def _naive_utc(value: datetime) -> datetime:
    """Drop the timezone for comparison against naive-UTC columns."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def iter_bank_ids() -> Iterable[BankID]:
    """Every bank the simulator provisions accounts for."""
    return catalogue.BANK_PROFILES.keys()
