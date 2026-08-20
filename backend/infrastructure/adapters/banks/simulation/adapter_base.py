"""
Simulated Bank Adapter Base
===========================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters

Shared `BankPort` implementation for every rail served by the simulated core
banking system.

Why a base class rather than six copies
---------------------------------------
Each adapter used to carry its own balance generator, statement generator, and
normaliser. That duplication was justified while each one imitated a different
proprietary API shape — translating `avlBal` and `AvailableBalance` and
`available_bal` onto one schema is the adapter layer earning its keep.

It stops being justified once all six read the same simulator: the differences
collapse to a bank identifier, a reference format, and an uptime figure. Six
copies of identical transfer logic would be six places for a debit to go wrong.

What stays per-bank
-------------------
The production endpoint constants, the order-reference format, and the uptime
each rail advertises to the Smart Router. Those are the things that will still
differ when a real CBS replaces this, and a concrete adapter that talks to a
real bank simply stops inheriting from here.
"""

from __future__ import annotations

import random
import uuid
from abc import abstractmethod
from datetime import datetime, timezone
from decimal import Decimal

from backend.application.ports.bank_port import BankPort
from backend.domain.models.account import Account, BankID
from backend.domain.models.transaction import Transaction
from backend.infrastructure.adapters.banks.simulation import mapping
from backend.infrastructure.adapters.banks.simulation.engine import (
    SimulatedCoreBankingEngine,
)


class SimulatedBankAdapter(BankPort):
    """
    A bank rail backed by the simulated core banking system.

    Subclasses supply identity and presentation; all movement and state lives
    in the shared engine, so every rail agrees on what happened.
    """

    #: Prefix of the order reference this bank issues, e.g. "COOP-ORD".
    _ORDER_PREFIX: str = "SIM-ORD"
    #: Prefix of the proprietary transaction code shown on statements.
    _TRANSACTION_CODE_PREFIX: str = "SIM"
    #: Rolling availability this rail advertises. Read by the Smart Router.
    _UPTIME: float = 0.99

    def __init__(self, engine: SimulatedCoreBankingEngine, api_key: str = "") -> None:
        """
        Args:
            engine:  The shared simulated core banking system. Required: an
                     adapter with no books cannot move money, and silently
                     falling back to invented balances is the failure this
                     whole change exists to remove.
            api_key: Credential the production adapter will present. Unused
                     while simulated, kept so configuration stays wired up.
        """
        self._engine = engine
        self._api_key = api_key

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def bank_id(self) -> BankID:
        """The rail this adapter serves."""
        ...

    def health_check(self) -> bool:
        """
        Liveness of this rail, as the Smart Router sees it.

        Still probabilistic: the router's circuit breaker and uptime scoring
        are real logic and need a rail that occasionally fails to be worth
        anything. Unlike balances, an availability figure is not a claim about
        anyone's money.
        """
        return random.random() < self._UPTIME

    # ── Account Information (AIS) ─────────────────────────────────────────────

    def get_balance(self, account_number: str) -> Account:
        """
        Current position of one account at this bank.

        Raises:
            AccountNotFoundError: The account does not exist at this bank.
        """
        return mapping.to_account(
            self._engine.get_account(self.bank_id, account_number)
        )

    def get_transactions(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Transaction]:
        """
        Statement for one account, newest first.

        These are the account's real movements, not generated history. A newly
        opened account therefore shows only its opening balance — which is
        accurate, and preferable to a statement that invents transactions the
        balance cannot account for.

        Raises:
            AccountNotFoundError: The account does not exist at this bank.
        """
        entries = self._engine.get_entries(
            bank_id=self.bank_id,
            account_number=account_number,
            from_date=from_date,
            to_date=to_date,
        )
        return [
            mapping.to_transaction(entry, self._TRANSACTION_CODE_PREFIX)
            for entry in entries
        ]

    # ── Payment Initiation (PIS) ──────────────────────────────────────────────

    def transfer(
        self,
        debtor_account: str,
        creditor_account: str,
        creditor_bank_id: BankID,
        amount: Decimal,
        currency: str,
        end_to_end_id: str,
        remittance_info: str | None = None,
        fee_amount: Decimal | None = None,
    ) -> str:
        """
        Submit the debit order. Money moves here, atomically, or not at all.

        Raises:
            InsufficientFundsError: The debtor cannot cover amount plus fee.
            AccountNotFoundError:   Either account is unknown to its bank.
            InactiveAccountError:   Either account is not open for business.
            DuplicateTransferError: The reference names a different transfer.
        """
        return self._engine.transfer(
            debtor_bank_id=self.bank_id,
            debtor_account=debtor_account,
            creditor_bank_id=creditor_bank_id,
            creditor_account=creditor_account,
            amount=amount,
            currency=currency,
            end_to_end_id=end_to_end_id,
            order_reference=self._order_reference(end_to_end_id),
            fee_amount=fee_amount,
            remittance_info=remittance_info,
        )

    def _order_reference(self, end_to_end_id: str) -> str:
        """
        Mint the bank's own reference for a new order, in its house format.

        The trailing token is drawn fresh rather than derived from the caller's
        reference. A bank allocates an order reference per order and it has to
        be unique on the bank's side; deriving it from `end_to_end_id` looked
        more traceable but collided the moment two different transfers shared a
        tail — which repeat transfers between the same pair of users reliably
        do. Traceability is not lost: the order row holds both references.

        Ignored on a replay. The engine returns the reference it issued the
        first time, so a retried transfer keeps one reference.
        """
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        return f"{self._ORDER_PREFIX}-{stamp}-{uuid.uuid4().hex[:10].upper()}"
