"""
Simulated Account Catalogue
===========================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters

The set of accounts that exist in the sandbox, and their opening positions.

Accounts are provisioned strictly: an account number outside this catalogue does
not exist at any bank, and asking about it raises `AccountNotFoundError`. The
alternative — inventing an account on first touch — is what the adapters used to
do, and it made every account number valid, every balance fictional, and account
linking a formality that could never fail.

Opening balances are derived from a keyed digest of `bank:account`, not from
`hash()`. Python randomises string hashing per process, so the previous seeding
produced different balances on every restart and different balances in every
uvicorn worker. A digest is stable forever, which is what "the same account
always has the same opening balance" actually requires.

The figures are only opening positions. Once an account exists its balance lives
in `sim_bank_accounts` and moves when money moves; nothing here is consulted
again.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from decimal import Decimal

from backend.domain.models.account import AccountType, BankID

# ── The demo population ───────────────────────────────────────────────────────
#
# Account numbers are reused across banks on purpose: the same person holds an
# account at several of them, which is what makes the aggregated balance view
# and cross-bank routing worth demonstrating. The name is the bank's KYC record
# and must match the holder's Fayda identity, or account linking rejects it.
DEMO_ACCOUNT_HOLDERS: dict[str, str] = {
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


@dataclass(frozen=True)
class BankProfile:
    """
    How one simulated bank differs from the others.

    The balance bands reproduce the ranges the previous per-adapter mocks used,
    so a CBE account still looks like a CBE account. They exist to make the
    demo data plausible, not because anything depends on them.
    """

    bank_id: BankID
    min_opening: Decimal
    max_opening: Decimal
    branch_codes: tuple[str, ...]
    account_types: tuple[AccountType, ...] = (AccountType.SAVINGS, AccountType.CURRENT)


BANK_PROFILES: dict[BankID, BankProfile] = {
    BankID.COOP: BankProfile(
        bank_id=BankID.COOP,
        min_opening=Decimal("8000"),
        max_opening=Decimal("120000"),
        branch_codes=("ADD001", "ADD015", "NZR003", "AWA007"),
    ),
    BankID.CBE: BankProfile(
        bank_id=BankID.CBE,
        min_opening=Decimal("20000"),
        max_opening=Decimal("500000"),
        branch_codes=("CBE001", "CBE004", "CBE012", "CBE089"),
    ),
    BankID.WEGAGEN: BankProfile(
        bank_id=BankID.WEGAGEN,
        min_opening=Decimal("3000"),
        max_opening=Decimal("60000"),
        branch_codes=("WGB-ADD01", "WGB-ADD05", "WGB-HAW01"),
    ),
    BankID.AWASH: BankProfile(
        bank_id=BankID.AWASH,
        min_opening=Decimal("8000"),
        max_opening=Decimal("150000"),
        branch_codes=("AWB-FIN01", "AWB-BOL02", "AWB-KAZ03"),
    ),
    BankID.ABYSSINIA: BankProfile(
        bank_id=BankID.ABYSSINIA,
        min_opening=Decimal("5000"),
        max_opening=Decimal("110000"),
        branch_codes=("BOA-ADD01", "BOA-BOL02", "BOA-KAZ03"),
    ),
    BankID.BERHAN: BankProfile(
        bank_id=BankID.BERHAN,
        min_opening=Decimal("4000"),
        max_opening=Decimal("85000"),
        branch_codes=("BRH-PIA01", "BRH-MER02", "BRH-BOL03"),
    ),
}


@dataclass(frozen=True)
class AccountSeed:
    """The opening position of one account at one bank."""

    bank_id: BankID
    account_number: str
    account_name: str
    account_type: AccountType
    branch_code: str
    opening_balance: Decimal
    currency: str = "ETB"


def is_known_account(account_number: str) -> bool:
    """Whether this account number exists anywhere in the sandbox."""
    return account_number.strip() in DEMO_ACCOUNT_HOLDERS


def seed_for(bank_id: BankID, account_number: str) -> AccountSeed | None:
    """
    The opening position for one account, or None if it does not exist.

    Args:
        bank_id:        Bank holding the account.
        account_number: Account number to look up.

    Returns:
        A deterministic `AccountSeed`, identical on every call in every
        process, or None when the account is not part of the sandbox.
    """
    number = account_number.strip()
    holder = DEMO_ACCOUNT_HOLDERS.get(number)
    if holder is None:
        return None

    profile = BANK_PROFILES.get(bank_id)
    if profile is None:
        return None

    rng = _stable_rng(f"{bank_id.value}:{number}")
    spread = profile.max_opening - profile.min_opening
    opening = profile.min_opening + (spread * Decimal(str(rng.random())))

    return AccountSeed(
        bank_id=bank_id,
        account_number=number,
        account_name=holder,
        account_type=rng.choice(profile.account_types),
        branch_code=rng.choice(profile.branch_codes),
        opening_balance=opening.quantize(Decimal("0.01")),
    )


def all_seeds() -> list[AccountSeed]:
    """
    Every account in the sandbox, across every bank.

    Used to provision the simulated banks on first boot. Ordered so that
    provisioning writes rows in a stable sequence, which keeps a re-run's
    behaviour identical and makes a diff of the seeded data readable.
    """
    seeds: list[AccountSeed] = []
    for bank_id in BANK_PROFILES:
        for account_number in DEMO_ACCOUNT_HOLDERS:
            seed = seed_for(bank_id, account_number)
            if seed is not None:
                seeds.append(seed)
    return seeds


def _stable_rng(key: str) -> random.Random:
    """
    A generator seeded identically in every process, forever.

    `hash()` on a string is salted per process by default, so seeding from it
    gave a different answer after every restart — which is why account balances
    used to change when the backend was rebooted.
    """
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))
