"""
Port: PaymentRepositoryPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO SQL.

The slice of payment persistence the settlement use case needs.

Deliberately narrow. `PaymentRepository` also owns consent tokens, webhook
delivery bookkeeping, and history queries, none of which settlement has any
business reaching. A port that exposed all of it would document a dependency
that does not exist and invite one that should not.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.domain.models.payment import Payment


class PaymentRepositoryPort(ABC):
    """Persistence contract for driving a payment to its terminal state."""

    @abstractmethod
    def get_payment(self, payment_id: str) -> Payment | None:
        """Load one payment, or None if the identifier is unknown."""
        ...

    @abstractmethod
    def get_payment_by_end_to_end_id(self, end_to_end_id: str) -> Payment | None:
        """
        Load the payment carrying a caller-supplied reference, or None.

        The bank knows a transfer by its `end_to_end_id`; it has never seen the
        gateway's `payment_id`. This is how a settlement confirmation arriving
        from a rail is matched back to the payment that caused it.
        """
        ...

    @abstractmethod
    def update_payment(self, payment: Payment) -> None:
        """Persist a payment's current state."""
        ...

    @abstractmethod
    def create_webhook_event(
        self,
        payment_id: str,
        webhook_url: str,
        payload: dict,
    ) -> str:
        """
        Queue a status notification for delivery to a third party.

        Returns:
            The identifier of the queued event.
        """
        ...
