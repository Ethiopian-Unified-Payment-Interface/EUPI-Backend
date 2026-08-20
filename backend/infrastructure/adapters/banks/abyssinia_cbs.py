"""
Bank of Abyssinia — CBS Adapter
===============================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Production: calls Kifiya's Abyssinia CBS middleware REST endpoint.
Simulated:  reads and writes the shared simulated core banking system, so a
            transfer through this rail actually debits and credits.

Abyssinia rail characteristics:
  - Order references in Abyssinia's house format, "BOA-TXN-<date>-<ref>"
  - High reliability (98.8%), fast response latency (~85ms)
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


class AbyssiniaCBSAdapter(SimulatedBankAdapter):
    """
    Bank of Abyssinia — Core Banking System Adapter.

    In production this adapter calls Abyssinia's REST/JSON endpoints,
    translating `account_no` / `avail_bal` / `acct_name` onto the gateway's
    normalised domain models.
    """

    _BASE_URL = "https://api.bankofabyssinia.com/v1"
    _ACCOUNT_ENDPOINT = "/accounts/detail"
    _STATEMENT_ENDPOINT = "/accounts/statement"
    _TRANSFER_ENDPOINT = "/payments/transfer"
    _HEALTH_ENDPOINT = "/system/health"

    _ORDER_PREFIX = "BOA-TXN"
    _TRANSACTION_CODE_PREFIX = "BOA"
    _UPTIME = 0.988

    def __init__(
        self,
        engine: SimulatedCoreBankingEngine,
        api_key: str = settings.ABYSSINIA_CBS_API_KEY,
    ) -> None:
        super().__init__(engine=engine, api_key=api_key)

    @property
    def bank_id(self) -> BankID:
        return BankID.ABYSSINIA
