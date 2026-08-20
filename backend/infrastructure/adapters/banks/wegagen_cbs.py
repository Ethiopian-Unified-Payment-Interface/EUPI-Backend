"""
Wegagen Bank — CBS Adapter
===========================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Production: calls Kifiya's Wegagen CBS middleware endpoint (SOAP/XML).
Simulated:  reads and writes the shared simulated core banking system, so a
            transfer through this rail actually debits and credits.

Wegagen rail characteristics:
  - Order references in Wegagen's house format, "WGB-TXN-<date>-<ref>"
  - Medium reliability (97.0%), medium latency (~140ms)
  - Lowest transaction fee of the six rails, so it often wins on cost scoring
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


class WegagenCBSAdapter(SimulatedBankAdapter):
    """
    Wegagen Bank — Core Banking System Adapter.

    In production this adapter speaks Wegagen's older SOAP/XML interface,
    parsing `<TransactionRef>` out of the response and translating the envelope
    onto the gateway's normalised domain models.
    """

    _BASE_URL = "https://cbs.wegagenbank.com/openapi/v1"
    _ACCOUNT_ENDPOINT = "/GetAccountInfo"
    _STATEMENT_ENDPOINT = "/GetAccountStatement"
    _TRANSFER_ENDPOINT = "/InitiateTransfer"
    _HEALTH_ENDPOINT = "/SystemStatus"

    _ORDER_PREFIX = "WGB-TXN"
    _TRANSACTION_CODE_PREFIX = "WGB"
    _UPTIME = 0.970

    def __init__(
        self,
        engine: SimulatedCoreBankingEngine,
        api_key: str = settings.WEGAGEN_CBS_API_KEY,
    ) -> None:
        super().__init__(engine=engine, api_key=api_key)

    @property
    def bank_id(self) -> BankID:
        return BankID.WEGAGEN
