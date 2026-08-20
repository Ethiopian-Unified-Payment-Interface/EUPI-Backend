"""
Port: BankPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.

Defines the contract that every bank adapter (Coop, CBE, Wegagen, Awash) MUST
satisfy. The use-case layer depends exclusively on this abstract class — never
on a concrete adapter. Dependency inversion is enforced here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.account import Account, BankID
from backend.domain.models.transaction import Transaction


class BankError(Exception):
    """
    Base class for every failure a bank rail can report.

    These live beside the port rather than inside an adapter because they are
    part of the contract: a use case must be able to tell "this account has no
    money" from "this bank is unreachable" without importing infrastructure and
    inverting the dependency the port exists to enforce.
    """


class AccountNotFoundError(BankError):
    """The account does not exist at this bank."""


class InactiveAccountError(BankError):
    """The account exists but is dormant, frozen, or closed."""


class InsufficientFundsError(BankError):
    """The debtor account cannot cover the debit."""


class DuplicateTransferError(BankError):
    """This `end_to_end_id` has already been submitted to this bank."""


class BankConnectionError(BankError):
    """The bank's core banking system is unreachable or timed out."""


class BankPort(ABC):
    """
    Abstract Driven Port: Banking Rail Interface.

    Any class that wishes to act as a bank adapter MUST inherit from this ABC
    and provide concrete implementations for all abstract methods. The
    infrastructure layer (adapters/banks/) satisfies this contract.

    Design note: all methods are synchronous at the domain contract level.
    Concrete adapters may use async internally; they should expose sync wrappers
    or the use-case layer may use asyncio.run() / anyio as appropriate.
    """

    # ------------------------------------------------------------------
    # Account Information Service (AIS)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_balance(self, account_number: str) -> Account:
        """
        Retrieve the current balance and account metadata for a given account.

        Args:
            account_number: The customer's account number at this bank.

        Returns:
            A fully populated :class:`~domain.models.account.Account` domain object.

        Raises:
            AccountNotFoundError: If the account does not exist at this bank.
            BankConnectionError: If the bank CBS is temporarily unavailable.
        """
        ...

    @abstractmethod
    def get_transactions(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Transaction]:
        """
        Retrieve transaction history for an account within a date range.

        The gateway guarantees at most 1 year of history per the AIS spec.
        Bank adapters MUST filter results to the requested window and normalise
        each entry to the :class:`~domain.models.transaction.Transaction` schema.

        Args:
            account_number: The customer's account number at this bank.
            from_date:       Start of the date range (UTC, inclusive).
            to_date:         End of the date range (UTC, inclusive).

        Returns:
            A list of :class:`~domain.models.transaction.Transaction` objects,
            ordered by booking_date descending (newest first).

        Raises:
            AccountNotFoundError: If the account does not exist.
            BankConnectionError: If the bank CBS is temporarily unavailable.
        """
        ...

    # ------------------------------------------------------------------
    # Payment Initiation Service (PIS)
    # ------------------------------------------------------------------

    @abstractmethod
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
        Initiate an inter-bank or intra-bank fund transfer.

        This method represents the ORDER step of the PIS 4-step lifecycle.
        The adapter submits the debit instruction to the bank's CBS and returns
        the bank's own order reference number.

        The debit is `amount + fee_amount`; the credit is `amount`. The bank
        collects the fee from its own customer and later settles EUPI's share
        of it, which is why the two figures are separate rather than one total.

        Args:
            debtor_account:   Source account number at this bank.
            creditor_account: Destination account number.
            creditor_bank_id: Destination bank rail identifier.
            amount:           Transfer amount reaching the beneficiary (positive).
            currency:         ISO 4217 currency code (typically "ETB").
            end_to_end_id:    Unique reference from the initiating TPP. Submitting
                              it twice must not move money twice.
            remittance_info:  Optional payment narration / invoice reference.
            fee_amount:       Fee the bank collects from the debtor on top of
                              `amount`. None or zero means no fee.

        Returns:
            A bank-issued order reference string for audit and reconciliation.

        Raises:
            InsufficientFundsError: If the debtor cannot cover amount plus fee.
            AccountNotFoundError:   If either account is unknown to its bank.
            InactiveAccountError:   If either account is not open for business.
            DuplicateTransferError: If end_to_end_id has already been processed.
            BankConnectionError:    If the bank CBS is temporarily unavailable.
        """
        ...

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def bank_id(self) -> BankID:
        """
        The BankID enum value that uniquely identifies this adapter instance.
        Used by the Smart Router to select the correct adapter at runtime.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """
        Perform a lightweight liveness ping against the bank's CBS endpoint.

        Returns:
            True if the CBS is reachable and responding within SLA.
            False if the CBS is down or responding outside acceptable latency.

        Note: This is called by the Smart Router to evaluate rail uptime scores.
        """
        ...
