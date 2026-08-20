"""
Simulated CBS → Domain Mapping
==============================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters

Translates the simulator's rows into the gateway's normalised domain models.

Each adapter used to own a `_normalise_account` that mapped its bank's
proprietary field names — `avlBal`, `AvailableBalance`, `available_bal` — onto
one schema. That translation is the whole point of the adapter layer and it
stays exactly where it is for a real CBS. But six adapters reading one
simulator are reading one schema, so repeating the mapping six times would only
create six places for it to drift.
"""

from __future__ import annotations

from backend.domain.models.account import Account, Currency
from backend.domain.models.transaction import (
    RemittanceInfo,
    Transaction,
    TransactionChannel,
    TransactionStatus,
    TransactionType,
)
from backend.infrastructure.adapters.banks.simulation.engine import (
    CREDIT,
    AccountSnapshot,
    EntrySnapshot,
)


def account_id_for(bank_id: str, account_number: str) -> str:
    """The gateway's stable account identifier for one bank account."""
    return f"ACC-{bank_id}-{account_number[-8:]}"


def mask(account_number: str) -> str:
    """Last four digits only. Full numbers never leave the adapter layer."""
    return f"****{account_number[-4:]}"


def to_account(snapshot: AccountSnapshot) -> Account:
    """
    Map a simulated account position onto the unified `Account` model.

    Args:
        snapshot: The account's current position in the simulator.

    Returns:
        The normalised domain account, with the number masked.
    """
    bank = snapshot.bank_id.value
    return Account(
        account_id=account_id_for(bank, snapshot.account_number),
        bank_id=snapshot.bank_id,
        account_number=mask(snapshot.account_number),
        account_type=snapshot.account_type,
        currency=Currency(snapshot.currency),
        available_balance=snapshot.available_balance,
        ledger_balance=snapshot.ledger_balance,
        account_name=snapshot.account_name.title(),
        is_active=snapshot.is_active,
        last_updated_at=snapshot.updated_at,
    )


def to_transaction(entry: EntrySnapshot, transaction_code_prefix: str) -> Transaction:
    """
    Map one simulated journal entry onto the unified `Transaction` model.

    Args:
        entry:                   The journal row.
        transaction_code_prefix: The bank's own code prefix, kept so a
                                 statement still looks like it came from that
                                 bank rather than from a shared simulator.

    Returns:
        The normalised domain transaction. Always BOOKED: the simulator writes
        a journal entry only once the movement has committed, so there is no
        such thing as an unbooked entry in these books.
    """
    bank = entry.bank_id.value
    return Transaction(
        transaction_id=entry.entry_id,
        account_id=account_id_for(bank, entry.account_number),
        bank_id=bank,
        transaction_type=(
            TransactionType.CREDIT if entry.direction == CREDIT else TransactionType.DEBIT
        ),
        status=TransactionStatus.BOOKED,
        amount=entry.amount,
        currency=entry.currency,
        value_date=entry.booked_at,
        booking_date=entry.booked_at,
        channel=TransactionChannel.GATEWAY,
        counterparty_name=(
            entry.counterparty_name.title() if entry.counterparty_name else None
        ),
        counterparty_account=(
            mask(entry.counterparty_account) if entry.counterparty_account else None
        ),
        remittance_info=RemittanceInfo(
            end_to_end_id=entry.end_to_end_id or entry.entry_id,
            unstructured=entry.narration or None,
        ),
        bank_transaction_code=f"{transaction_code_prefix}-{entry.entry_type}",
    )
