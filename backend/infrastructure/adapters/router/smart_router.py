"""
Smart Payment Router — Production Implementation
=================================================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to call health_check() on bank ports.

Capabilities:
  - Calls bank_port.health_check() at evaluation time for live latency measurement.
  - Maintains a rolling uptime window (deque of N most recent checks).
  - Configurable weight matrix for uptime / latency / cost scoring.
  - Circuit breaker: rails with < 50% rolling uptime are excluded.
  - register_rail() accepts BankPort instances for health polling.
  - evaluate_all_routes() returns full RouteScore for audit trail.

Scoring formula (composite score ∈ [0, 1]):
    score = (W_uptime × uptime_score)
          + (W_latency × latency_score)
          + (W_cost × cost_score)

    uptime_score  = rolling_uptime_pct / 100
    latency_score = max(0, 1 - latency_ms / MAX_LATENCY)
    cost_score    = max(0, 1 - cost_etb / MAX_COST)

Higher score = preferred rail.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from decimal import Decimal

from backend.application.ports.bank_port import BankPort
from backend.application.ports.routing_port import RouteScore, RoutingPort
from backend.config import settings
from backend.domain.models.account import BankID

logger = logging.getLogger(__name__)

# ── Static cost & latency baselines per rail (ETB fee, base latency in ms) ────
# These are the "at rest" values; actual latency is measured during health_check.
_RAIL_COSTS: dict[BankID, Decimal] = {
    BankID.COOP:    Decimal("2.50"),
    BankID.CBE:     Decimal("3.00"),
    BankID.WEGAGEN: Decimal("2.00"),
    BankID.AWASH:   Decimal("2.75"),
}

_BASE_LATENCY_MS: dict[BankID, float] = {
    BankID.COOP:    150.0,
    BankID.CBE:      95.0,
    BankID.WEGAGEN: 140.0,
    BankID.AWASH:   160.0,
}

# Normalisation ceilings (values at or above these score 0)
_MAX_LATENCY_MS: float = 2_000.0
_MAX_COST_ETB: float = 50.0

# Circuit breaker: exclude rails with rolling uptime below this threshold
_MIN_UPTIME_THRESHOLD: float = 50.0


class SmartRouter(RoutingPort):
    """
    Production Smart Payment Router.

    Accepts a dict of {BankID: BankPort} at construction time so it can call
    health_check() on each port during route evaluation. The abstract
    RoutingPort.register_rail(bank_id) interface is still satisfied —
    it simply adds the bank_id to the active set.
    """

    def __init__(self, bank_ports: dict[BankID, BankPort]) -> None:
        """
        Args:
            bank_ports: Map of BankID → concrete BankPort adapter.
                        The router polls each port's health_check() during scoring.
        """
        self._bank_ports = bank_ports
        self._registered: set[BankID] = set()
        # Rolling uptime history: deque of bool (True=healthy) per bank_id
        self._uptime_history: dict[BankID, deque[bool]] = defaultdict(
            lambda: deque(maxlen=settings.ROUTER_UPTIME_WINDOW)
        )
        # Cached latency from most recent health check (ms)
        self._last_latency_ms: dict[BankID, float] = {}

    # ── RoutingPort Contract ───────────────────────────────────────────────────

    def register_rail(self, bank_id: BankID) -> None:
        """Add a bank rail to the active routing pool."""
        self._registered.add(bank_id)
        logger.info("SmartRouter: rail registered — %s", bank_id.value)

    def deregister_rail(self, bank_id: BankID) -> None:
        """Remove a bank rail from routing consideration."""
        self._registered.discard(bank_id)
        logger.warning("SmartRouter: rail deregistered — %s", bank_id.value)

    def evaluate_all_routes(
        self,
        amount: Decimal,
        target_bank_id: BankID,
        currency: str = "ETB",
    ) -> list[RouteScore]:
        """
        Score every registered rail. Called before get_optimal_route() for
        audit logging, and directly by the presentation layer for observability.
        """
        scores: list[RouteScore] = []

        for bank_id in self._registered:
            port = self._bank_ports.get(bank_id)
            if port is None:
                continue

            # Live health check with latency timing
            is_healthy, latency_ms = self._ping_with_timing(port, bank_id)
            rolling_uptime = self._rolling_uptime_pct(bank_id)
            cost = _RAIL_COSTS.get(bank_id, Decimal("5.00"))

            # Circuit breaker: mark as unavailable if uptime < threshold
            is_available = is_healthy and rolling_uptime >= _MIN_UPTIME_THRESHOLD

            composite = self._composite_score(rolling_uptime, latency_ms, cost)

            scores.append(
                RouteScore(
                    bank_id=bank_id,
                    latency_ms=latency_ms,
                    uptime_percentage=rolling_uptime,
                    transaction_cost_etb=cost,
                    composite_score=composite,
                    is_available=is_available,
                )
            )

        # Sort best-first
        return sorted(scores, key=lambda s: s.composite_score, reverse=True)

    def get_optimal_route(
        self,
        amount: Decimal,
        target_bank_id: BankID,
        currency: str = "ETB",
    ) -> BankID:
        """
        Return the highest-scoring AVAILABLE rail.

        Raises:
            RuntimeError: If no registered rail is currently available.
        """
        all_scores = self.evaluate_all_routes(amount, target_bank_id, currency)

        logger.info(
            "SmartRouter route evaluation",
            extra={
                "scores": [
                    {"bank": s.bank_id.value, "score": round(s.composite_score, 4), "available": s.is_available}
                    for s in all_scores
                ]
            },
        )

        available = [s for s in all_scores if s.is_available]
        if not available:
            raise RuntimeError(
                f"SmartRouter: no available rail found for a {currency} {amount} payment. "
                f"Evaluated rails: {[s.bank_id.value for s in all_scores]}"
            )

        winner = available[0]
        logger.info(
            "SmartRouter selected rail: %s (score=%.4f, uptime=%.1f%%, latency=%.0fms, cost=%.2f ETB)",
            winner.bank_id.value,
            winner.composite_score,
            winner.uptime_percentage,
            winner.latency_ms,
            winner.transaction_cost_etb,
        )
        return winner.bank_id

    # ── Private Helpers ────────────────────────────────────────────────────────

    def _ping_with_timing(
        self,
        port: BankPort,
        bank_id: BankID,
    ) -> tuple[bool, float]:
        """
        Call health_check() and time how long it takes.
        Records result in the rolling uptime history.

        Returns:
            (is_healthy: bool, latency_ms: float)
        """
        start = time.monotonic()
        try:
            is_healthy = port.health_check()
        except Exception as exc:
            logger.warning("SmartRouter health_check raised for %s: %s", bank_id.value, exc)
            is_healthy = False

        latency_ms = (time.monotonic() - start) * 1_000

        # Fall back to baseline latency if health check was very fast (mock returns instantly)
        if latency_ms < 1.0:
            latency_ms = _BASE_LATENCY_MS.get(bank_id, 200.0)

        self._uptime_history[bank_id].append(is_healthy)
        self._last_latency_ms[bank_id] = latency_ms

        return is_healthy, latency_ms

    def _rolling_uptime_pct(self, bank_id: BankID) -> float:
        """
        Calculate the rolling uptime percentage from the history deque.
        Returns 100.0 if no history exists yet (assume healthy until proven otherwise).
        """
        history = self._uptime_history[bank_id]
        if not history:
            return 100.0
        return (sum(history) / len(history)) * 100.0

    def _composite_score(
        self,
        uptime_pct: float,
        latency_ms: float,
        cost_etb: Decimal,
    ) -> float:
        """
        Compute a normalised composite score in [0, 1].

        Weights are sourced from settings (configurable via env vars):
            ROUTER_WEIGHT_UPTIME   default 0.50
            ROUTER_WEIGHT_LATENCY  default 0.30
            ROUTER_WEIGHT_COST     default 0.20
        """
        uptime_score = uptime_pct / 100.0
        latency_score = max(0.0, 1.0 - latency_ms / _MAX_LATENCY_MS)
        cost_score = max(0.0, 1.0 - float(cost_etb) / _MAX_COST_ETB)

        return (
            settings.ROUTER_WEIGHT_UPTIME   * uptime_score
            + settings.ROUTER_WEIGHT_LATENCY * latency_score
            + settings.ROUTER_WEIGHT_COST    * cost_score
        )
