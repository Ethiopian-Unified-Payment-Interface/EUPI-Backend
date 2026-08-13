"""
Awash Bank — CBS Adapter
========================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Awash Bank is Ethiopia's largest private commercial bank.
Production: calls Kifiya's Awash CBS middleware REST endpoint.
Mock (MVP): simulates Awash's modern REST API format (JSON).

Awash API characteristics simulated:
  - Account numbers: 13-digit numeric strings starting with "0132"
  - Modern REST/JSON endpoints with OAuth2 Bearer / API token header
  - High transaction volume, premium retail balances
  - High reliability (99.2% uptime), low latency (~75ms)
  - Competitive transaction fees (3.00 ETB)
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


class AwashCBSAdapter(BankPort):
    """
    Awash Bank — Core Banking System Adapter.

    Awash Bank's digital integration API uses modern REST JSON endpoints.
    Field names follow camelCase conventions (`accountNumber`, `availableBalance`).
    """

    _BASE_URL = "https://api.awashbank.com/cbs/v1"
    _ACCOUNT_ENDPOINT = "/accounts"
    _STATEMENT_ENDPOINT = "/statements"
    _TRANSFER_ENDPOINT = "/transfers"
    _HEALTH_ENDPOINT = "/health"

    _NARRATIONS = [
        "AwashPay mobile transfer",
        "ATM withdrawal Meskel Square",
        "POS payment Friendship City Center",
        "Awash direct salary deposit",
        "Ethio Telecom Airtime purchase",
        "Merchant QR payment Bole",
        "P2P transfer Awash Mobile",
        "Cross-border remittance payout",
        "School fee payment ICS",
        "Utility bill payment AAWSA",
    ]

    def __init__(self, api_key: str = settings.AWASH_CBS_API_KEY) -> None:
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Client-ID": "KIFIYA-OPEN-GATEWAY",
            "Content-Type": "application/json",
        }

    @property
    def bank_id(self) -> BankID:
        return BankID.AWASH

    def health_check(self) -> bool:
        """
        Production: GET {_BASE_URL}{_HEALTH_ENDPOINT}
        Mock: 99.2% uptime simulation (high reliability).
        """
        return random.random() < 0.992

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
        Response contains `awashRef` string.
        """
        ref_suffix = end_to_end_id[-8:].upper() if len(end_to_end_id) >= 8 else end_to_end_id.upper()
        return f"AWB-TXN-{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}-{ref_suffix}"

    # ── Mock Response Simulators ───────────────────────────────────────────────

    def _mock_account_response(self, account_number: str) -> dict:
        """
        Simulates Awash Bank's JSON API response.
        camelCase field names mirror Awash's OpenAPI specification.
        """
        rng = random.Random(hash(f"AWASH:{account_number}"))
        available = Decimal(str(round(rng.uniform(8_000, 150_000), 2)))
        ledger = available + Decimal(str(round(rng.uniform(100, 5_000), 2)))

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
            "accountNumber": account_number,
            "accountHolderName": holder_name,
            "accountType": rng.choice(["SAVINGS", "CURRENT"]),
            "branchName": rng.choice(["Finfinne Main Branch", "Bole Medhanialem", "Kazanchis"]),
            "currency": "ETB",
            "availableBalance": str(available),
            "ledgerBalance": str(ledger),
            "accountStatus": "ACTIVE",
            "productType": "AWASH_PREMIUM_RETAIL",
            "lastActivityDate": datetime.now(tz=timezone.utc).isoformat(),
        }

    def _mock_statement_response(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        rng = random.Random(hash(f"AWASH:STMT:{account_number}"))
        entries = []
        current = to_date
        num_entries = rng.randint(5, 15)

        for _ in range(num_entries):
            current -= timedelta(days=rng.randint(1, 20))
            if current < from_date:
                break
            is_credit = rng.random() > 0.45
            entries.append({
                "txnId": f"AWB{rng.randint(100_000_000, 999_999_999)}",
                "valueDate": current.isoformat(),
                "postDate": current.isoformat(),
                "type": "CREDIT" if is_credit else "DEBIT",
                "amount": str(round(rng.uniform(100, 15_000), 2)),
                "currency": "ETB",
                "narration": rng.choice(self._NARRATIONS),
                "counterpartyName": rng.choice(["Kifiya Tech", "Ethio Telecom", "Awash Wine", "CBE Rail", "Shoa Supermarket"]),
                "counterpartyAccount": f"****{rng.randint(1000, 9999)}",
                "channel": rng.choice(["MOBILE", "ATM", "POS", "BRANCH"]),
                "status": "COMPLETED",
            })
        return entries

    # ── Normalisers ────────────────────────────────────────────────────────────

    def _normalise_account(self, raw: dict) -> Account:
        cat_map = {"SAVINGS": AccountType.SAVINGS, "CURRENT": AccountType.CURRENT}
        return Account(
            account_id=f"ACC-AWB-{raw['accountNumber'][-8:]}",
            bank_id=BankID.AWASH,
            account_number=f"****{raw['accountNumber'][-4:]}",
            account_type=cat_map.get(raw["accountType"], AccountType.SAVINGS),
            currency=Currency.ETB,
            available_balance=Decimal(raw["availableBalance"]),
            ledger_balance=Decimal(raw["ledgerBalance"]),
            account_name=raw["accountHolderName"].title(),
            is_active=raw["accountStatus"] == "ACTIVE",
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
            txn_dt = datetime.fromisoformat(raw["valueDate"])
        except ValueError:
            txn_dt = datetime.now(tz=timezone.utc)

        return Transaction(
            transaction_id=raw["txnId"],
            account_id=f"ACC-AWB-{account_number[-8:]}",
            bank_id=BankID.AWASH.value,
            transaction_type=TransactionType.CREDIT if raw["type"] == "CREDIT" else TransactionType.DEBIT,
            status=TransactionStatus.BOOKED,
            amount=Decimal(raw["amount"]),
            currency="ETB",
            value_date=txn_dt,
            booking_date=txn_dt,
            channel=channel_map.get(raw.get("channel", ""), None),
            counterparty_name=raw.get("counterpartyName"),
            counterparty_account=raw.get("counterpartyAccount"),
            remittance_info=RemittanceInfo(
                end_to_end_id=raw["txnId"],
                unstructured=raw.get("narration"),
            ),
            bank_transaction_code=f"AWB-{raw.get('channel', 'UNK')}",
        )
