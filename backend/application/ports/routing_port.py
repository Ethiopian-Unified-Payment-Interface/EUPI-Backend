"""
Port: RoutingPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO scoring logic.

Defines the contract for the Smart Payment Router. The concrete implementation
in infrastructure/adapters/router/smart_router.py MUST satisfy this ABC.

The router evaluates latency, uptime, and transaction costs across all active
bank adapters and selects the optimal rail for each payment.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.account import BankID


@dataclass(frozen=True)
class RouteScore:
    """
    Value object representing the router's evaluation of a single bank rail.

    Immutable — the concrete router creates one per candidate rail and returns
    the set to the use-case layer so callers can log or audit the decision.
    """

    bank_id: BankID
    """The bank rail being scored."""

    latency_ms: float
    """Estimated end-to-end latency in milliseconds (lower is better)."""

    uptime_percentage: float
    """Rolling 24-hour uptime of the bank's CBS (0.0–100.0; higher is better)."""

    transaction_cost_etb: Decimal
    """Estimated fee for this rail in ETB (lower is better)."""

    composite_score: float
    """
    Normalised composite score used for ranking. Higher score = preferred rail.
    Computed by the concrete router using its internal weighting matrix.
    """

    is_available: bool
    """
    True if the rail is currently healthy and within SLA thresholds.
    Rails with is_available=False are excluded from selection.
    """


class RoutingPort(ABC):
    """
    Abstract Driven Port: Smart Payment Router Interface.

    The router is invoked by the PIS use-case layer after the VERIFIED step
    and before the ORDER step. Its responsibility is to return the single
    best available bank rail for a given payment.

    Concrete implementation: infrastructure/adapters/router/smart_router.py
    """

    @abstractmethod
    def get_optimal_route(
        self,
        amount: Decimal,
        target_bank_id: BankID,
        currency: str = "ETB",
    ) -> BankID:
        """
        Select and return the single optimal banking rail for a payment.

        The concrete implementation evaluates all candidate rails using a
        scoring matrix that weighs latency, uptime, and transaction cost.
        The highest-scoring *available* rail is returned.

        Args:
            amount:        Payment amount in the given currency.
            target_bank_id: The destination bank BankID. The router MUST
                           respect this when cross-bank routing is required.
            currency:      ISO 4217 currency code (default "ETB").

        Returns:
            The :class:`~domain.models.account.BankID` of the selected rail.

        Raises:
            NoAvailableRouteError: If all evaluated rails are currently unavailable.
            RoutingError:          For any other routing failure.
        """
        ...

    @abstractmethod
    def evaluate_all_routes(
        self,
        amount: Decimal,
        target_bank_id: BankID,
        currency: str = "ETB",
    ) -> list[RouteScore]:
        """
        Return scored evaluations for every candidate rail, sorted best-first.

        This method is used for observability, audit logging, and debugging.
        The PIS use-case layer calls :meth:`get_optimal_route` for the actual
        selection, but may call this method to log the full decision matrix.

        Args:
            amount:        Payment amount in the given currency.
            target_bank_id: The destination bank BankID.
            currency:      ISO 4217 currency code (default "ETB").

        Returns:
            A list of :class:`RouteScore` objects, ordered descending by
            composite_score (best route first). May include unavailable rails
            so callers can see why certain rails were excluded.

        Raises:
            RoutingError: If route evaluation cannot complete.
        """
        ...

    @abstractmethod
    def register_rail(self, bank_id: BankID) -> None:
        """
        Register a bank rail with the router so it participates in scoring.

        Called during application startup by the dependency injection wiring
        in main.py. Each bank adapter announces itself to the router.

        Args:
            bank_id: The BankID of the adapter being registered.

        Raises:
            DuplicateRailError: If this bank_id is already registered.
        """
        ...

    @abstractmethod
    def deregister_rail(self, bank_id: BankID) -> None:
        """
        Remove a bank rail from active routing consideration.

        Called if an adapter is taken offline for maintenance. The router
        will immediately exclude this rail from future scoring until it is
        re-registered.

        Args:
            bank_id: The BankID of the adapter to deregister.

        Raises:
            RailNotFoundError: If the bank_id is not currently registered.
        """
        ...
