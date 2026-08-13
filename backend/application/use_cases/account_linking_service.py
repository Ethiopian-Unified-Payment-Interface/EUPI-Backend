"""
Use Case: Account Linking Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Responsibilities:
  - Link a verified bank account to a super app user's profile.
  - Verify the account exists at the target bank before linking.
  - Manage default sending/receiving account designations.
  - List and remove linked accounts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

# Domain imports only
from backend.domain.models.account import BankID
from backend.domain.models.linked_account import AccountDirection, LinkedAccount

# Application-layer port contracts only — never concrete adapters
from backend.application.ports.account_link_repository_port import (
    AccountLinkRepositoryPort,
)
from backend.application.ports.bank_port import BankPort
from backend.application.ports.user_repository_port import UserRepositoryPort

logger = logging.getLogger(__name__)


class AccountLinkingService:
    """
    Account Linking Use-Case Orchestrator.

    Injected dependencies (constructor injection / Dependency Inversion):
      - link_repo:  An AccountLinkRepositoryPort for persisting linked accounts.
      - user_repo:  A UserRepositoryPort for verifying user existence.
      - bank_ports: A mapping of BankID → BankPort adapter for account verification.
    """

    def __init__(
        self,
        link_repo: AccountLinkRepositoryPort,
        user_repo: UserRepositoryPort,
        bank_ports: dict[BankID, BankPort],
    ) -> None:
        self._link_repo = link_repo
        self._user_repo = user_repo
        self._bank_ports = bank_ports

    def link_account(
        self,
        username: str,
        bank_id: BankID,
        account_number: str,
    ) -> LinkedAccount:
        """
        Link a bank account to a super app user.

        Verifies the account exists at the target bank by calling
        get_balance() on the bank port. If verification succeeds, the
        account is persisted as a linked account.

        If the user has no other linked accounts, the first linked
        account is automatically set as the default for both sending
        and receiving.

        Args:
            username:       The super app user's unique username.
            bank_id:        The bank where the account is held.
            account_number: The full account number to link.

        Returns:
            The newly created LinkedAccount domain object.

        Raises:
            UserNotFoundError: If username doesn't match any registered user.
            BankNotSupportedError: If bank_id has no registered adapter.
            AccountVerificationError: If the bank port cannot verify the account.
        """
        # Verify user exists
        from backend.domain.models.user import normalize_username
        full_username = normalize_username(username)
        user = self._user_repo.get_by_username(full_username)
        if user is None:
            raise UserNotFoundError(
                f"No super app user found with username '{username}'."
            )

        # Verify bank is supported
        port = self._bank_ports.get(bank_id)
        if port is None:
            raise BankNotSupportedError(
                f"Bank '{bank_id.value}' is not supported for account linking."
            )

        # Verify account exists at the bank
        try:
            account = port.get_balance(account_number=account_number)
        except Exception as exc:
            raise AccountVerificationError(
                f"Could not verify account '{account_number}' at {bank_id.value}: {exc}"
            )

        # Verify account ownership matches user's Fayda verified legal name
        user_name_norm = user.full_name.strip().upper()
        bank_name_norm = account.account_name.strip().upper()
        if user_name_norm != bank_name_norm:
            raise AccountOwnerMismatchError(
                f"Bank account '{account_number}' at {bank_id.value} is registered under "
                f"'{account.account_name}', which does not match your Fayda National ID identity '{user.full_name}'."
            )

        # Check if this is the user's first linked account
        existing_links = self._link_repo.list_for_user(full_username)
        is_first = len(existing_links) == 0

        link = LinkedAccount(
            link_id=str(uuid.uuid4()),
            username=full_username,
            bank_id=bank_id,
            account_number=account_number,
            account_name=account.account_name,
            is_default_sending=is_first,
            is_default_receiving=is_first,
            linked_at=datetime.now(tz=timezone.utc),
        )

        self._link_repo.add_link(link)

        logger.info(
            "Account linked",
            extra={
                "username": full_username,
                "bank_id": bank_id.value,
                "link_id": link.link_id,
                "is_first": is_first,
            },
        )

        return link

    def list_linked_accounts(self, username: str) -> list[LinkedAccount]:
        """
        Retrieve all linked accounts for a user.

        Args:
            username: The super app user's unique username.

        Returns:
            A list of LinkedAccount domain objects.
        """
        from backend.domain.models.user import normalize_username
        return self._link_repo.list_for_user(normalize_username(username))

    def sync_user_accounts(self, username: str) -> list[dict]:
        """
        Sync connected bank accounts and return live balance information.

        Args:
            username: The super app user's unique username.

        Returns:
            A list of dicts with live account balance details.
        """
        from backend.domain.models.user import normalize_username
        links = self._link_repo.list_for_user(normalize_username(username))
        synced = []
        for link in links:
            port = self._bank_ports.get(link.bank_id)
            if port is not None:
                try:
                    acct = port.get_balance(link.account_number)
                    available_balance = acct.available_balance
                    ledger_balance = acct.ledger_balance
                except Exception:
                    available_balance = Decimal("0.00")
                    ledger_balance = Decimal("0.00")
            else:
                available_balance = Decimal("0.00")
                ledger_balance = Decimal("0.00")

            synced.append({
                "link_id": link.link_id,
                "username": link.username,
                "bank_id": link.bank_id.value,
                "account_number": link.account_number,
                "account_name": link.account_name,
                "available_balance": available_balance,
                "ledger_balance": ledger_balance,
                "currency": "ETB",
                "is_default_sending": link.is_default_sending,
                "is_default_receiving": link.is_default_receiving,
                "linked_at": link.linked_at,
            })
        return synced

    def set_default_account(
        self,
        username: str,
        link_id: str,
        direction: AccountDirection,
    ) -> None:
        """
        Set a linked account as the default for a given direction.

        Args:
            username:  The unique username of the user making the request. Must own
                       the linked account being modified.
            link_id:   The unique ID of the linked account.
            direction: SENDING or RECEIVING.

        Raises:
            LinkNotFoundError: If the link_id doesn't exist.
            NotOwnerError:     If the link belongs to a different user.
        """
        from backend.domain.models.user import normalize_username
        full_username = normalize_username(username)
        link = self._link_repo.get_link(link_id)
        if link is None:
            raise LinkNotFoundError(
                f"Linked account '{link_id}' not found."
            )
        if link.username != full_username:
            raise NotOwnerError(
                f"Linked account '{link_id}' does not belong to user '{username}'."
            )
        self._link_repo.set_default(link_id, direction)

        logger.info(
            "Default account updated",
            extra={"link_id": link_id, "direction": direction.value},
        )

    def remove_linked_account(self, username: str, link_id: str) -> None:
        """
        Remove a linked account.

        Args:
            username: The unique username of the user making the request. Must own
                      the linked account being removed.
            link_id:  The unique ID of the linked account to remove.

        Raises:
            LinkNotFoundError: If the link_id doesn't exist.
            NotOwnerError:     If the link belongs to a different user.
        """
        from backend.domain.models.user import normalize_username
        full_username = normalize_username(username)
        link = self._link_repo.get_link(link_id)
        if link is None:
            raise LinkNotFoundError(
                f"Linked account '{link_id}' not found."
            )
        if link.username != full_username:
            raise NotOwnerError(
                f"Linked account '{link_id}' does not belong to user '{username}'."
            )

        self._link_repo.remove_link(link_id)
        logger.info("Account link removed", extra={"link_id": link_id, "username": full_username})


# Custom exceptions
class AccountLinkingError(Exception):
    """Base exception for account linking errors."""

class BankNotSupportedError(AccountLinkingError):
    """Raised when the target bank has no registered adapter."""

class AccountVerificationError(AccountLinkingError):
    """Raised when the bank port cannot verify the account."""

class AccountOwnerMismatchError(AccountLinkingError):
    """Raised when the bank account owner does not match the user's Fayda identity."""

class LinkNotFoundError(AccountLinkingError):
    """Raised when a linked account ID doesn't exist."""

class UserNotFoundError(AccountLinkingError):
    """Raised when the username doesn't match any registered user."""

class NotOwnerError(AccountLinkingError):
    """Raised when a user attempts to modify a linked account they don't own."""