"""
Bank of Abyssinia — CBS Adapter
===============================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Bank of Abyssinia (Abisiniya) is one of Ethiopia's premier private commercial banks,
known for digital innovations like Apollo.
Production: calls Kifiya's Abyssinia CBS middleware REST endpoint.
Mock (MVP): simulates Abyssinia's REST/JSON API format.

Abyssinia API characteristics simulated:
  - Account numbers: 13-digit numeric strings starting with "0022"
  - Modern JSON payloads with `account_no`, `avail_bal`, `acct_name`
  - High retail and corporate balance volume
  - High reliability (98.8% uptime), fast response latency (~85ms)
  - Standard transaction fee (2.50 ETB)
"""

from __future__ import annotations

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


class AbyssiniaCBSAdapter(BankPort):
    """
    Bank of Abyssinia — Core Banking System Adapter.

    Abyssinia's core banking integration uses standardized snake_case JSON schemas.
    """

    _BASE_URL = "https://api.bankofabyssinia.com/v1"
    _ACCOUNT_ENDPOINT = "/accounts/detail"
    _STATEMENT_ENDPOINT = "/accounts/statement"
    _TRANSFER_ENDPOINT = "/payments/transfer"
    _HEALTH_ENDPOINT = "/system/health"

    _NARRATIONS = [
        "BOA-APOLLO: Digital P2P transfer",
        "BOA-ATM: Bole Road ATM Cash Out",
        "BOA-POS: Hilton Addis Merchant Payment",
        "BOA-FT: Inward domestic wire transfer",
        "BOA-AIR: Ethio Telecom mobile topup",
        "BOA-QR: Merchant QR code scan pay",
        "BOA-SAL: Monthly salary credit",
        "BOA-ECOM: Ecommerce Online Checkout",
        "BOA-TAX: Ministry of Revenue Tax Settlement",
        "BOA-SAV: Target savings automated debit",
    ]

    def __init__(self, api_key: str = settings.ABYSSINIA_CBS_API_KEY) -> None:
        self._api_key = api_key
        self._headers = {
            "BOA-Api-Key": api_key,
            "BOA-Channel-ID": "KIFIYA-OPEN-GATEWAY",
            "Content-Type": "application/json",
        }

    @property
    def bank_id(self) -> BankID:
        return BankID.ABYSSINIA

    def health_check(self) -> bool:
        """
        Production: GET {_BASE_URL}{_HEALTH_ENDPOINT}
        Mock: 98.8% uptime simulation.
        """
        return random.random() < 0.988

    def get_balance(self, account_number: str) -> Account:
        raw = self._mock_account_response(account_number)
        return self._normalise_account(raw)

    def get_transactions(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Transaction]:
        raw_entries = self._mock_statement_response(account_number, from_date, to_date)
        return [self._normalise_transaction(e, account_number) for e in raw_entries]

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
        Production: POST {_BASE_URL}{_TRANSFER_ENDPOINT}
        Response contains `boa_ref` string.
        """
        ref_suffix = end_to_end_id[-8:].upper() if len(end_to_end_id) >= 8 else end_to_end_id.upper()
        return f"BOA-TXN-{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}-{ref_suffix}"

    # ── Mock Response Simulators ───────────────────────────────────────────────

    def _mock_account_response(self, account_number: str) -> dict:
        """
        Simulates Bank of Abyssinia's JSON API response.
        """
        rng = random.Random(hash(f"BOA:{account_number}"))
        available = Decimal(str(round(rng.uniform(5_000, 110_000), 2)))
        ledger = available + Decimal(str(round(rng.uniform(200, 3_000), 2)))

        _ACCOUNT_MAP = {
            "1000234567890": "ABEBE GIRMA TADESSE",
            "1000111222333": "ABEBE GIRMA TADESSE",
            "1000333444555": "ABEBE GIRMA TADESSE",
            "1000666777888": "ABEBE GIRMA TADESSE",
            "1000555666777": "ABEBE GIRMA TADESSE",
            "1000111999888": "ABEBE GIRMA TADESSE",
            "1000987654321": "SELAMAWIT BEKELE HAILU",
            "1000444555666": "SELAMAWIT BEKELE HAILU",
            "1000777888999": "SELAMAWIT BEKELE HAILU",
            "1000888999000": "SELAMAWIT BEKELE HAILU",
            "1000222888777": "SELAMAWIT BEKELE HAILU",
            "1000101010101": "DANIEL KEBEDE WOLDETSADIK",
            "1000202020202": "DANIEL KEBEDE WOLDETSADIK",
            "1000303030303": "DANIEL KEBEDE WOLDETSADIK",
            "1000404040404": "TEWODROS KASSAHUN",
            "1000505050505": "TEWODROS KASSAHUN",
            "1000606060606": "TEWODROS KASSAHUN",
            "1000707070707": "BETELHEM DESALEGN",
            "1000808080808": "BETELHEM DESALEGN",
            "1000909090909": "YARED ASHENAFI",
            "1000121212121": "YARED ASHENAFI",
        }
        holder_name = _ACCOUNT_MAP.get(account_number, "ABEBE GIRMA TADESSE")

        return {
            "account_no": account_number,
            "account_name": holder_name,
            "account_category": rng.choice(["SAVINGS", "CURRENT"]),
            "branch_code": rng.choice(["BOA-ADD01", "BOA-BOL02", "BOA-KAZ03"]),
            "currency_code": "ETB",
            "avail_balance": str(available),
            "ledger_balance": str(ledger),
            "status": "ACTIVE",
            "product_name": "BOA_APOLLO_DIGITAL",
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }

    def _mock_statement_response(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        rng = random.Random(hash(f"BOA:STMT:{account_number}"))
        entries = []
        current = to_date
        num_entries = rng.randint(4, 14)

        for _ in range(num_entries):
            current -= timedelta(days=rng.randint(1, 22))
            if current < from_date:
                break
            is_credit = rng.random() > 0.48
            entries.append({
                "txn_reference": f"BOA{rng.randint(100_000_000, 999_999_999)}",
                "value_date": current.isoformat(),
                "booking_date": current.isoformat(),
                "txn_direction": "CREDIT" if is_credit else "DEBIT",
                "txn_amount": str(round(rng.uniform(80, 12_000), 2)),
                "currency": "ETB",
                "narration_text": rng.choice(self._NARRATIONS),
                "counterparty_title": rng.choice(["Abyssinia Commercial", "Ethio Telecom", "Bole Grocery", "CBE Gateway", "Hilton Addis"]),
                "counterparty_account_no": f"****{rng.randint(1000, 9999)}",
                "channel_type": rng.choice(["MOBILE", "ATM", "POS", "BRANCH"]),
                "status_code": "SUCCESS",
            })
        return entries

    # ── Normalisers ────────────────────────────────────────────────────────────

    def _normalise_account(self, raw: dict) -> Account:
        cat_map = {"SAVINGS": AccountType.SAVINGS, "CURRENT": AccountType.CURRENT}
        return Account(
            account_id=f"ACC-BOA-{raw['account_no'][-8:]}",
            bank_id=BankID.ABYSSINIA,
            account_number=f"****{raw['account_no'][-4:]}",
            account_type=cat_map.get(raw["account_category"], AccountType.SAVINGS),
            currency=Currency.ETB,
            available_balance=Decimal(raw["avail_balance"]),
            ledger_balance=Decimal(raw["ledger_balance"]),
            account_name=raw["account_name"].title(),
            is_active=raw["status"] == "ACTIVE",
            last_updated_at=datetime.now(tz=timezone.utc),
        )

    def _normalise_transaction(self, raw: dict, account_number: str) -> Transaction:
        channel_map = {
            "MOBILE": TransactionChannel.MOBILE,
            "ATM": TransactionChannel.ATM,
            "POS": TransactionChannel.POS,
            "BRANCH": TransactionChannel.BRANCH,
        }
        try:
            txn_dt = datetime.fromisoformat(raw["value_date"])
        except ValueError:
            txn_dt = datetime.now(tz=timezone.utc)

        return Transaction(
            transaction_id=raw["txn_reference"],
            account_id=f"ACC-BOA-{account_number[-8:]}",
            bank_id=BankID.ABYSSINIA.value,
            transaction_type=TransactionType.CREDIT if raw["txn_direction"] == "CREDIT" else TransactionType.DEBIT,
            status=TransactionStatus.BOOKED,
            amount=Decimal(raw["txn_amount"]),
            currency="ETB",
            value_date=txn_dt,
            booking_date=txn_dt,
            channel=channel_map.get(raw.get("channel_type", ""), None),
            counterparty_name=raw.get("counterparty_title"),
            counterparty_account=raw.get("counterparty_account_no"),
            remittance_info=RemittanceInfo(
                end_to_end_id=raw["txn_reference"],
                unstructured=raw.get("narration_text"),
            ),
            bank_transaction_code=f"BOA-{raw.get('channel_type', 'UNK')}",
        )
