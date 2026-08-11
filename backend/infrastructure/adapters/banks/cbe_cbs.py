"""
Commercial Bank of Ethiopia — CBS Adapter
==========================================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

CBE is Ethiopia's largest bank with the most standardised API.
Production: calls Kifiya's CBE CBS middleware endpoint.
Mock (MVP): returns deterministic data simulating CBE's REST API format.

CBE API characteristics simulated:
  - Account numbers: 13-digit numeric strings
  - REST-style response with snake_case JSON fields
  - Richer transaction metadata (category codes, beneficiary details)
  - Highest reliability (~98.5% uptime) and fastest latency (~95ms)
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


class CBECBSAdapter(BankPort):
    """
    Commercial Bank of Ethiopia — Core Banking System Adapter.

    CBE's API is more RESTful and standardised than other Ethiopian banks,
    reflecting its scale and government backing. Fields use snake_case JSON.
    """

    _BASE_URL = "https://openapi.combanketh.et/cbs/v3"
    _ACCOUNT_ENDPOINT = "/accounts/{account_number}/summary"
    _STATEMENT_ENDPOINT = "/accounts/{account_number}/transactions"
    _TRANSFER_ENDPOINT = "/payments/outward"
    _HEALTH_ENDPOINT = "/system/health"

    _NARRATIONS = [
        "Salary payment - Ethiopian Government Payroll",
        "CBE Direct: Ethiopian Airlines stipend",
        "CBE-IB: Commercial invoice settlement",
        "CBE ATM: Cash withdrawal Meskel Square",
        "CBE Mobile: Telebirr wallet top-up",
        "CBE-RTGS: Large value government transfer",
        "CBE-ACH: EFT from Wegagen Bank",
        "CBE-POS: Ethiopian Skylight Hotel settlement",
        "CBE Mobile: School fees payment",
        "CBE-SWIFT: Inward remittance from UAE",
    ]

    def __init__(self, api_key: str = settings.CBE_CBS_API_KEY) -> None:
        self._api_key = api_key
        self._headers = {
            "X-API-Key": api_key,
            "X-Institution-Code": "KIFIYA",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def bank_id(self) -> BankID:
        return BankID.CBE

    def health_check(self) -> bool:
        """
        Production: GET {_BASE_URL}{_HEALTH_ENDPOINT} expecting {"status": "UP"}.
        Mock: 98.5% uptime simulation (highest of the three banks).
        """
        return random.random() < 0.985

    def get_balance(self, account_number: str) -> Account:
        raw = self._mock_account_response(account_number)
        return self._normalise_account(raw)

    def get_transactions(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Transaction]:
        raw_txns = self._mock_statement_response(account_number, from_date, to_date)
        return [self._normalise_transaction(t, account_number) for t in raw_txns]

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
        Production:
            POST {_BASE_URL}{_TRANSFER_ENDPOINT}
            Body: {source_account, beneficiary_account, beneficiary_bank_code,
                   amount, currency, reference, narration}
            Returns: {"transaction_reference": "CBE-TRF-..."}
        """
        ref_suffix = end_to_end_id[-8:].upper() if len(end_to_end_id) >= 8 else end_to_end_id.upper()
        return f"CBE-TRF-{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M')}-{ref_suffix}"

    # ── Mock Response Simulators ───────────────────────────────────────────────

    def _mock_account_response(self, account_number: str) -> dict:
        """
        Simulates CBE's REST API account summary response (snake_case fields).
        Seeded by account number for determinism.
        """
        rng = random.Random(hash(f"CBE:{account_number}"))
        available = Decimal(str(round(rng.uniform(20_000, 500_000), 2)))
        ledger = available + Decimal(str(round(rng.uniform(500, 20_000), 2)))
        account_class = rng.choice(["PERSONAL_SAVINGS", "CURRENT", "SALARY"])

        # CBE's REST response format
        return {
            "account_number": account_number,
            "holder_name": "ABEBE GIRMA TADESSE",
            "account_class": account_class,
            "branch_code": rng.choice(["CBE001", "CBE004", "CBE012", "CBE089"]),
            "currency_code": "ETB",
            "available_balance": str(available),
            "book_balance": str(ledger),
            "account_status": "ACTIVE",
            "opened_date": "2017-08-20",
            "last_transaction_date": datetime.now(tz=timezone.utc).date().isoformat(),
        }

    def _mock_statement_response(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        rng = random.Random(hash(f"CBE:STMT:{account_number}"))
        entries = []
        current = to_date
        num_entries = rng.randint(8, 20)

        for _ in range(num_entries):
            current -= timedelta(days=rng.randint(1, 15))
            if current < from_date:
                break
            is_credit = rng.random() > 0.45
            channel = rng.choice(["MOBILE_BANKING", "ATM", "INTERNET_BANKING", "POS", "BRANCH"])
            entries.append({
                "transaction_id": f"CBE-{rng.randint(10_000_000, 99_999_999)}",
                "transaction_date": current.isoformat(),
                "value_date": current.isoformat(),
                "transaction_type": "CREDIT" if is_credit else "DEBIT",
                "amount": str(round(rng.uniform(100, 50_000), 2)),
                "currency": "ETB",
                "narration": rng.choice(self._NARRATIONS),
                "beneficiary_name": rng.choice(["Ministry of Finance", "Tigist Haile", "Coop Bank Transfer", "Kifiya Tech", "UNDP Ethiopia"]),
                "beneficiary_account": f"****{rng.randint(1000, 9999)}",
                "channel": channel,
                "status": "BOOKED",
                "category_code": rng.choice(["SALARY", "TRANSFER", "UTILITY", "PURCHASE", "GOVERNMENT"]),
            })
        return entries

    # ── Normalisers ────────────────────────────────────────────────────────────

    def _normalise_account(self, raw: dict) -> Account:
        class_map = {
            "PERSONAL_SAVINGS": AccountType.SAVINGS,
            "CURRENT": AccountType.CURRENT,
            "SALARY": AccountType.CURRENT,
        }
        return Account(
            account_id=f"ACC-CBE-{raw['account_number'][-8:]}",
            bank_id=BankID.CBE,
            account_number=f"****{raw['account_number'][-4:]}",
            account_type=class_map.get(raw["account_class"], AccountType.CURRENT),
            currency=Currency.ETB,
            available_balance=Decimal(raw["available_balance"]),
            ledger_balance=Decimal(raw["book_balance"]),
            account_name=raw["holder_name"].title(),
            is_active=raw["account_status"] == "ACTIVE",
            last_updated_at=datetime.now(tz=timezone.utc),
        )

    def _normalise_transaction(self, raw: dict, account_number: str) -> Transaction:
        channel_map = {
            "MOBILE_BANKING": TransactionChannel.MOBILE,
            "ATM": TransactionChannel.ATM,
            "POS": TransactionChannel.POS,
            "INTERNET_BANKING": TransactionChannel.INTERNET,
            "BRANCH": TransactionChannel.BRANCH,
        }
        txn_dt = datetime.fromisoformat(raw["transaction_date"]).replace(tzinfo=timezone.utc)
        return Transaction(
            transaction_id=raw["transaction_id"],
            account_id=f"ACC-CBE-{account_number[-8:]}",
            bank_id=BankID.CBE.value,
            transaction_type=TransactionType.CREDIT if raw["transaction_type"] == "CREDIT" else TransactionType.DEBIT,
            status=TransactionStatus.BOOKED,
            amount=Decimal(raw["amount"]),
            currency="ETB",
            value_date=txn_dt,
            booking_date=txn_dt,
            channel=channel_map.get(raw.get("channel", ""), None),
            counterparty_name=raw.get("beneficiary_name"),
            counterparty_account=raw.get("beneficiary_account"),
            remittance_info=RemittanceInfo(
                end_to_end_id=raw["transaction_id"],
                unstructured=raw.get("narration"),
            ),
            bank_transaction_code=f"CBE-{raw.get('category_code', 'GEN')}",
        )
