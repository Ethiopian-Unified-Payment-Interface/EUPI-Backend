"""
Cooperative Bank of Oromia — CBS Adapter
=========================================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Production: calls Kifiya's Coop CBS integration endpoint.
Mock (MVP): returns deterministic data simulating Coop's proprietary API format.

Coop API quirks simulated:
  - Account numbers: 16-digit numeric strings
  - Response fields use abbreviated Amharic-style keys (acctNo, avlBal, etc.)
  - Transactions called "entries" in their schema
  - Slightly higher latency than CBE (~150ms) reflecting rural network routing
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.application.ports.bank_port import BankPort
from backend.config import settings
from backend.domain.models.account import Account, AccountType, BankID, Currency
from backend.domain.models.transaction import (
    RemittanceInfo,
    Transaction,
    TransactionChannel,
    TransactionStatus,
    TransactionType,
)


class CoopCBSAdapter(BankPort):
    """
    Cooperative Bank of Oromia — Core Banking System Adapter.

    In production this adapter calls Kifiya's Coop CBS middleware.
    In MVP mode the HTTP call is replaced by a deterministic mock response.
    Swapping mock → real requires only replacing `_mock_account_response()`
    and `_mock_statement_response()` with actual httpx calls.
    """

    # Production endpoint (commented out until real integration is live)
    _BASE_URL = "https://cbs-api.coopethiopia.com/v2"
    _ACCOUNT_ENDPOINT = "/accounts/{account_number}"
    _STATEMENT_ENDPOINT = "/accounts/{account_number}/entries"
    _TRANSFER_ENDPOINT = "/transfers/initiate"
    _HEALTH_ENDPOINT = "/ping"

    # Realistic Coop transaction narrations
    _NARRATIONS = [
        "COOP-MOB: Salary credit - Kifiya Fin Tech",
        "COOP-ATM: Cash withdrawal Bole branch",
        "COOP-EFT: Cooperative dividend payment",
        "COOP-MOB: Airtime purchase Safaricom",
        "COOP-TRF: Inter-bank transfer received from CBE",
        "COOP-MOB: Utility payment - Ethiopian Electric Power",
        "COOP-POS: Purchase at Shoa Supermarket Addis",
        "COOP-MOB: Agricultural input loan repayment",
    ]

    def __init__(self, api_key: str = settings.COOP_CBS_API_KEY) -> None:
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Partner-ID": "KIFIYA-GW",
            "Content-Type": "application/json",
        }

    # ── BankPort Properties ────────────────────────────────────────────────────

    @property
    def bank_id(self) -> BankID:
        return BankID.COOP

    def health_check(self) -> bool:
        """
        Simulate Coop CBS health check.
        Production: GET {_BASE_URL}{_HEALTH_ENDPOINT} with a 5s timeout.
        Mock: 99.1% uptime simulation.
        """
        # Production code (uncomment when live):
        # try:
        #     resp = httpx.get(f"{self._BASE_URL}{self._HEALTH_ENDPOINT}",
        #                      headers=self._headers, timeout=5.0)
        #     return resp.status_code == 200
        # except httpx.RequestError:
        #     return False
        return random.random() < 0.991  # 99.1% uptime mock

    # ── AIS ───────────────────────────────────────────────────────────────────

    def get_balance(self, account_number: str) -> Account:
        """Fetch account balance from Coop CBS and normalise to domain model."""
        raw = self._mock_account_response(account_number)
        return self._normalise_account(raw)

    def get_transactions(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Transaction]:
        """Fetch account statement from Coop CBS and normalise each entry."""
        raw_entries = self._mock_statement_response(account_number, from_date, to_date)
        return [self._normalise_transaction(e, account_number) for e in raw_entries]

    # ── PIS ───────────────────────────────────────────────────────────────────

    def transfer(
        self,
        debtor_account: str,
        creditor_account: str,
        creditor_bank_id: BankID,
        amount: Decimal,
        currency: str,
        end_to_end_id: str,
        remittance_info: str | None = None,
    ) -> str:
        """
        Submit debit order to Coop CBS.
        Production: POST {_BASE_URL}{_TRANSFER_ENDPOINT} with signed payload.
        Mock: returns a realistic Coop order reference.
        """
        # Production:
        # payload = {"debtorAcct": debtor_account, "creditorAcct": creditor_account,
        #            "creditorBankCode": creditor_bank_id.value, "amount": str(amount),
        #            "currency": currency, "endToEndId": end_to_end_id,
        #            "narration": remittance_info or ""}
        # resp = httpx.post(f"{self._BASE_URL}{self._TRANSFER_ENDPOINT}",
        #                   json=payload, headers=self._headers, timeout=30.0)
        # resp.raise_for_status()
        # return resp.json()["orderRef"]

        ref_suffix = end_to_end_id[-8:].upper() if len(end_to_end_id) >= 8 else end_to_end_id.upper()
        return f"COOP-ORD-{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}-{ref_suffix}"

    # ── Private: Mock CBS Response Simulators ─────────────────────────────────

    def _mock_account_response(self, account_number: str) -> dict:
        """
        Simulates Coop Bank's proprietary CBS API account response.
        Uses a seeded RNG so the same account always returns the same balance.
        """
        rng = random.Random(hash(f"COOP:{account_number}"))
        available = Decimal(str(round(rng.uniform(8_000, 120_000), 2)))
        ledger = available + Decimal(str(round(rng.uniform(100, 5_000), 2)))

        # Coop's raw API format (proprietary field names)
        return {
            "acctNo": account_number,
            "acctName": "ABEBE GIRMA TADESSE",
            "acctType": rng.choice(["SAV", "CUR"]),
            "branchCd": rng.choice(["ADD001", "ADD015", "NZR003", "AWA007"]),
            "currCd": "ETB",
            "avlBal": str(available),
            "ledgBal": str(ledger),
            "acctSts": "A",   # A=Active, D=Dormant, C=Closed
            "openDt": "2019-03-15",
            "lastTxnDt": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
        }

    def _mock_statement_response(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        """Simulates Coop's statement endpoint with realistic Ethiopian transaction data."""
        rng = random.Random(hash(f"COOP:STMT:{account_number}"))
        entries = []
        current = to_date
        num_entries = rng.randint(5, 15)

        for i in range(num_entries):
            current -= timedelta(days=rng.randint(1, 20))
            if current < from_date:
                break
            is_credit = rng.random() > 0.4
            entries.append({
                "entryId": f"COOP-TXN-{rng.randint(100000, 999999)}",
                "txnDt": current.strftime("%Y-%m-%dT%H:%M:%S"),
                "crDr": "CR" if is_credit else "DR",
                "amt": str(round(rng.uniform(50, 15_000), 2)),
                "currCd": "ETB",
                "narr": rng.choice(self._NARRATIONS),
                "cptyName": rng.choice(["Kifiya Fin Tech", "Selam Tesfaye", "CBE Transfer", "Ethiopian Airlines", "Awash Bank"]),
                "cptyAcct": f"****{rng.randint(1000, 9999)}",
                "channel": rng.choice(["MOB", "ATM", "POS", "EFT"]),
                "sts": "BOOK",
            })
        return entries

    # ── Private: Normalisers ──────────────────────────────────────────────────

    def _normalise_account(self, raw: dict) -> Account:
        """Transform Coop's proprietary response format into the gateway Account model."""
        type_map = {"SAV": AccountType.SAVINGS, "CUR": AccountType.CURRENT}
        return Account(
            account_id=f"ACC-COOP-{raw['acctNo'][-8:]}",
            bank_id=BankID.COOP,
            account_number=f"****{raw['acctNo'][-4:]}",
            account_type=type_map.get(raw["acctType"], AccountType.SAVINGS),
            currency=Currency.ETB,
            available_balance=Decimal(raw["avlBal"]),
            ledger_balance=Decimal(raw["ledgBal"]),
            account_name=raw["acctName"].title(),
            is_active=raw["acctSts"] == "A",
            last_updated_at=datetime.now(tz=timezone.utc),
        )

    def _normalise_transaction(self, raw: dict, account_number: str) -> Transaction:
        """Transform a Coop statement entry into the gateway Transaction model."""
        channel_map = {
            "MOB": TransactionChannel.MOBILE,
            "ATM": TransactionChannel.ATM,
            "POS": TransactionChannel.POS,
            "EFT": TransactionChannel.INTERNET,
        }
        txn_dt = datetime.fromisoformat(raw["txnDt"]).replace(tzinfo=timezone.utc)
        return Transaction(
            transaction_id=raw["entryId"],
            account_id=f"ACC-COOP-{account_number[-8:]}",
            bank_id=BankID.COOP.value,
            transaction_type=TransactionType.CREDIT if raw["crDr"] == "CR" else TransactionType.DEBIT,
            status=TransactionStatus.BOOKED,
            amount=Decimal(raw["amt"]),
            currency="ETB",
            value_date=txn_dt,
            booking_date=txn_dt,
            channel=channel_map.get(raw.get("channel", ""), None),
            counterparty_name=raw.get("cptyName"),
            counterparty_account=raw.get("cptyAcct"),
            remittance_info=RemittanceInfo(
                end_to_end_id=raw["entryId"],
                unstructured=raw.get("narr"),
            ),
            bank_transaction_code=f"COOP-{raw.get('channel', 'UNK')}",
        )
