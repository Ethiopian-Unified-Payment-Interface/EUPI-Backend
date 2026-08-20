"""
Awash Bank — CBS Adapter
========================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Production: calls Kifiya's Awash CBS middleware REST endpoint.
Simulated:  reads and writes the shared simulated core banking system, so a
            transfer through this rail actually debits and credits.

Awash rail characteristics:
  - Order references in Awash's house format, "AWB-TXN-<date>-<ref>"
  - Highest reliability of the six rails (99.2%), lowest latency (~75ms)
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


class AwashCBSAdapter(SimulatedBankAdapter):
    """
    Awash Bank — Core Banking System Adapter.

    In production this adapter calls Awash's modern REST/JSON endpoints with an
    OAuth2 bearer credential, translating `accountHolderName` and friends onto
    the gateway's normalised domain models.
    """

    _BASE_URL = "https://api.awashbank.com/cbs/v1"
    _ACCOUNT_ENDPOINT = "/accounts"
    _STATEMENT_ENDPOINT = "/statements"
    _TRANSFER_ENDPOINT = "/transfers"
    _HEALTH_ENDPOINT = "/health"

    _ORDER_PREFIX = "AWB-TXN"
    _TRANSACTION_CODE_PREFIX = "AWB"
    _UPTIME = 0.992

    def __init__(
        self,
        engine: SimulatedCoreBankingEngine,
        api_key: str = settings.AWASH_CBS_API_KEY,
    ) -> None:
        super().__init__(engine=engine, api_key=api_key)

    @property
    def bank_id(self) -> BankID:
        return BankID.AWASH
