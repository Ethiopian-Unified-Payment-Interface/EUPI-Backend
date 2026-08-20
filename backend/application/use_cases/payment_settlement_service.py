"""
Use Case: Payment Settlement Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Drives an ORDERED payment to its terminal state when the bank confirms.

Why this exists as a use case
-----------------------------
This logic used to live inside the `POST /v1/callbacks` route handler: load the
payment, run the state transition, persist, queue the third-party webhook. That
is business logic in a controller, and it had a second cost — it was reachable
only over HTTP, so the simulated banks had no way to confirm settlement and
every payment stopped at ORDERED forever. Two callers need it now, the HTTP
callback and the bank's own settlement worker, and they must not be two
implementations that can drift apart.

Idempotency
-----------
Confirming a payment twice is normal, not exceptional: a bank that does not
receive an acknowledgement retries, and the settlement worker retries anything
it did not finish. A repeated confirmation returns the already-settled payment
untouched. A *contradictory* one — a failure for a payment already settled —
is rejected, because silently accepting it would rewrite a terminal outcome.
"""

from __future__ import annotations

import logging

from backend.application.ports.payment_repository_port import PaymentRepositoryPort
from backend.application.use_cases.pis_service import PISService
from backend.domain.models.payment import Payment, PaymentStatus

logger = logging.getLogger(__name__)


class SettlementError(Exception):
    """Base exception for settlement failures."""


class PaymentNotFoundError(SettlementError):
    """No payment matches the supplied identifier or reference."""


class ConflictingSettlementError(SettlementError):
    """A confirmation contradicts an outcome the payment already reached."""


class PaymentSettlementService:
    """
    Terminal-state transitions for payments, driven by bank confirmation.

    Injected dependencies (constructor injection / Dependency Inversion):
      - payment_repo: Persistence for the payment and its outbound webhook.
      - pis_service:  Owner of the payment state machine and ledger posting.
    """

    def __init__(
        self,
        payment_repo: PaymentRepositoryPort,
        pis_service: PISService,
    ) -> None:
        self._payment_repo = payment_repo
        self._pis_service = pis_service

    def settle(
        self,
        payment_id: str,
        bank_confirmed: bool,
        bank_order_reference: str | None = None,
        failure_reason: str | None = None,
    ) -> Payment:
        """
        Apply a bank's settlement decision to a payment.

        Args:
            payment_id:           The gateway payment to finalise.
            bank_confirmed:       True if the beneficiary was credited.
            bank_order_reference: The bank's reference, for reconciliation.
                                  Logged on mismatch rather than rejected: a
                                  bank that reports a different reference for a
                                  payment it is otherwise confirming is an
                                  operations question, and refusing the
                                  callback would strand settled funds.
            failure_reason:       Why, when `bank_confirmed` is False.

        Returns:
            The payment in SUCCESS or FAILED status.

        Raises:
            PaymentNotFoundError:        No such payment.
            ConflictingSettlementError:  The payment already reached the
                                         opposite terminal state.
            InvalidPaymentStateError:    The payment was never ordered.
        """
        payment = self._payment_repo.get_payment(payment_id)
        if payment is None:
            raise PaymentNotFoundError(f"Payment '{payment_id}' not found.")

        already = self._already_settled(payment, bank_confirmed)
        if already is not None:
            return already

        if (
            bank_order_reference
            and payment.bank_order_reference
            and bank_order_reference != payment.bank_order_reference
        ):
            logger.warning(
                "Settlement reported a different bank order reference than the "
                "one recorded at ORDER. Proceeding; flag for reconciliation.",
                extra={
                    "payment_id": payment_id,
                    "recorded": payment.bank_order_reference,
                    "reported": bank_order_reference,
                },
            )

        final = self._pis_service.process_callback(
            payment=payment,
            bank_confirmed=bank_confirmed,
            failure_reason=failure_reason,
        )

        self._payment_repo.update_payment(final)
        self._queue_webhook(final)

        logger.info(
            "Payment settled",
            extra={"payment_id": payment_id, "status": final.status.value},
        )
        return final

    def settle_by_reference(
        self,
        end_to_end_id: str,
        bank_confirmed: bool,
        bank_order_reference: str | None = None,
        failure_reason: str | None = None,
    ) -> Payment:
        """
        As `settle`, but addressed by the reference the bank knows.

        Args:
            end_to_end_id: The caller-supplied reference carried to the bank.

        Returns:
            The payment in SUCCESS or FAILED status.

        Raises:
            PaymentNotFoundError: No payment carries this reference.
        """
        payment = self._payment_repo.get_payment_by_end_to_end_id(end_to_end_id)
        if payment is None:
            raise PaymentNotFoundError(
                f"No payment carries reference '{end_to_end_id}'."
            )
        return self.settle(
            payment_id=payment.payment_id,
            bank_confirmed=bank_confirmed,
            bank_order_reference=bank_order_reference,
            failure_reason=failure_reason,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _already_settled(payment: Payment, bank_confirmed: bool) -> Payment | None:
        """
        Resolve a repeated confirmation.

        Returns the payment unchanged when this confirmation agrees with the
        outcome already recorded, which makes a retried callback a no-op.

        Raises:
            ConflictingSettlementError: When it disagrees. A terminal state is
                a statement about money that has moved; overwriting it because
                a later message said otherwise would make the ledger a record
                of the most recent opinion rather than of what happened.
        """
        if payment.status is PaymentStatus.SUCCESS:
            if bank_confirmed:
                return payment
            raise ConflictingSettlementError(
                f"Payment {payment.payment_id} already settled successfully; "
                f"a failure callback cannot reverse it. Post a reversal instead."
            )

        if payment.status is PaymentStatus.FAILED:
            if not bank_confirmed:
                return payment
            raise ConflictingSettlementError(
                f"Payment {payment.payment_id} already failed; a success "
                f"callback cannot revive it."
            )

        return None

    def _queue_webhook(self, payment: Payment) -> None:
        """
        Queue the third-party status notification, if one was requested.

        Failures are logged rather than raised. The payment is already settled
        by this point and the money has moved; refusing the settlement because
        a notification could not be queued would trade a missing webhook for a
        payment stuck in ORDERED, which is strictly worse.
        """
        if not payment.webhook_url:
            return

        request = payment.initiate_request
        try:
            self._payment_repo.create_webhook_event(
                payment_id=payment.payment_id,
                webhook_url=payment.webhook_url,
                payload={
                    "event_type": "payment.settled",
                    "payment_id": payment.payment_id,
                    "status": payment.status.value,
                    "amount": str(request.amount),
                    "currency": request.currency,
                    "end_to_end_id": request.end_to_end_id,
                    "bank_order_reference": payment.bank_order_reference,
                    "failure_reason": payment.failure_reason,
                    "updated_at": payment.updated_at.isoformat(),
                },
            )
        except Exception:  # noqa: BLE001 — see docstring
            logger.exception(
                "Could not queue settlement webhook; the payment itself settled.",
                extra={"payment_id": payment.payment_id},
            )
