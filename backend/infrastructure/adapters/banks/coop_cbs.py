"""
Cooperative Bank of Oromia — CBS Adapter
=========================================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Production: calls Kifiya's Coop CBS integration endpoint.
Simulated:  reads and writes the shared simulated core banking system, so a
            transfer through this rail actually debits and credits.

Coop rail characteristics:
  - Order references in Coop's house format, "COOP-ORD-<date>-<ref>"
  - Slightly higher latency than CBE (~150ms), reflecting rural network routing
  - 99.1% rolling availability
"""

from __future__ import annotations

from backend.config import settings
from backend.domain.models.account import BankID
from backend.infrastructure.adapters.banks.simulation.adapter_base import (
    SimulatedBankAdapter,
)
from backend.infrastructure.adapters.banks.simulation.engine import (
    SimulatedCoreBankingEngine,
)


class CoopCBSAdapter(SimulatedBankAdapter):
    """
    Cooperative Bank of Oromia — Core Banking System Adapter.

    In production this adapter calls Kifiya's Coop CBS middleware, translating
    Coop's abbreviated field names (`acctNo`, `avlBal`) onto the gateway's
    normalised domain models. Going live means implementing `BankPort` against
    those endpoints instead of inheriting the simulated base — no use case
    changes, because none of them knows which it is talking to.
    """

    _BASE_URL = "https://cbs-api.coopethiopia.com/v2"
    _ACCOUNT_ENDPOINT = "/accounts/{account_number}"
    _STATEMENT_ENDPOINT = "/accounts/{account_number}/entries"
    _TRANSFER_ENDPOINT = "/transfers/initiate"
    _HEALTH_ENDPOINT = "/ping"

    _ORDER_PREFIX = "COOP-ORD"
    _TRANSACTION_CODE_PREFIX = "COOP"
    _UPTIME = 0.991

    def __init__(
        self,
        engine: SimulatedCoreBankingEngine,
        api_key: str = settings.COOP_CBS_API_KEY,
    ) -> None:
        super().__init__(engine=engine, api_key=api_key)

    @property
    def bank_id(self) -> BankID:
        return BankID.COOP
