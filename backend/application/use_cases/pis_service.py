"""
Use Case: PIS Service — Payment Initiation Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Implements the PIS 4-step lifecycle as a pure state machine:

  Step 1 — INITIATE:  Validate the request, create a Payment domain object,
                      call the Smart Router to assign a banking rail. → PENDING

  Step 2 — VERIFY:    Validate the Fayda consent token (OTP already confirmed
                      by the IdentityPort upstream). Assert STANDARD KYC level.
                      → VERIFIED

  Step 3 — ORDER:     Submit the debit instruction to the bank adapter selected
                      in Step 1. Capture the bank order reference. → ORDERED

  Step 4 — CALLBACK:  Mark the payment SUCCESS or FAILED based on the bank
                      callback. Return the final Payment to the presentation
                      layer which fires the webhook to the TPP.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only imports. Kept behind TYPE_CHECKING so the accounting stack
    # stays an optional collaborator at runtime and there is no import cycle
    # between use-case modules.
    from backend.application.use_cases.fee_service import FeeService
    from backend.application.use_cases.ledger_service import LedgerService

# Domain imports only
from backend.domain.models.account import BankID
from backend.domain.models.identity import KYCLevel
from backend.domain.models.payment import (
    Payment,
    PaymentInitiateRequest,
    PaymentRail,
    PaymentStatus,
)

# Application-layer port contracts only — never concrete adapters
from backend.application.ports.bank_port import BankPort
from backend.application.ports.identity_port import IdentityPort
from backend.application.ports.routing_port import RoutingPort

# Re-use KYC level guard and exceptions from the AIS service module
from backend.application.use_cases.ais_service import (
    ConsentValidationError,
    InsufficientKYCLevelError,
    _KYC_LEVEL_ORDER,
    _assert_kyc_level,
)

logger = logging.getLogger(__name__)


class PISService:
    """
    Payment Initiation Service (PIS) Use-Case Orchestrator.

    Injected dependencies (constructor injection / Dependency Inversion):
      - bank_ports:    A mapping of BankID → BankPort adapter.
      - identity_port: An IdentityPort adapter for consent validation.
      - routing_port:  A RoutingPort adapter for rail selection.

    This class owns the PIS state machine and is the single authority on
    what constitutes a valid state transition. It never reads from a database
    directly — in a full implementation a PaymentRepository port would be
    injected for persistence. For the MVP the payment object is returned
    to the presentation layer which persists it via the SQLite repo.
    """

    # PIS requires STANDARD KYC (OTP + biometric liveness).
    _REQUIRED_KYC_LEVEL: KYCLevel = KYCLevel.STANDARD

    def __init__(
        self,
        bank_ports: dict[BankID, BankPort],
        identity_port: IdentityPort,
        routing_port: RoutingPort,
        ledger_service: "LedgerService | None" = None,
        fee_service: "FeeService | None" = None,
    ) -> None:
        """
        Args:
            bank_ports:     Dictionary mapping BankID → concrete BankPort adapter.
            identity_port:  Concrete IdentityPort adapter (e.g., FaydaAdapter).
            routing_port:   Concrete RoutingPort adapter (e.g., SmartRouter).
            ledger_service: Posts double-entry records for settled payments.
                            Optional so existing unit tests can construct a
                            PISService without the accounting stack; when
                            absent, payments settle without being ledgered.
            fee_service:    Prices payments. Optional for the same reason.
        """
        self._bank_ports = bank_ports
        self._identity_port = identity_port
        self._routing_port = routing_port
        self._ledger_service = ledger_service
        self._fee_service = fee_service

    # ------------------------------------------------------------------
    # Step 1 — INITIATE
    # ------------------------------------------------------------------

    def initiate_payment(
        self,
        request: PaymentInitiateRequest,
        webhook_url: str | None = None,
    ) -> Payment:
        """
        Step 1: Validate the payment request and create a PENDING Payment.

        Business rules enforced:
          - Amount must be positive (enforced by the Pydantic model).
          - Debtor and creditor accounts must not be identical.
          - The Smart Router must be able to find at least one available rail.

        Args:
            request:     The payment initiation payload from the TPP.
            webhook_url: Optional TPP callback URL for async status updates.

        Returns:
            A :class:`~domain.models.payment.Payment` in PENDING status with
            a selected_rail already assigned by the Smart Router.

        Raises:
            SameAccountError:     If debtor and creditor accounts are identical.
            NoAvailableRouteError: Propagated from the routing port if no rail
                                   is available for this payment.
        """
        # Business rule: source and destination must differ.
        if (
            request.debtor_account_number == request.creditor_account_number
            and request.debtor_bank_id == request.creditor_bank_id
        ):
            raise SameAccountError(
                "Debtor and creditor accounts must be different for a payment."
            )

        # Ask the Smart Router to select the optimal rail.
        target_bank_id = BankID(request.creditor_bank_id)
        optimal_rail_bank_id = self._routing_port.get_optimal_route(
            amount=request.amount,
            target_bank_id=target_bank_id,
            currency=request.currency,
        )
        selected_rail = PaymentRail(optimal_rail_bank_id.value)

        payment = Payment(
            payment_id=f"PAY-{uuid.uuid4().hex[:16].upper()}",
            status=PaymentStatus.PENDING,
            initiate_request=request,
            selected_rail=selected_rail,
            webhook_url=webhook_url,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )

        logger.info(
            "PIS Step 1 — Payment initiated",
            extra={
                "payment_id": payment.payment_id,
                "selected_rail": selected_rail.value,
                "amount": str(request.amount),
                "currency": request.currency,
            },
        )

        # Log the full routing decision for observability.
        try:
            all_scores = self._routing_port.evaluate_all_routes(
                amount=request.amount,
                target_bank_id=target_bank_id,
                currency=request.currency,
            )
            logger.debug(
                "PIS routing scores: %s",
                [
                    {"bank": s.bank_id.value, "score": s.composite_score, "available": s.is_available}
                    for s in all_scores
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("PIS routing score audit failed (non-critical): %s", exc)

        return payment

    # ------------------------------------------------------------------
    # Step 2 — VERIFY
    # ------------------------------------------------------------------

    def verify_payment(
        self,
        payment: Payment,
        consent_token: str,
    ) -> Payment:
        """
        Step 2: Validate Fayda consent and transition the payment to VERIFIED.

        Business rules enforced:
          - Payment must be in PENDING status.
          - Consent token must be valid, unexpired, and not revoked.
          - Token must carry STANDARD KYC level or above.

        Args:
            payment:       The Payment domain object in PENDING status.
            consent_token: Fayda consent token obtained after OTP confirmation.

        Returns:
            A copy of the payment with status=VERIFIED and the consent_token
            stored on the object.

        Raises:
            InvalidPaymentStateError: If payment is not in PENDING status.
            ConsentValidationError:   If the consent token is invalid.
            InsufficientKYCLevelError: If KYC level < STANDARD.
        """
        self._assert_status(payment, PaymentStatus.PENDING, "VERIFY")

        # Validate the consent token via the identity port.
        is_valid = self._identity_port.verify_consent_token(consent_token)
        if not is_valid:
            raise ConsentValidationError(
                "PIS VERIFY failed: the consent token is invalid or has expired."
            )

        achieved_level = self._identity_port.get_kyc_level_for_token(consent_token)
        _assert_kyc_level(achieved_level, self._REQUIRED_KYC_LEVEL)

        # Pydantic models are immutable by default; build a new instance.
        verified_payment = payment.model_copy(
            update={
                "status": PaymentStatus.VERIFIED,
                "consent_token": consent_token,
                "updated_at": datetime.now(tz=timezone.utc),
            }
        )

        logger.info(
            "PIS Step 2 — Payment verified",
            extra={
                "payment_id": payment.payment_id,
                "kyc_level": achieved_level.value,
            },
        )
        return verified_payment

    # ------------------------------------------------------------------
    # Step 3 — ORDER
    # ------------------------------------------------------------------

    def order_payment(self, payment: Payment) -> Payment:
        """
        Step 3: Submit the debit instruction to the bank rail. → ORDERED or FAILED.

        Business rules enforced:
          - Payment must be in VERIFIED status.
          - The bank adapter for the selected_rail must be registered.
          - On adapter failure the payment transitions to FAILED (not raised).

        Args:
            payment: The Payment domain object in VERIFIED status.

        Returns:
            A copy of the payment with status=ORDERED (success) or FAILED,
            with bank_order_reference or failure_reason populated accordingly.

        Raises:
            InvalidPaymentStateError: If payment is not in VERIFIED status.
            BankNotRegisteredError:   If the selected_rail has no adapter.
        """
        self._assert_status(payment, PaymentStatus.VERIFIED, "ORDER")

        if payment.selected_rail is None:
            raise PISServiceError(
                f"Payment {payment.payment_id} has no selected_rail; cannot ORDER."
            )

        # Map PaymentRail → BankID to look up the adapter.
        try:
            bank_id = BankID(payment.selected_rail.value)
        except ValueError:
            raise BankNotRegisteredError(
                f"Selected rail '{payment.selected_rail.value}' has no matching BankID."
            )

        port = self._bank_ports.get(bank_id)
        if port is None:
            raise BankNotRegisteredError(
                f"Bank adapter for rail '{bank_id.value}' is not registered."
            )

        req = payment.initiate_request
        try:
            bank_reference = port.transfer(
                debtor_account=req.debtor_account_number,
                creditor_account=req.creditor_account_number,
                creditor_bank_id=BankID(req.creditor_bank_id),
                amount=req.amount,
                currency=req.currency,
                end_to_end_id=req.end_to_end_id,
                remittance_info=req.remittance_info,
            )

            ordered_payment = payment.model_copy(
                update={
                    "status": PaymentStatus.ORDERED,
                    "bank_order_reference": bank_reference,
                    "updated_at": datetime.now(tz=timezone.utc),
                }
            )

            logger.info(
                "PIS Step 3 — Payment ordered",
                extra={
                    "payment_id": payment.payment_id,
                    "bank_id": bank_id.value,
                    "bank_reference": bank_reference,
                },
            )
            return ordered_payment

        except Exception as exc:  # noqa: BLE001
            # Capture bank-side failures as a FAILED terminal state so the
            # presentation layer can return a structured error to the TPP.
            failed_payment = payment.model_copy(
                update={
                    "status": PaymentStatus.FAILED,
                    "failure_reason": str(exc),
                    "updated_at": datetime.now(tz=timezone.utc),
                }
            )
            logger.error(
                "PIS Step 3 — Payment ORDER failed",
                extra={
                    "payment_id": payment.payment_id,
                    "bank_id": bank_id.value,
                    "reason": str(exc),
                },
            )
            return failed_payment

    # ------------------------------------------------------------------
    # Step 4 — CALLBACK
    # ------------------------------------------------------------------

    def process_callback(
        self,
        payment: Payment,
        bank_confirmed: bool,
        failure_reason: str | None = None,
    ) -> Payment:
        """
        Step 4: Process the bank's async callback and move to a terminal state.

        This method is called by the presentation layer's webhook handler
        (POST /v1/callbacks) after the bank rail fires its own status callback.

        Business rules enforced:
          - Payment must be in ORDERED status.
          - If confirmed → SUCCESS. If not → FAILED with reason.

        Args:
            payment:        The Payment domain object in ORDERED status.
            bank_confirmed: True if the bank confirmed a successful credit.
            failure_reason: Human-readable reason if bank_confirmed is False.

        Returns:
            A copy of the payment in SUCCESS or FAILED terminal status.

        Raises:
            InvalidPaymentStateError: If payment is not in ORDERED status.
        """
        self._assert_status(payment, PaymentStatus.ORDERED, "CALLBACK")

        if bank_confirmed:
            final_payment = payment.model_copy(
                update={
                    "status": PaymentStatus.SUCCESS,
                    "updated_at": datetime.now(tz=timezone.utc),
                }
            )
            logger.info(
                "PIS Step 4 — Payment SUCCESS",
                extra={
                    "payment_id": payment.payment_id,
                    "bank_reference": payment.bank_order_reference,
                },
            )
            self._record_in_ledger(final_payment)
        else:
            final_payment = payment.model_copy(
                update={
                    "status": PaymentStatus.FAILED,
                    "failure_reason": failure_reason or "Bank callback indicated failure.",
                    "updated_at": datetime.now(tz=timezone.utc),
                }
            )
            logger.error(
                "PIS Step 4 — Payment FAILED via callback",
                extra={
                    "payment_id": payment.payment_id,
                    "reason": failure_reason,
                },
            )

        return final_payment

    # ------------------------------------------------------------------
    # Ledger integration
    # ------------------------------------------------------------------

    def _record_in_ledger(self, payment: Payment) -> None:
        """
        Price a settled payment and post its double-entry records.

        Called only on the SUCCESS path — a failed payment moved no money and
        must not appear in the ledger.

        Failures here are logged, not raised. The money has already moved at
        the bank by this point; refusing the callback would leave the payment
        stuck in ORDERED while the funds sit settled, which is a worse state
        than an unledgered success. Posting is idempotent by payment_id, so a
        replayed callback repairs the gap rather than double-posting.

        Args:
            payment: The payment in SUCCESS status.
        """
        if self._ledger_service is None:
            return

        request = payment.initiate_request

        try:
            fee_quote = None
            if self._fee_service is not None:
                from backend.domain.models.ledger import TransactionType

                transaction_type = TransactionType.classify(
                    request.debtor_bank_id, request.creditor_bank_id
                )
                # Price against the DEBTOR's bank, not the routed rail.
                #
                # Under revenue share the customer's own bank collects the fee
                # and owes EUPI a share of it, so the receivable belongs to
                # that bank. `selected_rail` is a routing artifact — which rail
                # carried the transfer — and using it books the receivable
                # against a bank that never charged anyone. That produced
                # COOP->COOP payments accruing revenue against CBE, which the
                # reconciliation report surfaced as volume and revenue landing
                # on different banks.
                #
                # It also makes pricing correct: a negotiated rate with COOP
                # should apply to COOP's customers regardless of routing.
                fee_quote = self._fee_service.quote(
                    bank_id=request.debtor_bank_id,
                    transaction_type=transaction_type,
                    amount=request.amount,
                    currency=request.currency,
                )

            self._ledger_service.record_settled_payment(
                payment_id=payment.payment_id,
                debtor_bank_id=request.debtor_bank_id,
                debtor_account_number=request.debtor_account_number,
                creditor_bank_id=request.creditor_bank_id,
                creditor_account_number=request.creditor_account_number,
                amount=request.amount,
                currency=request.currency,
                fee_quote=fee_quote,
            )
        except Exception:  # noqa: BLE001 — see docstring
            logger.exception(
                "Failed to record settled payment in the ledger. The payment "
                "itself succeeded; replay the callback to post the entries.",
                extra={"payment_id": payment.payment_id},
            )

    # ------------------------------------------------------------------
    # Cancellation (out-of-band, pre-ORDER)
    # ------------------------------------------------------------------

    def cancel_payment(self, payment: Payment, reason: str = "Customer requested cancellation.") -> Payment:
        """
        Cancel a payment that has not yet reached the ORDERED step.

        Only PENDING or VERIFIED payments can be cancelled. Once ORDERED,
        the bank rail is authoritative and cancellation is not supported
        by the MVP (would require a reversal flow).

        Args:
            payment: The Payment to cancel.
            reason:  Human-readable cancellation reason.

        Returns:
            A copy of the payment in CANCELLED terminal status.

        Raises:
            InvalidPaymentStateError: If the payment is already in a terminal
                                      or ORDERED state.
        """
        cancellable = {PaymentStatus.PENDING, PaymentStatus.VERIFIED}
        if payment.status not in cancellable:
            raise InvalidPaymentStateError(
                f"Payment {payment.payment_id} cannot be cancelled from status "
                f"'{payment.status.value}'. Only PENDING or VERIFIED payments may be cancelled."
            )

        cancelled_payment = payment.model_copy(
            update={
                "status": PaymentStatus.CANCELLED,
                "failure_reason": reason,
                "updated_at": datetime.now(tz=timezone.utc),
            }
        )
        logger.info(
            "PIS — Payment CANCELLED",
            extra={"payment_id": payment.payment_id, "reason": reason},
        )
        return cancelled_payment

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_status(
        payment: Payment,
        expected: PaymentStatus,
        step_name: str,
    ) -> None:
        """
        Guard that a payment is in the expected state before a transition.

        Args:
            payment:   The Payment to check.
            expected:  The required current status.
            step_name: The step name used in the error message (e.g., "VERIFY").

        Raises:
            InvalidPaymentStateError: If payment.status != expected.
        """
        if payment.status != expected:
            raise InvalidPaymentStateError(
                f"PIS {step_name} step requires payment status '{expected.value}', "
                f"but payment {payment.payment_id} is in '{payment.status.value}'."
            )


# ------------------------------------------------------------------
# Domain-Level Exceptions (Application Layer — PIS)
# ------------------------------------------------------------------

class PISServiceError(Exception):
    """Base exception for all PIS service errors."""


class InvalidPaymentStateError(PISServiceError):
    """Raised when a state transition is attempted from an invalid current status."""


class SameAccountError(PISServiceError):
    """Raised when debtor and creditor are the same account."""


class BankNotRegisteredError(PISServiceError):
    """Raised when the selected rail has no registered bank adapter."""


class NoAvailableRouteError(PISServiceError):
    """Raised when the routing port cannot find any available bank rail."""
