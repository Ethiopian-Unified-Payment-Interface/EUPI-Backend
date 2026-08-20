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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.application.ports.identity_port import IdentityPort
    from backend.application.use_cases.user_registration_service import (
        UserRegistrationService,
    )

# Domain imports only
from backend.domain.models.linked_account import LinkedAccount
from backend.domain.models.payment import Payment, PaymentInitiateRequest, PaymentStatus

# Application-layer port contracts only — never concrete adapters
from backend.application.ports.account_link_repository_port import (
    AccountLinkRepositoryPort,
)
from backend.application.ports.payment_repository_port import PaymentRepositoryPort
from backend.application.ports.user_repository_port import UserRepositoryPort

# Compose with existing use-case orchestrators (same layer — allowed)
from backend.application.use_cases.payment_settlement_service import (
    PaymentSettlementService,
)
from backend.application.use_cases.pis_service import PISService

logger = logging.getLogger(__name__)


class SuperAppTransferService:
    """
    Super App P2P Transfer Use-Case Orchestrator.

    Composes the existing PISService with user and account link
    resolution to provide a username-based "send money" flow.

    Injected dependencies:
      - user_repo:            Username resolution.
      - link_repo:            Default account lookup.
      - pis_service:          Payment execution through the PIS lifecycle.
      - payment_repo:         Persistence required before settlement can load
                              the payment it is about to finalise.
      - settlement_service:   Drives ORDERED → SUCCESS after the bank posts.
    """

    # Consent minted for a transfer authorises exactly that transfer. Two
    # minutes is enough to complete initiate → verify → order in one request
    # and far too short to be reused later if it somehow escaped the process.
    _CONSENT_TTL_SECONDS = 120

    def __init__(
        self,
        user_repo: UserRepositoryPort,
        link_repo: AccountLinkRepositoryPort,
        pis_service: PISService,
        identity_port: "IdentityPort | None" = None,
        registration_service: "UserRegistrationService | None" = None,
        payment_repo: PaymentRepositoryPort | None = None,
        settlement_service: PaymentSettlementService | None = None,
    ) -> None:
        """
        Args:
            user_repo:            Username resolution.
            link_repo:            Default account lookup.
            pis_service:          Payment execution.
            identity_port:        Mints the consent token derived from a PIN
                                  authorisation. Required by `send_money`.
            registration_service: Verifies the transaction PIN, reusing the
                                  same argon2 hash and lockout counters as
                                  login. Required by `send_money`.
            payment_repo:         Persistence for the ordered payment.
                                  Required by `send_money`.
            settlement_service:   Completes the payment after the bank posts.
                                  Required by `send_money`.
        """
        self._user_repo = user_repo
        self._link_repo = link_repo
        self._pis_service = pis_service
        self._identity_port = identity_port
        self._registration_service = registration_service
        self._payment_repo = payment_repo
        self._settlement_service = settlement_service

    def send_money(
        self,
        sender_username: str,
        recipient_username: str,
        amount: Decimal,
        pin: str,
        currency: str = "ETB",
        remittance_info: str | None = None,
        client_reference: str | None = None,
    ) -> Payment:
        """
        Authorise and execute a P2P transfer in one call.

        The Super App transaction PIN is the payer's consent. Verifying it mints
        a short-lived consent token, which then drives the ordinary PIS flow —
        initiate → verify → order — and, because the bank adapter already
        posted the debit and credit, settlement. The caller observes a
        completed payment, not an ORDERED one the Super App would render as
        pending forever.

        Why this exists: PIS VERIFY requires a `gateway_access` token, and a
        Super App session token is deliberately not interchangeable with one.
        Without this path the app could create a payment and never complete it.
        Stopping at ORDERED was the next gap: money had moved at the bank but
        EUPI never recorded SUCCESS, so neither history nor the ledger showed
        a credit and a debit.

        Args:
            sender_username:    The payer, from their session.
            recipient_username: The payee's handle.
            amount:             Transfer amount.
            pin:                The payer's 6-digit PIN, re-entered to authorise
                                this transfer.
            currency:           Currency code.
            remittance_info:    Optional narration.
            client_reference:   Optional caller-supplied idempotency key. When
                                given, the payment reference is derived from it,
                                so a double-submitted transfer is rejected by
                                the unique constraint instead of sending twice.

        Returns:
            The Payment in SUCCESS status once both accounts have moved, or
            FAILED if the bank rejected the order.

        Raises:
            InvalidPINError / PINLockedError: PIN wrong, or too many attempts.
            RecipientNotFoundError, NoDefaultAccountError, SelfTransferError,
            InsufficientBalanceError: As for `initiate_transfer`.
        """
        if self._identity_port is None or self._registration_service is None:
            raise TransferError(
                "PIN-authorised transfers are unavailable: the transfer service "
                "was constructed without an identity port or registration service."
            )
        if self._payment_repo is None or self._settlement_service is None:
            raise TransferError(
                "PIN-authorised transfers are unavailable: the transfer service "
                "was constructed without a payment repository or settlement service."
            )

        # 1. Authorise. Raises before anything is created if the PIN is wrong,
        #    and is throttled by the same lockout as login.
        payer = self._registration_service.authorise_with_pin(sender_username, pin)

        # 2. Build the payment. Resolution of both defaults happens here.
        payment = self.initiate_transfer(
            sender_username=sender_username,
            recipient_username=recipient_username,
            amount=amount,
            currency=currency,
            remittance_info=remittance_info,
            client_reference=client_reference,
        )

        # 3. Mint consent from the PIN authorisation, tagged so an auditor can
        #    tell this apart from an OTP-authorised payment.
        from backend.domain.models.identity import KYCLevel

        consent_token = self._identity_port.issue_delegated_consent_token(
            fin=payer.fin,
            scopes=["payments:write"],
            kyc_level=KYCLevel.STANDARD,
            consent_method="superapp_pin",
            ttl_seconds=self._CONSENT_TTL_SECONDS,
        )

        # 4. Run the rest of the PIS lifecycle, then record the bank's result.
        verified = self._pis_service.verify_payment(payment, consent_token)
        ordered = self._pis_service.order_payment(verified)
        final = self._record_bank_result(ordered)

        logger.info(
            "P2P transfer authorised by PIN and completed",
            extra={
                "payment_id": final.payment_id,
                "consent_method": "superapp_pin",
                "status": final.status.value,
            },
        )
        return final

    def finalise_existing(self, payment: Payment) -> Payment:
        """
        Complete an already-created transfer that never reached SUCCESS.

        Used when a retried `client_reference` finds the original payment.
        ORDERED means the bank posted and EUPI did not record it; confirming
        now repairs the gap. Any other status is returned unchanged — a
        SUCCESS replay is a no-op, a FAILED one must not be revived.
        """
        if payment.status is not PaymentStatus.ORDERED:
            return payment
        if self._settlement_service is None:
            return payment
        return self._settlement_service.settle(
            payment_id=payment.payment_id,
            bank_confirmed=True,
            bank_order_reference=payment.bank_order_reference,
        )

    def initiate_transfer(
        self,
        sender_username: str,
        recipient_username: str,
        amount: Decimal,
        currency: str = "ETB",
        remittance_info: str | None = None,
        client_reference: str | None = None,
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

        # Build the PIS request
        request = PaymentInitiateRequest(
            debtor_account_number=sender_account.account_number,
            debtor_bank_id=sender_account.bank_id.value,
            creditor_account_number=recipient_account.account_number,
            creditor_bank_id=recipient_account.bank_id.value,
            creditor_name=recipient.full_name,
            amount=amount,
            currency=currency,
            # Without a client reference a UUID suffix keeps each attempt
            # unique, since the DB enforces end_to_end_id uniqueness and two
            # deliberate repeat transfers must not collide.
            #
            # With one, the reference is derived from it instead, so a
            # double-submitted transfer — a retried request, a double-tapped
            # button — is rejected by that same unique constraint rather than
            # sending the money twice. That matters more now that a single call
            # completes the whole transfer.
            end_to_end_id=(
                f"P2P-REF-{client_reference}"
                if client_reference
                else f"P2P-{uuid.uuid4().hex[:12].upper()}-{sender_username}-{recipient.username}"
            ),
            remittance_info=remittance_info,
        )

        payment = self._pis_service.initiate_payment(request=request)

        # Advisory affordability check. The bank is the authority and re-checks
        # atomically when the order is placed; this only exists so the app can
        # say "not enough money" before we ask the payer for their PIN, and it
        # must therefore price the whole debit — principal plus the fee the
        # bank collects — not the principal alone.
        fee = payment.fee.customer_fee if payment.fee else Decimal("0.00")
        self._assert_can_afford(sender_account, amount + fee)

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

    def _assert_can_afford(self, account: LinkedAccount, total_debit: Decimal) -> None:
        """
        Raise InsufficientBalanceError if the account clearly cannot cover
        `total_debit` (principal + fee).

        Advisory only. A balance read is a snapshot, so this can be beaten by a
        concurrent debit; the bank re-checks under a row lock when the order is
        placed and is the one that decides. Any failure to *read* the balance is
        therefore logged and swallowed rather than blocking the transfer — the
        exception is a missing or closed account, which is a definite "this will
        never work" and is worth surfacing here.
        """
        from backend.application.ports.bank_port import (
            AccountNotFoundError,
            InactiveAccountError,
        )

        port = self._pis_service._bank_ports.get(account.bank_id)
        if port is None:
            return

        try:
            snapshot = port.get_balance(account.account_number)
        except (AccountNotFoundError, InactiveAccountError) as exc:
            raise TransferError(
                f"Your default sending account at {account.bank_id.value} is not "
                f"usable: {exc}"
            ) from exc
        except Exception as exc:
            logger.warning(
                "Could not verify balance prior to transfer; deferring to the bank",
                extra={"bank_id": account.bank_id.value, "error": str(exc)},
            )
            return

        if snapshot.available_balance < total_debit:
            raise InsufficientBalanceError(
                f"Insufficient funds in default sending account "
                f"'{account.account_number}' at {account.bank_id.value}. "
                f"Available: {snapshot.available_balance} ETB, "
                f"required: {total_debit} ETB (including fees)."
            )

    def _record_bank_result(self, payment: Payment) -> Payment:
        """
        Persist the bank's decision and, when it accepted, complete settlement.

        `order_payment` already moved money on the simulated books — debit
        the sender, credit the recipient, collect the fee. Leaving the
        payment ORDERED waits for an external callback the Super App never
        fires; the settlement worker eventually would, but until then the
        history shows pending and the EUPI ledger has no entry. Confirming
        here is not a shortcut around the bank: the bank already posted.
        The worker remains for TPP payments that stop at ORDER, and a
        repeated confirmation is a no-op because settlement is idempotent.
        """
        assert self._payment_repo is not None
        assert self._settlement_service is not None

        self._payment_repo.update_payment(payment)

        if payment.status is not PaymentStatus.ORDERED:
            return payment

        return self._settlement_service.settle(
            payment_id=payment.payment_id,
            bank_confirmed=True,
            bank_order_reference=payment.bank_order_reference,
        )

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