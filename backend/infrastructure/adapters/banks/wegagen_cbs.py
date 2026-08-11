"""
Wegagen Bank — CBS Adapter
===========================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Rule: ONLY layer allowed to make external HTTP calls.

Wegagen is a mid-size private commercial bank, strong in retail and SME.
Production: calls Kifiya's Wegagen CBS middleware endpoint.
Mock (MVP): simulates Wegagen's XML-style API format (wrapped in Python dict).

Wegagen API characteristics simulated:
  - Account numbers: 13-digit numeric strings starting with "0011"
  - Older SOAP/XML API style translated to dict for readability
  - Smaller retail balances, more frequent small transactions
  - Medium reliability (97% uptime), medium latency (~140ms)
  - Lowest transaction fee (2.00 ETB) — often wins on cost scoring
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


class WegagenCBSAdapter(BankPort):
    """
    Wegagen Bank — Core Banking System Adapter.

    Wegagen's legacy system uses a SOAP-derived XML API; this adapter
    translates the XML payload to a Python dict before normalising to the
    domain model. Field naming uses PascalCase (XML style).
    """

    _BASE_URL = "https://cbs.wegagenbank.com/openapi/v1"
    _ACCOUNT_ENDPOINT = "/GetAccountInfo"
    _STATEMENT_ENDPOINT = "/GetAccountStatement"
    _TRANSFER_ENDPOINT = "/InitiateTransfer"
    _HEALTH_ENDPOINT = "/SystemStatus"

    _NARRATIONS = [
        "WGB-MOB: Mobile banking transfer",
        "WGB-ATM: Cash withdrawal Bole road",
        "WGB-POS: Restaurant Yod Abyssinia",
        "WGB-EFT: Received from Awash Bank",
        "WGB-MOB: Ethio Telecom bill payment",
        "WGB-SME: Business loan repayment",
        "WGB-MOB: Wegagen WegaPay P2P",
        "WGB-DOM: Domestic wire settlement",
        "WGB-INS: Insurance premium auto-debit",
        "WGB-MOB: Market vendor payment QR",
    ]

    def __init__(self, api_key: str = settings.WEGAGEN_CBS_API_KEY) -> None:
        self._api_key = api_key
        self._headers = {
            "WGB-API-Token": api_key,
            "WGB-Client": "KIFIYA-GATEWAY",
            "Content-Type": "application/xml",   # Wegagen's API is XML-based
        }

    @property
    def bank_id(self) -> BankID:
        return BankID.WEGAGEN

    def health_check(self) -> bool:
        """
        Production: POST {_BASE_URL}{_HEALTH_ENDPOINT} with SOAP envelope.
        Mock: 97.0% uptime simulation.
        """
        return random.random() < 0.970

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
        Production: POST XML SOAP envelope to {_BASE_URL}{_TRANSFER_ENDPOINT}.
        Response parsed from <TransactionRef> XML element.
        """
        ref_suffix = end_to_end_id[-8:].upper() if len(end_to_end_id) >= 8 else end_to_end_id.upper()
        return f"WGB-TXN-{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}-{ref_suffix}"

    # ── Mock Response Simulators ───────────────────────────────────────────────

    def _mock_account_response(self, account_number: str) -> dict:
        """
        Simulates Wegagen's XML API response translated to a Python dict.
        PascalCase field names mirror their XML element structure.
        """
        rng = random.Random(hash(f"WGB:{account_number}"))
        available = Decimal(str(round(rng.uniform(3_000, 60_000), 2)))
        ledger = available + Decimal(str(round(rng.uniform(50, 2_000), 2)))

        # PascalCase keys mirror Wegagen's XML <Element> naming
        return {
            "AccountNumber": account_number,
            "AccountHolderName": "ABEBE GIRMA TADESSE",
            "AccountCategory": rng.choice(["S", "C"]),  # S=Savings, C=Current
            "BranchCode": rng.choice(["WGB-ADD01", "WGB-ADD05", "WGB-HAW01"]),
            "Currency": "ETB",
            "AvailableBalance": str(available),
            "LedgerBalance": str(ledger),
            "Status": rng.choice(["ACTIVE", "ACTIVE", "ACTIVE", "DORMANT"]),  # mostly active
            "ProductCode": rng.choice(["WGB-SAV001", "WGB-CUR002", "WGB-SME001"]),
            "LastActivityDate": datetime.now(tz=timezone.utc).strftime("%d/%m/%Y"),  # Wegagen uses DD/MM/YYYY
        }

    def _mock_statement_response(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        rng = random.Random(hash(f"WGB:STMT:{account_number}"))
        entries = []
        current = to_date
        num_entries = rng.randint(4, 12)

        for _ in range(num_entries):
            current -= timedelta(days=rng.randint(1, 25))
            if current < from_date:
                break
            is_credit = rng.random() > 0.42
            entries.append({
                "EntrySeqNo": f"WGB{rng.randint(1_000_000, 9_999_999)}",
                "ValueDate": current.strftime("%d/%m/%Y"),  # Wegagen DD/MM/YYYY format
                "PostDate": current.strftime("%d/%m/%Y"),
                "DrCr": "C" if is_credit else "D",
                "Amount": str(round(rng.uniform(50, 8_000), 2)),
                "Currency": "ETB",
                "Narration": rng.choice(self._NARRATIONS),
                "CounterpartyName": rng.choice(["Tigist Haile", "Abiy Industries", "Coop Bank", "Telebirr", "EEPCO"]),
                "CounterpartyAcct": f"****{rng.randint(1000, 9999)}",
                "ChannelCode": rng.choice(["MB", "AT", "PS", "BR"]),
                "TxnStatus": "BOK",
            })
        return entries

    # ── Normalisers ────────────────────────────────────────────────────────────

    def _normalise_account(self, raw: dict) -> Account:
        cat_map = {"S": AccountType.SAVINGS, "C": AccountType.CURRENT}
        return Account(
            account_id=f"ACC-WGB-{raw['AccountNumber'][-8:]}",
            bank_id=BankID.WEGAGEN,
            account_number=f"****{raw['AccountNumber'][-4:]}",
            account_type=cat_map.get(raw["AccountCategory"], AccountType.SAVINGS),
            currency=Currency.ETB,
            available_balance=Decimal(raw["AvailableBalance"]),
            ledger_balance=Decimal(raw["LedgerBalance"]),
            account_name=raw["AccountHolderName"].title(),
            is_active=raw["Status"] == "ACTIVE",
            last_updated_at=datetime.now(tz=timezone.utc),
        )

    def _normalise_transaction(self, raw: dict, account_number: str) -> Transaction:
        channel_map = {"MB": TransactionChannel.MOBILE, "AT": TransactionChannel.ATM,
                       "PS": TransactionChannel.POS, "BR": TransactionChannel.BRANCH}
        # Parse Wegagen's DD/MM/YYYY date format
        try:
            txn_dt = datetime.strptime(raw["ValueDate"], "%d/%m/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            txn_dt = datetime.now(tz=timezone.utc)
        return Transaction(
            transaction_id=raw["EntrySeqNo"],
            account_id=f"ACC-WGB-{account_number[-8:]}",
            bank_id=BankID.WEGAGEN.value,
            transaction_type=TransactionType.CREDIT if raw["DrCr"] == "C" else TransactionType.DEBIT,
            status=TransactionStatus.BOOKED,
            amount=Decimal(raw["Amount"]),
            currency="ETB",
            value_date=txn_dt,
            booking_date=txn_dt,
            channel=channel_map.get(raw.get("ChannelCode", ""), None),
            counterparty_name=raw.get("CounterpartyName"),
            counterparty_account=raw.get("CounterpartyAcct"),
            remittance_info=RemittanceInfo(
                end_to_end_id=raw["EntrySeqNo"],
                unstructured=raw.get("Narration"),
            ),
            bank_transaction_code=f"WGB-{raw.get('ChannelCode', 'UNK')}",
        )
