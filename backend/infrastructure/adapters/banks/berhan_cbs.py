"""
Berhan Bank — CBS Adapter
=========================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Production: calls Kifiya's Berhan CBS middleware API endpoint.
Simulated:  reads and writes the shared simulated core banking system, so a
            transfer through this rail actually debits and credits.

Berhan rail characteristics:
  - Order references in Berhan's house format, "BRH-TXN-<date>-<ref>"
  - Solid reliability (97.8%), medium-low latency (~110ms)
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


class BerhanCBSAdapter(SimulatedBankAdapter):
    """
    Berhan Bank — Core Banking System Adapter.

    In production this adapter calls Berhan's REST API, translating its
    uppercase response attributes (`ACCOUNT_TITLE`, `AVAILABLE_BAL`) onto the
    gateway's normalised domain models.
    """

    _BASE_URL = "https://cbs.berhanbanksc.com/api/v1"
    _ACCOUNT_ENDPOINT = "/AccountInfo"
    _STATEMENT_ENDPOINT = "/AccountStatement"
    _TRANSFER_ENDPOINT = "/FundTransfer"
    _HEALTH_ENDPOINT = "/Ping"

    _ORDER_PREFIX = "BRH-TXN"
    _TRANSACTION_CODE_PREFIX = "BRH"
    _UPTIME = 0.978

    def __init__(
        self,
        engine: SimulatedCoreBankingEngine,
        api_key: str = settings.BERHAN_CBS_API_KEY,
    ) -> None:
        super().__init__(engine=engine, api_key=api_key)

    @property
    def bank_id(self) -> BankID:
        return BankID.BERHAN
