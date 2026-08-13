"""
Berhan Bank — CBS Adapter
=========================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Berhan Bank is a fast-growing private commercial bank in Ethiopia.
Production: calls Kifiya's Berhan CBS middleware API endpoint.
Mock (MVP): simulates Berhan's CBS JSON payload structure.

Berhan API characteristics simulated:
  - Account numbers: 13-digit numeric strings starting with "0033"
  - REST API structure with uppercase response attributes
  - Strong regional presence and micro-merchant adoption
  - Solid reliability (97.8% uptime), medium-low latency (~110ms)
  - Competitive transaction fee (2.20 ETB)
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


class BerhanCBSAdapter(BankPort):
    """
    Berhan Bank — Core Banking System Adapter.

    Berhan Bank's API uses clean JSON structures with UPPERCASE keys.
    """

    _BASE_URL = "https://cbs.berhanbanksc.com/api/v1"
    _ACCOUNT_ENDPOINT = "/AccountInfo"
    _STATEMENT_ENDPOINT = "/AccountStatement"
    _TRANSFER_ENDPOINT = "/FundTransfer"
    _HEALTH_ENDPOINT = "/Ping"

    _NARRATIONS = [
        "BRH-MOB: Berhan Mobile Banking Transfer",
        "BRH-ATM: Cash Withdrawal Piassa Branch",
        "BRH-POS: Supermarket Payment Mercato",
        "BRH-EFT: Direct Debit Merchant Settlement",
        "BRH-AIR: Airtime Purchase Ethio Telecom",
        "BRH-QR: QR Code Merchant Transfer",
        "BRH-SAL: Salary Disbursement",
        "BRH-MICRO: Micro-merchant daily collection",
        "BRH-SAV: Automated savings sweep",
        "BRH-UTIL: Water and Electricity Bill Pay",
    ]

    def __init__(self, api_key: str = settings.BERHAN_CBS_API_KEY) -> None:
        self._api_key = api_key
        self._headers = {
            "BERHAN-AUTH-KEY": api_key,
            "BERHAN-SYSTEM": "KIFIYA-OPEN-GATEWAY",
            "Content-Type": "application/json",
        }

    @property
    def bank_id(self) -> BankID:
        return BankID.BERHAN

    def health_check(self) -> bool:
        """
        Production: GET {_BASE_URL}{_HEALTH_ENDPOINT}
        Mock: 97.8% uptime simulation.
        """
        return random.random() < 0.978

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
        Response contains `berhan_ref` string.
        """
        ref_suffix = end_to_end_id[-8:].upper() if len(end_to_end_id) >= 8 else end_to_end_id.upper()
        return f"BRH-TXN-{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}-{ref_suffix}"

    # ── Mock Response Simulators ───────────────────────────────────────────────

    def _mock_account_response(self, account_number: str) -> dict:
        """
        Simulates Berhan Bank's JSON API response.
        """
        rng = random.Random(hash(f"BRH:{account_number}"))
        available = Decimal(str(round(rng.uniform(4_000, 85_000), 2)))
        ledger = available + Decimal(str(round(rng.uniform(100, 2_500), 2)))

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
            "ACCOUNT_NUMBER": account_number,
            "ACCOUNT_TITLE": holder_name,
            "ACCOUNT_TYPE": rng.choice(["SAVINGS", "CURRENT"]),
            "BRANCH_NAME": rng.choice(["Piassa Branch", "Mercato Branch", "Bole Branch"]),
            "CURRENCY": "ETB",
            "AVAILABLE_BAL": str(available),
            "LEDGER_BAL": str(ledger),
            "ACCOUNT_STATUS": "ACTIVE",
            "PRODUCT_CODE": "BRH-SAV-01",
            "LAST_TXN_DATE": datetime.now(tz=timezone.utc).isoformat(),
        }

    def _mock_statement_response(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        rng = random.Random(hash(f"BRH:STMT:{account_number}"))
        entries = []
        current = to_date
        num_entries = rng.randint(4, 12)

        for _ in range(num_entries):
            current -= timedelta(days=rng.randint(1, 24))
            if current < from_date:
                break
            is_credit = rng.random() > 0.46
            entries.append({
                "REF_NO": f"BRH{rng.randint(100_000_000, 999_999_999)}",
                "VALUE_DATE": current.isoformat(),
                "POST_DATE": current.isoformat(),
                "TXN_TYPE": "CREDIT" if is_credit else "DEBIT",
                "AMOUNT": str(round(rng.uniform(60, 9_500), 2)),
                "CURRENCY": "ETB",
                "NARRATION": rng.choice(self._NARRATIONS),
                "COUNTERPARTY": rng.choice(["Berhan Merchant", "Ethio Telecom", "Mercato Trader", "CBE Gateway", "Shoa Bakery"]),
                "COUNTERPARTY_ACCT": f"****{rng.randint(1000, 9999)}",
                "CHANNEL": rng.choice(["MOBILE", "ATM", "POS", "BRANCH"]),
                "STATUS": "SUCCESS",
            })
        return entries

    # ── Normalisers ────────────────────────────────────────────────────────────

    def _normalise_account(self, raw: dict) -> Account:
        cat_map = {"SAVINGS": AccountType.SAVINGS, "CURRENT": AccountType.CURRENT}
        return Account(
            account_id=f"ACC-BRH-{raw['ACCOUNT_NUMBER'][-8:]}",
            bank_id=BankID.BERHAN,
            account_number=f"****{raw['ACCOUNT_NUMBER'][-4:]}",
            account_type=cat_map.get(raw["ACCOUNT_TYPE"], AccountType.SAVINGS),
            currency=Currency.ETB,
            available_balance=Decimal(raw["AVAILABLE_BAL"]),
            ledger_balance=Decimal(raw["LEDGER_BAL"]),
            account_name=raw["ACCOUNT_TITLE"].title(),
            is_active=raw["ACCOUNT_STATUS"] == "ACTIVE",
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
            txn_dt = datetime.fromisoformat(raw["VALUE_DATE"])
        except ValueError:
            txn_dt = datetime.now(tz=timezone.utc)

        return Transaction(
            transaction_id=raw["REF_NO"],
            account_id=f"ACC-BRH-{account_number[-8:]}",
            bank_id=BankID.BERHAN.value,
            transaction_type=TransactionType.CREDIT if raw["TXN_TYPE"] == "CREDIT" else TransactionType.DEBIT,
            status=TransactionStatus.BOOKED,
            amount=Decimal(raw["AMOUNT"]),
            currency="ETB",
            value_date=txn_dt,
            booking_date=txn_dt,
            channel=channel_map.get(raw.get("CHANNEL", ""), None),
            counterparty_name=raw.get("COUNTERPARTY"),
            counterparty_account=raw.get("COUNTERPARTY_ACCT"),
            remittance_info=RemittanceInfo(
                end_to_end_id=raw["REF_NO"],
                unstructured=raw.get("NARRATION"),
            ),
            bank_transaction_code=f"BRH-{raw.get('CHANNEL', 'UNK')}",
        )
