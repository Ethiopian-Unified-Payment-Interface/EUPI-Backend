"""
Use Case: Super App Transfer Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Responsibilities:
  - Resolve transfer recipient by username (P2P lookup).
  - Determine default sending and receiving accounts for both parties.
  - Delegate the actual payment execution to the existing PISService.
  - Provide a single high-level `send_money(sender_username, recipient_username, amount)`
    that wraps the full PIS 4-step lifecycle.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

# Domain imports only
from backend.domain.models.linked_account import LinkedAccount
from backend.domain.models.payment import Payment, PaymentInitiateRequest

# Application-layer port contracts only — never concrete adapters
from backend.application.ports.account_link_repository_port import (
    AccountLinkRepositoryPort,
)
from backend.application.ports.user_repository_port import UserRepositoryPort

# Compose with existing use-case orchestrator (same layer — allowed)
from backend.application.use_cases.pis_service import PISService

logger = logging.getLogger(__name__)


class SuperAppTransferService:
    """
    Super App P2P Transfer Use-Case Orchestrator.

    Composes the existing PISService with user and account link
    resolution to provide a username-based "send money" flow.

    Injected dependencies:
      - user_repo: UserRepositoryPort for username resolution.
      - link_repo: AccountLinkRepositoryPort for default account lookup.
      - pis_service: PISService for payment execution.
    """

    def __init__(
        self,
        user_repo: UserRepositoryPort,
        link_repo: AccountLinkRepositoryPort,
        pis_service: PISService,
    ) -> None:
        self._user_repo = user_repo
        self._link_repo = link_repo
        self._pis_service = pis_service

    def initiate_transfer(
        self,
        sender_username: str,
        recipient_username: str,
        amount: Decimal,
        currency: str = "ETB",
        remittance_info: str | None = None,
    ) -> Payment:
        """
        Initiate a P2P transfer from sender to recipient.

        Resolves the recipient by username, finds default linked accounts
        for both parties, and delegates to PISService.initiate_payment().

        Args:
            sender_username:    The sender's username (from JWT/session).
            recipient_username: The recipient's username handle.
            amount:             Transfer amount (must be > 0).
            currency:           Currency code (default "ETB").
            remittance_info:    Optional description / reference.

        Returns:
            A Payment domain object in PENDING status.

        Raises:
            RecipientNotFoundError:      If recipient_username doesn't exist.
            NoDefaultAccountError:       If sender or recipient has no default account.
            SelfTransferError:           If sender tries to send to themselves.
        """
        from backend.domain.models.user import normalize_username
        norm_sender = normalize_username(sender_username)
        norm_recipient = normalize_username(recipient_username)

        # Resolve recipient
        recipient = self._user_repo.get_by_username(norm_recipient)
        if recipient is None:
            raise RecipientNotFoundError(
                f"No user found with username '{recipient_username}'."
            )

        # Prevent self-transfer
        if recipient.username == norm_sender:
            raise SelfTransferError("Cannot send money to yourself.")

        # Find sender's default sending account
        sender_account = self._find_default_sending(norm_sender)
        if sender_account is None:
            raise NoDefaultAccountError(
                "You have no default sending account. Please link a bank account first."
            )

        # Find recipient's default receiving account
        recipient_account = self._find_default_receiving(recipient.username)
        if recipient_account is None:
            raise NoDefaultAccountError(
                f"Recipient '{recipient_username}' has no default receiving account."
            )

        # Check sender's available balance at their default sending bank
        port = self._pis_service._bank_ports.get(sender_account.bank_id)
        if port is not None:
            try:
                acct = port.get_balance(sender_account.account_number)
                if acct.available_balance < amount:
                    raise InsufficientBalanceError(
                        f"Insufficient funds in default sending account '{sender_account.account_number}' "
                        f"at {sender_account.bank_id.value}. Available: {acct.available_balance} ETB, Requested: {amount} ETB."
                    )
            except InsufficientBalanceError:
                raise
            except Exception as exc:
                logger.warning(f"Could not verify balance prior to transfer: {exc}")

        # Build the PIS request
        request = PaymentInitiateRequest(
            debtor_account_number=sender_account.account_number,
            debtor_bank_id=sender_account.bank_id.value,
            creditor_account_number=recipient_account.account_number,
            creditor_bank_id=recipient_account.bank_id.value,
            creditor_name=recipient.full_name,
            amount=amount,
            currency=currency,
            # A UUID suffix keeps this unique per attempt — the DB enforces
            # end_to_end_id uniqueness, so two identical repeat transfers
            # (same sender, recipient, amount) must not collide.
            end_to_end_id=f"P2P-{uuid.uuid4().hex[:12].upper()}-{sender_username}-{recipient.username}",
            remittance_info=remittance_info,
        )

        payment = self._pis_service.initiate_payment(request=request)

        logger.info(
            "P2P transfer initiated",
            extra={
                "sender_username": sender_username,
                "recipient_username": recipient_username,
                "amount": str(amount),
                "payment_id": payment.payment_id,
            },
        )

        return payment

    # Private helpers

    def _find_default_sending(self, username: str) -> LinkedAccount | None:
        """Find the user's default sending account, or None."""
        from backend.domain.models.user import normalize_username
        links = self._link_repo.list_for_user(normalize_username(username))
        for link in links:
            if link.is_default_sending:
                return link
        return None

    def _find_default_receiving(self, username: str) -> LinkedAccount | None:
        """Find the user's default receiving account, or None."""
        from backend.domain.models.user import normalize_username
        links = self._link_repo.list_for_user(normalize_username(username))
        for link in links:
            if link.is_default_receiving:
                return link
        return None


# Custom exceptions
class TransferError(Exception):
    """Base exception for super app transfer errors."""

class RecipientNotFoundError(TransferError):
    """Raised when the recipient username doesn't exist."""

class NoDefaultAccountError(TransferError):
    """Raised when sender or recipient has no default linked account."""

class SelfTransferError(TransferError):
    """Raised when a user attempts to transfer to themselves."""

class InsufficientBalanceError(TransferError):
    """Raised when the sender has insufficient funds in their default sending account."""