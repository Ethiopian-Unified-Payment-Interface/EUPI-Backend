"""
Mock Bank Adapter — for local development & Swagger testing.
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters
Legacy mock adapter. Superseded by the per-bank CBS adapters (coop_cbs.py, cbe_cbs.py, wegagen_cbs.py).

Each mock bank returns slightly different data so fan-out aggregation is visible in Swagger.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.application.ports.bank_port import BankPort
from backend.domain.models.account import Account, AccountType, BankID, Currency
from backend.domain.models.transaction import (
    RemittanceInfo,
    Transaction,
    TransactionChannel,
    TransactionStatus,
    TransactionType,
)


class _MockBankAdapter(BankPort):
    """Shared mock logic — parameterised per bank."""

    def __init__(
        self,
        bank_id: BankID,
        account_name: str,
        balance: Decimal,
    ) -> None:
        self._bank_id = bank_id
        self._account_name = account_name
        self._balance = balance

    @property
    def bank_id(self) -> BankID:
        return self._bank_id

    def health_check(self) -> bool:
        return True

    def get_balance(self, account_number: str) -> Account:
        return Account(
            account_id=f"ACC-{self._bank_id.value}-MOCK-001",
            bank_id=self._bank_id,
            account_number="****1234",
            account_type=AccountType.SAVINGS,
            currency=Currency.ETB,
            available_balance=self._balance,
            ledger_balance=self._balance + Decimal("250.00"),
            account_name=self._account_name,
            is_active=True,
            last_updated_at=datetime.now(tz=timezone.utc),
        )

    def get_transactions(
        self,
        account_number: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Transaction]:
        now = datetime.now(tz=timezone.utc)
        return [
            Transaction(
                transaction_id=f"TXN-{self._bank_id.value}-001",
                account_id=f"ACC-{self._bank_id.value}-MOCK-001",
                bank_id=self._bank_id.value,
                transaction_type=TransactionType.CREDIT,
                status=TransactionStatus.BOOKED,
                amount=Decimal("5000.00"),
                currency="ETB",
                value_date=now - timedelta(days=5),
                booking_date=now - timedelta(days=5),
                channel=TransactionChannel.MOBILE,
                counterparty_name="Kifiya Financial Technologies",
                remittance_info=RemittanceInfo(
                    end_to_end_id="E2E-MOCK-001",
                    unstructured="Salary payment – November 2025",
                ),
            ),
            Transaction(
                transaction_id=f"TXN-{self._bank_id.value}-002",
                account_id=f"ACC-{self._bank_id.value}-MOCK-001",
                bank_id=self._bank_id.value,
                transaction_type=TransactionType.DEBIT,
                status=TransactionStatus.BOOKED,
                amount=Decimal("320.00"),
                currency="ETB",
                value_date=now - timedelta(days=2),
                booking_date=now - timedelta(days=2),
                channel=TransactionChannel.POS,
                counterparty_name="Addis Supermarket",
                remittance_info=RemittanceInfo(
                    end_to_end_id="E2E-MOCK-002",
                    unstructured="Grocery purchase",
                ),
            ),
        ]

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
        # Return a deterministic fake order reference.
        return f"{self._bank_id.value}-ORD-MOCK-{end_to_end_id[-6:].upper()}"


# ── Public factory instances — one per bank rail ──────────────────────────────

class CoopMockAdapter(_MockBankAdapter):
    def __init__(self) -> None:
        super().__init__(BankID.COOP, "Abebe Girma Tadesse", Decimal("12500.75"))


class CBEMockAdapter(_MockBankAdapter):
    def __init__(self) -> None:
        super().__init__(BankID.CBE, "Abebe Girma Tadesse", Decimal("8300.00"))


class WegagenMockAdapter(_MockBankAdapter):
    def __init__(self) -> None:
        super().__init__(BankID.WEGAGEN, "Abebe Girma Tadesse", Decimal("4120.50"))
