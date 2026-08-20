"""
Commercial Bank of Ethiopia — CBS Adapter
==========================================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Production: calls Kifiya's CBE CBS middleware endpoint.
Simulated:  reads and writes the shared simulated core banking system, so a
            transfer through this rail actually debits and credits.

CBE rail characteristics:
  - Order references in CBE's house format, "CBE-TRF-<date>-<ref>"
  - Highest reliability (98.5%) and fastest latency (~95ms) of the six rails
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


class CBECBSAdapter(SimulatedBankAdapter):
    """
    Commercial Bank of Ethiopia — Core Banking System Adapter.

    In production this adapter calls Kifiya's CBE middleware, translating CBE's
    snake_case REST payloads onto the gateway's normalised domain models.
    """

    _BASE_URL = "https://openapi.combanketh.et/cbs/v3"
    _ACCOUNT_ENDPOINT = "/accounts/{account_number}/summary"
    _STATEMENT_ENDPOINT = "/accounts/{account_number}/transactions"
    _TRANSFER_ENDPOINT = "/payments/outward"
    _HEALTH_ENDPOINT = "/system/health"

    _ORDER_PREFIX = "CBE-TRF"
    _TRANSACTION_CODE_PREFIX = "CBE"
    _UPTIME = 0.985

    def __init__(
        self,
        engine: SimulatedCoreBankingEngine,
        api_key: str = settings.CBE_CBS_API_KEY,
    ) -> None:
        super().__init__(engine=engine, api_key=api_key)

    @property
    def bank_id(self) -> BankID:
        return BankID.CBE
