"""
Use Case: AIS Service — Account Information Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Responsibilities:
  - Aggregate account balances and metadata across all registered bank rails.
  - Retrieve and normalise up to 1 year of transaction history per account.
  - Enforce consent token validity before any data is returned.
  - Return fully typed domain objects; callers handle serialisation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

# Domain imports only
from backend.domain.models.account import Account, BankID
from backend.domain.models.identity import KYCLevel
from backend.domain.models.transaction import Transaction

# Application-layer port contracts only — never concrete adapters
from backend.application.ports.bank_port import BankPort
from backend.application.ports.identity_port import IdentityPort

logger = logging.getLogger(__name__)


class AISService:
    """
    Account Information Service (AIS) Use-Case Orchestrator.

    Injected dependencies (constructor injection / Dependency Inversion):
      - bank_ports:     A mapping of BankID → BankPort adapter. The service has
                        no knowledge of which concrete bank class is behind each port.
      - identity_port:  An IdentityPort adapter used to validate consent tokens.

    Clean Architecture invariant: this class NEVER instantiates a concrete adapter.
    It receives them from the outer layer (main.py wiring) via constructor injection.
    """

    # Minimum KYC level required to read account data.
    _REQUIRED_KYC_LEVEL: KYCLevel = KYCLevel.BASIC

    # Maximum allowed history window per the AIS spec.
    _MAX_HISTORY_DAYS: int = 365

    def __init__(
        self,
        bank_ports: dict[BankID, BankPort],
        identity_port: IdentityPort,
    ) -> None:
        """
        Args:
            bank_ports:    Dictionary mapping BankID → concrete BankPort adapter.
                           Populated by the DI wiring in main.py at startup.
            identity_port: Concrete IdentityPort adapter (e.g., FaydaAdapter).
        """
        self._bank_ports = bank_ports
        self._identity_port = identity_port

    # ------------------------------------------------------------------
    # Public Use-Case Methods
    # ------------------------------------------------------------------

    def get_all_balances(
        self,
        consent_token: str,
        customer_fin: str | None = None,
    ) -> list[Account]:
        """
        Fetch and aggregate account balances across ALL registered bank rails.

        This is the primary AIS endpoint handler. It fans out to every registered
        bank port, collects the account data, and returns a unified list.

        Args:
            consent_token:  A valid Fayda consent token. Must have at least BASIC
                            KYC level and include the `accounts:read` scope.
            customer_fin:   The customer's Fayda Identification Number, decoded
                            from the JWT by the caller. Used as the stable account
                            lookup key passed to bank adapters. Falls back to
                            consent_token if not provided (legacy behaviour).

        Returns:
            A list of :class:`~domain.models.account.Account` objects, one per
            successfully queried bank rail. Rails that error are skipped and logged.

        Raises:
            ConsentValidationError:  If the consent_token is invalid or expired.
            InsufficientKYCLevelError: If the token's KYC level is below BASIC.
            NoAccountsFoundError:    If no bank rail returns account data.
        """
        self._validate_consent(consent_token, required_scope="accounts:read")

        # Use the FIN as the stable lookup key so bank adapters always receive
        # the same identifier for a given customer (the JWT string changes on
        # every issuance and would produce different RNG-seeded mock data).
        lookup_key = customer_fin or consent_token
        accounts: list[Account] = []

        for bank_id, port in self._bank_ports.items():
            try:
                account = port.get_balance(account_number=lookup_key)
                accounts.append(account)
                logger.info(
                    "AIS balance fetched",
                    extra={"bank_id": bank_id.value, "account_id": account.account_id},
                )
            except Exception as exc:  # noqa: BLE001
                # Partial failure: log and skip the failing rail so the customer
                # still receives data from healthy banks.
                logger.warning(
                    "AIS balance fetch failed for bank %s: %s",
                    bank_id.value,
                    exc,
                )

        if not accounts:
            raise NoAccountsFoundError(
                "No bank rail returned account data for this consent token."
            )

        return accounts

    def get_balance_for_bank(
        self,
        consent_token: str,
        bank_id: BankID,
        account_number: str,
    ) -> Account:
        """
        Fetch the balance for a specific account at a specific bank rail.

        Args:
            consent_token:   Valid Fayda consent token.
            bank_id:         Target bank rail.
            account_number:  Customer account number at that bank.

        Returns:
            A single :class:`~domain.models.account.Account` domain object.

        Raises:
            ConsentValidationError:   If consent is invalid.
            BankNotRegisteredError:   If bank_id has no registered adapter.
            AccountNotFoundException: Propagated from the bank port.
        """
        self._validate_consent(consent_token, required_scope="accounts:read")
        port = self._get_port_or_raise(bank_id)
        account = port.get_balance(account_number=account_number)
        logger.info(
            "AIS single balance fetched",
            extra={"bank_id": bank_id.value, "account_id": account.account_id},
        )
        return account

    def get_transactions(
        self,
        consent_token: str,
        bank_id: BankID,
        account_number: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """
        Retrieve transaction history for an account, up to 1 year.

        The AIS spec mandates a maximum lookback of 365 days. If the caller
        requests a wider window it is silently clamped to the allowed maximum.

        Args:
            consent_token:  Valid Fayda consent token.
            bank_id:        Target bank rail.
            account_number: Customer account number at the target bank.
            from_date:      Start of history window (UTC). Defaults to 365 days ago.
            to_date:        End of history window (UTC). Defaults to now.

        Returns:
            A list of :class:`~domain.models.transaction.Transaction` objects,
            ordered by booking_date descending (newest first).

        Raises:
            ConsentValidationError:   If consent is invalid.
            BankNotRegisteredError:   If bank_id has no registered adapter.
            InvalidDateRangeError:    If from_date is after to_date.
        """
        self._validate_consent(consent_token, required_scope="transactions:read")
        port = self._get_port_or_raise(bank_id)

        now_utc = datetime.now(tz=timezone.utc)
        effective_to = to_date or now_utc
        effective_from = from_date or (now_utc - timedelta(days=self._MAX_HISTORY_DAYS))

        # Enforce the 1-year lookback cap regardless of what the caller requests.
        earliest_allowed = now_utc - timedelta(days=self._MAX_HISTORY_DAYS)
        if effective_from < earliest_allowed:
            logger.info(
                "AIS from_date clamped to 365-day max: %s → %s",
                effective_from.isoformat(),
                earliest_allowed.isoformat(),
            )
            effective_from = earliest_allowed

        if effective_from > effective_to:
            raise InvalidDateRangeError(
                f"from_date ({effective_from}) must not be after to_date ({effective_to})."
            )

        transactions = port.get_transactions(
            account_number=account_number,
            from_date=effective_from,
            to_date=effective_to,
        )

        logger.info(
            "AIS transactions fetched",
            extra={
                "bank_id": bank_id.value,
                "account_number": account_number[-4:],  # mask PII
                "count": len(transactions),
            },
        )
        return transactions

    def list_registered_banks(self) -> list[BankID]:
        """
        Return the list of bank rails currently registered with this service.

        Useful for the presentation layer to advertise which banks are available
        without exposing the concrete adapter instances.
        """
        return list(self._bank_ports.keys())

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _validate_consent(self, consent_token: str, required_scope: str) -> None:
        """
        Validate a consent token and assert it carries the required scope.

        Args:
            consent_token:  The token to validate.
            required_scope: OAuth-style scope string (e.g., "accounts:read").

        Raises:
            ConsentValidationError:    If the token is invalid or expired.
            InsufficientKYCLevelError: If the token's KYC level is below the
                                       service minimum (BASIC).
        """
        is_valid = self._identity_port.verify_consent_token(consent_token)
        if not is_valid:
            raise ConsentValidationError(
                "The provided consent token is invalid, expired, or has been revoked."
            )

        achieved_level = self._identity_port.get_kyc_level_for_token(consent_token)
        _assert_kyc_level(achieved_level, self._REQUIRED_KYC_LEVEL)

    def _get_port_or_raise(self, bank_id: BankID) -> BankPort:
        """Return the port for bank_id, or raise BankNotRegisteredError."""
        port = self._bank_ports.get(bank_id)
        if port is None:
            raise BankNotRegisteredError(
                f"Bank '{bank_id.value}' is not registered with this AIS service instance."
            )
        return port


# ------------------------------------------------------------------
# Domain-Level Exceptions (Application Layer)
# ------------------------------------------------------------------
# Defined here rather than a separate exceptions.py to keep the
# use-case module self-contained for Phase 1 scaffolding. They can
# be extracted when the exception hierarchy grows.

class AISServiceError(Exception):
    """Base exception for all AIS service errors."""


class ConsentValidationError(AISServiceError):
    """Raised when a Fayda consent token fails validation."""


class InsufficientKYCLevelError(AISServiceError):
    """Raised when the consent token's KYC level is below the required minimum."""


class BankNotRegisteredError(AISServiceError):
    """Raised when the requested BankID has no registered adapter."""


class NoAccountsFoundError(AISServiceError):
    """Raised when no bank rail returns any account data."""


class InvalidDateRangeError(AISServiceError):
    """Raised when from_date is after to_date."""


# ------------------------------------------------------------------
# KYC Level Utility (shared between AIS and PIS)
# ------------------------------------------------------------------

_KYC_LEVEL_ORDER: dict[KYCLevel, int] = {
    KYCLevel.BASIC: 1,
    KYCLevel.STANDARD: 2,
    KYCLevel.ENHANCED: 3,
}


def _assert_kyc_level(achieved: KYCLevel, required: KYCLevel) -> None:
    """
    Assert that the achieved KYC level satisfies the required minimum.

    Args:
        achieved: KYC level recorded in the consent token.
        required: Minimum level needed for the operation.

    Raises:
        InsufficientKYCLevelError: If achieved < required.
    """
    if _KYC_LEVEL_ORDER[achieved] < _KYC_LEVEL_ORDER[required]:
        raise InsufficientKYCLevelError(
            f"Operation requires KYC level '{required.value}', "
            f"but the consent token only certifies '{achieved.value}'."
        )
