"""
Mock Smart Router — for local development & Swagger testing.
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Legacy mock adapter. Superseded by smart_router.py which uses live health checks.

Routing matrix (mock):
  COOP    — 120ms latency, 99.9% uptime, 2.50 ETB fee
  CBE     —  95ms latency, 98.5% uptime, 3.00 ETB fee
  WEGAGEN — 140ms latency, 97.0% uptime, 2.00 ETB fee

Composite score = (uptime × 0.5) + (1/latency × 0.3) + (1/cost × 0.2)
Best score wins. WEGAGEN typically wins on cost; CBE wins on speed.
"""

from __future__ import annotations

from decimal import Decimal

from backend.application.ports.routing_port import RouteScore, RoutingPort
from backend.domain.models.account import BankID

_MOCK_MATRIX: dict[BankID, tuple[float, float, Decimal]] = {
    # bank_id: (latency_ms, uptime_pct, cost_etb)
    BankID.COOP:    (120.0, 99.9, Decimal("2.50")),
    BankID.CBE:     ( 95.0, 98.5, Decimal("3.00")),
    BankID.WEGAGEN: (140.0, 97.0, Decimal("2.00")),
}


def _composite(latency: float, uptime: float, cost: Decimal) -> float:
    return (uptime * 0.5) + ((1.0 / latency) * 1000 * 0.3) + ((1.0 / float(cost)) * 0.2)


class MockSmartRouter(RoutingPort):
    """Mock Smart Router that scores rails using the hardcoded matrix above."""

    def __init__(self) -> None:
        self._registered: set[BankID] = set()

    def register_rail(self, bank_id: BankID) -> None:
        self._registered.add(bank_id)

    def deregister_rail(self, bank_id: BankID) -> None:
        self._registered.discard(bank_id)

    def evaluate_all_routes(
        self,
        amount: Decimal,
        target_bank_id: BankID,
        currency: str = "ETB",
    ) -> list[RouteScore]:
        scores: list[RouteScore] = []
        for bank_id in self._registered:
            if bank_id not in _MOCK_MATRIX:
                continue
            latency, uptime, cost = _MOCK_MATRIX[bank_id]
            scores.append(
                RouteScore(
                    bank_id=bank_id,
                    latency_ms=latency,
                    uptime_percentage=uptime,
                    transaction_cost_etb=cost,
                    composite_score=_composite(latency, uptime, cost),
                    is_available=True,
                )
            )
        return sorted(scores, key=lambda s: s.composite_score, reverse=True)

    def get_optimal_route(
        self,
        amount: Decimal,
        target_bank_id: BankID,
        currency: str = "ETB",
    ) -> BankID:
        ranked = self.evaluate_all_routes(amount, target_bank_id, currency)
        available = [s for s in ranked if s.is_available]
        if not available:
            raise RuntimeError("No available bank rail found for routing.")
        return available[0].bank_id
