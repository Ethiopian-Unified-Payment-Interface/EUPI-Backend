"""
Ledger and fee-engine tests.

These cover the invariants that make the accounting trustworthy. If any of
them fail, the ledger cannot be audited and no fee derived from it can be
invoiced — treat a failure here as a release blocker, not a flaky test.

Run:  py -m pytest tests/ -v
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

# Isolated DB per session, and DEBUG on so config validation stays permissive.
_TEST_DB = Path(tempfile.gettempdir()) / "eupi_ledger_tests.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB.as_posix()}")
os.environ.setdefault("DEBUG", "true")

from backend.application.use_cases.fee_service import (  # noqa: E402
    FeeService,
    NoApplicableFeeRuleError,
)
from backend.application.use_cases.ledger_service import LedgerService  # noqa: E402
from backend.domain.models.fee import (  # noqa: E402
    ANY_BANK,
    FeeQuote,
    FeeRule,
    FeeType,
)
from backend.domain.models.ledger import (  # noqa: E402
    EntryDirection,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    TransactionType,
)
from backend.infrastructure.database.ledger_repository import (  # noqa: E402
    FeeRuleRepository,
    LedgerRepository,
)
from backend.infrastructure.database.session import Database  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """
    A fresh SQLite database per test, so no test sees another's rows.

    Built the same way production does — one Database injected into every
    repository — so the tests exercise the real wiring rather than a
    per-repository engine that no longer exists.
    """
    database = Database(url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    database.create_all()
    return database


@pytest.fixture()
def ledger(db: Database) -> LedgerService:
    return LedgerService(ledger_repo=LedgerRepository(db))


@pytest.fixture()
def fees(db: Database) -> FeeService:
    service = FeeService(fee_rule_repo=FeeRuleRepository(db))
    service.seed_defaults_if_empty()
    return service


def _entry(
    transaction_ref: str,
    account_ref: str,
    direction: EntryDirection,
    amount: str,
    is_mirror: bool = True,
) -> LedgerEntry:
    return LedgerEntry(
        entry_id=f"le_{account_ref}_{direction.value}_{amount}",
        transaction_ref=transaction_ref,
        account_ref=account_ref,
        direction=direction,
        amount=Decimal(amount),
        is_mirror=is_mirror,
    )


# ── Transaction type classification ───────────────────────────────────────────


class TestTransactionType:
    def test_same_bank_is_intra(self) -> None:
        assert TransactionType.classify("COOP", "COOP") is TransactionType.INTRA_BANK

    def test_different_banks_is_cross(self) -> None:
        assert TransactionType.classify("COOP", "CBE") is TransactionType.CROSS_BANK

    def test_classification_is_case_insensitive(self) -> None:
        assert TransactionType.classify("coop", "COOP") is TransactionType.INTRA_BANK

    def test_blank_bank_is_cross_not_intra(self) -> None:
        """Two unknown banks must not be treated as the same bank."""
        assert TransactionType.classify("", "") is TransactionType.CROSS_BANK


# ── The core invariant ────────────────────────────────────────────────────────


class TestBalanceInvariant:
    def test_balanced_transaction_is_accepted(self) -> None:
        txn = LedgerTransaction(
            transaction_ref="t1",
            transaction_type=TransactionType.INTRA_BANK,
            entries=[
                _entry("t1", "CUSTOMER:COOP:111", EntryDirection.CREDIT, "100.00"),
                _entry("t1", "CUSTOMER:COOP:222", EntryDirection.DEBIT, "100.00"),
            ],
        )
        assert sum(e.signed_amount for e in txn.entries) == Decimal("0")

    def test_unbalanced_transaction_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unbalanced"):
            LedgerTransaction(
                transaction_ref="t2",
                transaction_type=TransactionType.INTRA_BANK,
                entries=[
                    _entry("t2", "CUSTOMER:COOP:111", EntryDirection.CREDIT, "100.00"),
                    _entry("t2", "CUSTOMER:COOP:222", EntryDirection.DEBIT, "99.99"),
                ],
            )

    def test_single_sided_transaction_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            LedgerTransaction(
                transaction_ref="t3",
                transaction_type=TransactionType.INTRA_BANK,
                entries=[
                    _entry("t3", "CUSTOMER:COOP:111", EntryDirection.CREDIT, "100.00")
                ],
            )

    def test_mirror_leg_cannot_offset_revenue_leg(self) -> None:
        """
        The two books balance independently. A mirror credit must never be
        allowed to balance a revenue debit — that would let orchestrated volume
        silently fund recognised income.
        """
        with pytest.raises(ValueError, match="Unbalanced"):
            LedgerTransaction(
                transaction_ref="t4",
                transaction_type=TransactionType.INTRA_BANK,
                entries=[
                    _entry("t4", "CUSTOMER:COOP:111", EntryDirection.CREDIT, "100.00", is_mirror=True),
                    _entry("t4", "FEE_REVENUE:ETB", EntryDirection.DEBIT, "100.00", is_mirror=False),
                ],
            )

    def test_entries_must_share_the_transaction_ref(self) -> None:
        with pytest.raises(ValueError, match="foreign transaction_refs"):
            LedgerTransaction(
                transaction_ref="t5",
                transaction_type=TransactionType.INTRA_BANK,
                entries=[
                    _entry("t5", "CUSTOMER:COOP:111", EntryDirection.CREDIT, "100.00"),
                    _entry("WRONG", "CUSTOMER:COOP:222", EntryDirection.DEBIT, "100.00"),
                ],
            )

    def test_amounts_are_quantised_to_cents(self) -> None:
        """
        Without normalisation, 100 and 100.00 compare unequal and a balanced
        transaction can fail its own check.
        """
        entry = _entry("t6", "CUSTOMER:COOP:111", EntryDirection.DEBIT, "100")
        assert entry.amount == Decimal("100.00")
        assert str(entry.amount) == "100.00"


# ── Posting ───────────────────────────────────────────────────────────────────


class TestPosting:
    def test_settled_payment_balances_to_zero(self, ledger: LedgerService) -> None:
        quote = FeeQuote(
            customer_fee=Decimal("2.50"),
            eupi_revenue=Decimal("1.00"),
            transaction_type=TransactionType.INTRA_BANK,
            rule_id="r",
            rule_version=1,
            bank_id="COOP",
        )
        txn = ledger.record_settled_payment(
            payment_id="pay_1",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("2500.00"),
            currency="ETB",
            fee_quote=quote,
        )

        assert txn is not None
        assert len(txn.entries) == 4  # 2 principal + 2 fee
        assert sum(e.signed_amount for e in txn.entries) == Decimal("0")

    def test_posting_is_idempotent(self, ledger: LedgerService) -> None:
        """A replayed bank callback must not double-post."""
        args = dict(
            payment_id="pay_2",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="CBE",
            creditor_account_number="1000222",
            amount=Decimal("500.00"),
            currency="ETB",
        )
        first = ledger.record_settled_payment(**args)
        second = ledger.record_settled_payment(**args)

        assert first is not None
        assert second is None, "Second post should be a no-op, not a duplicate"
        assert len(ledger.get_payment_entries("pay_2")) == 2

    def test_principal_moves_between_the_right_accounts(self, ledger: LedgerService) -> None:
        ledger.record_settled_payment(
            payment_id="pay_3",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="CBE",
            creditor_account_number="1000222",
            amount=Decimal("750.00"),
            currency="ETB",
        )

        debtor = LedgerAccount.customer_ref("COOP", "1000111")
        creditor = LedgerAccount.customer_ref("CBE", "1000222")

        # Funds left the debtor (credit, negative) and arrived at the creditor.
        assert ledger.get_account_balance(debtor) == Decimal("-750.00")
        assert ledger.get_account_balance(creditor) == Decimal("750.00")

    def test_fee_books_eupi_share_not_the_whole_customer_fee(
        self, ledger: LedgerService
    ) -> None:
        """
        Under revenue share the bank keeps most of the fee. Booking the full
        customer fee as revenue would overstate income by 2.5x at the default
        40% share.
        """
        quote = FeeQuote(
            customer_fee=Decimal("10.00"),
            eupi_revenue=Decimal("4.00"),
            transaction_type=TransactionType.CROSS_BANK,
            rule_id="r",
            rule_version=1,
            bank_id="COOP",
        )
        ledger.record_settled_payment(
            payment_id="pay_4",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="CBE",
            creditor_account_number="1000222",
            amount=Decimal("1000.00"),
            currency="ETB",
            fee_quote=quote,
        )

        receivable = LedgerAccount.fee_receivable_ref("COOP")
        assert ledger.get_account_balance(receivable) == Decimal("4.00")
        assert ledger.get_account_balance(receivable) != Decimal("10.00")

    def test_zero_revenue_posts_no_fee_entries(self, ledger: LedgerService) -> None:
        quote = FeeQuote(
            customer_fee=Decimal("0.00"),
            eupi_revenue=Decimal("0.00"),
            transaction_type=TransactionType.INTRA_BANK,
            rule_id="free",
            rule_version=1,
            bank_id="COOP",
        )
        txn = ledger.record_settled_payment(
            payment_id="pay_5",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("100.00"),
            currency="ETB",
            fee_quote=quote,
        )
        assert txn is not None
        assert len(txn.entries) == 2


class TestReversal:
    def test_reversal_nets_the_original_to_zero(self, ledger: LedgerService) -> None:
        ledger.record_settled_payment(
            payment_id="pay_6",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("300.00"),
            currency="ETB",
        )
        debtor = LedgerAccount.customer_ref("COOP", "1000111")
        assert ledger.get_account_balance(debtor) == Decimal("-300.00")

        ledger.record_reversal("pay_6", reason="Bank recall")
        assert ledger.get_account_balance(debtor) == Decimal("0.00")

    def test_reversal_preserves_the_original_entries(self, ledger: LedgerService) -> None:
        """An audit trail that deletes the original is not an audit trail."""
        ledger.record_settled_payment(
            payment_id="pay_7",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("300.00"),
            currency="ETB",
        )
        ledger.record_reversal("pay_7", reason="Duplicate")

        entries = ledger.get_payment_entries("pay_7")
        assert len(entries) == 4, "Original 2 entries plus 2 reversing entries"

    def test_double_reversal_is_a_no_op(self, ledger: LedgerService) -> None:
        ledger.record_settled_payment(
            payment_id="pay_8",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("300.00"),
            currency="ETB",
        )
        assert ledger.record_reversal("pay_8", reason="First") is not None
        assert ledger.record_reversal("pay_8", reason="Second") is None

    def test_reversing_an_unknown_payment_returns_none(self, ledger: LedgerService) -> None:
        assert ledger.record_reversal("never_existed", reason="x") is None


# ── Fee pricing ───────────────────────────────────────────────────────────────


class TestFeePricing:
    def test_flat_fee(self) -> None:
        rule = FeeRule(
            rule_id="r",
            transaction_type=TransactionType.INTRA_BANK,
            fee_type=FeeType.FLAT,
            flat_fee=Decimal("2.50"),
            revenue_share_bps=4_000,
        )
        customer_fee, eupi_revenue = rule.price(Decimal("1000.00"))
        assert customer_fee == Decimal("2.50")
        assert eupi_revenue == Decimal("1.00")

    def test_percentage_fee(self) -> None:
        rule = FeeRule(
            rule_id="r",
            transaction_type=TransactionType.CROSS_BANK,
            fee_type=FeeType.PERCENTAGE,
            percentage_bps=100,  # 1%
            revenue_share_bps=5_000,
        )
        customer_fee, eupi_revenue = rule.price(Decimal("1000.00"))
        assert customer_fee == Decimal("10.00")
        assert eupi_revenue == Decimal("5.00")

    def test_hybrid_fee_with_cap(self) -> None:
        rule = FeeRule(
            rule_id="r",
            transaction_type=TransactionType.CROSS_BANK,
            fee_type=FeeType.HYBRID,
            flat_fee=Decimal("5.00"),
            percentage_bps=100,
            max_fee=Decimal("20.00"),
        )
        # 5.00 + 1% of 10_000 = 105.00, capped at 20.00
        customer_fee, _ = rule.price(Decimal("10000.00"))
        assert customer_fee == Decimal("20.00")

    def test_minimum_fee_floor(self) -> None:
        rule = FeeRule(
            rule_id="r",
            transaction_type=TransactionType.CROSS_BANK,
            fee_type=FeeType.PERCENTAGE,
            percentage_bps=10,
            min_fee=Decimal("3.00"),
        )
        customer_fee, _ = rule.price(Decimal("100.00"))  # 0.10 -> floored
        assert customer_fee == Decimal("3.00")

    def test_rounding_is_half_up(self) -> None:
        rule = FeeRule(
            rule_id="r",
            transaction_type=TransactionType.CROSS_BANK,
            fee_type=FeeType.PERCENTAGE,
            percentage_bps=1,  # 0.01%
        )
        # 0.01% of 1250.00 = 0.125 -> 0.13 half-up, not 0.12 banker's rounding
        customer_fee, _ = rule.price(Decimal("1250.00"))
        assert customer_fee == Decimal("0.13")

    def test_incoherent_rules_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_amount"):
            FeeRule(
                rule_id="r",
                transaction_type=TransactionType.INTRA_BANK,
                fee_type=FeeType.FLAT,
                flat_fee=Decimal("1.00"),
                min_amount=Decimal("100"),
                max_amount=Decimal("50"),
            )

        with pytest.raises(ValueError, match="flat_fee"):
            FeeRule(
                rule_id="r",
                transaction_type=TransactionType.INTRA_BANK,
                fee_type=FeeType.FLAT,
                flat_fee=Decimal("0"),
            )


class TestFeeResolution:
    def test_bank_specific_rule_beats_wildcard(self, fees: FeeService) -> None:
        fees.create_rule(
            FeeRule(
                rule_id="coop_special",
                bank_id="COOP",
                transaction_type=TransactionType.INTRA_BANK,
                fee_type=FeeType.FLAT,
                flat_fee=Decimal("1.00"),
            )
        )
        quote = fees.quote("COOP", TransactionType.INTRA_BANK, Decimal("500.00"))
        assert quote.rule_id == "coop_special"

        # A different bank still falls through to the wildcard default.
        other = fees.quote("CBE", TransactionType.INTRA_BANK, Decimal("500.00"))
        assert other.rule_id == "fee_default_intra_bank"

    def test_intra_bank_prices_below_cross_bank(self, fees: FeeService) -> None:
        """
        Intra-bank needs no interbank settlement, and the default pricing must
        reflect that — it is the reason intra-bank is the launch wedge.
        """
        intra = fees.quote("COOP", TransactionType.INTRA_BANK, Decimal("5000.00"))
        cross = fees.quote("COOP", TransactionType.CROSS_BANK, Decimal("5000.00"))
        assert intra.customer_fee < cross.customer_fee

    def test_missing_rule_raises_rather_than_pricing_at_zero(self, db: Database) -> None:
        """
        A silent zero fee is indistinguishable from a correctly free
        transaction, and the difference is revenue nobody notices is missing.
        """
        bare = FeeService(fee_rule_repo=FeeRuleRepository(db))
        with pytest.raises(NoApplicableFeeRuleError):
            bare.quote("COOP", TransactionType.INTRA_BANK, Decimal("100.00"))

    def test_quote_records_the_rule_version(self, fees: FeeService) -> None:
        quote = fees.quote("CBE", TransactionType.INTRA_BANK, Decimal("100.00"))
        assert quote.rule_version >= 1
        assert fees.explain(quote.rule_id, quote.rule_version) is not None

    def test_seeding_is_idempotent(self, fees: FeeService) -> None:
        assert fees.seed_defaults_if_empty() == 0


class TestFeeVersioning:
    def test_revision_does_not_reprice_history(self, fees: FeeService) -> None:
        """
        The whole point of versioning: re-running last quarter's report must
        produce last quarter's numbers, not today's prices.
        """
        original = fees.quote("CBE", TransactionType.INTRA_BANK, Decimal("1000.00"))
        original_fee = original.customer_fee

        fees.revise_rule(
            FeeRule(
                rule_id="fee_default_intra_bank",
                bank_id=ANY_BANK,
                transaction_type=TransactionType.INTRA_BANK,
                fee_type=FeeType.FLAT,
                flat_fee=Decimal("99.00"),
            )
        )

        # New payments price at the new rate...
        updated = fees.quote("CBE", TransactionType.INTRA_BANK, Decimal("1000.00"))
        assert updated.customer_fee == Decimal("99.00")
        assert updated.rule_version == original.rule_version + 1

        # ...while the version that priced the old payment is unchanged.
        historical = fees.explain(original.rule_id, original.rule_version)
        assert historical is not None
        assert historical.price(Decimal("1000.00"))[0] == original_fee

    def test_revising_an_unknown_rule_fails(self, fees: FeeService) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            fees.revise_rule(
                FeeRule(
                    rule_id="never_created",
                    transaction_type=TransactionType.INTRA_BANK,
                    fee_type=FeeType.FLAT,
                    flat_fee=Decimal("1.00"),
                )
            )

    def test_creating_a_duplicate_rule_fails(self, fees: FeeService) -> None:
        with pytest.raises(ValueError, match="already exists"):
            fees.create_rule(
                FeeRule(
                    rule_id="fee_default_intra_bank",
                    transaction_type=TransactionType.INTRA_BANK,
                    fee_type=FeeType.FLAT,
                    flat_fee=Decimal("1.00"),
                )
            )


# ── Reporting ─────────────────────────────────────────────────────────────────


class TestReconciliation:
    def test_volume_and_revenue_are_reported_separately(
        self, ledger: LedgerService
    ) -> None:
        """
        Volume is money that moved at the banks; revenue is money owed to EUPI.
        Conflating them would report a ~2500x overstatement of income here.
        """
        quote = FeeQuote(
            customer_fee=Decimal("2.50"),
            eupi_revenue=Decimal("1.00"),
            transaction_type=TransactionType.INTRA_BANK,
            rule_id="r",
            rule_version=1,
            bank_id="COOP",
        )
        ledger.record_settled_payment(
            payment_id="pay_9",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("2500.00"),
            currency="ETB",
            fee_quote=quote,
        )

        report = ledger.get_reconciliation()
        assert report["COOP"]["orchestrated_volume"] == Decimal("2500.00")
        assert report["COOP"]["accrued_revenue"] == Decimal("1.00")

    def test_volume_is_not_double_counted(self, ledger: LedgerService) -> None:
        """
        Each payment posts both a credit and a debit leg. Summing both would
        report double the value actually moved.
        """
        ledger.record_settled_payment(
            payment_id="pay_10",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("1000.00"),
            currency="ETB",
        )
        report = ledger.get_reconciliation()
        assert report["COOP"]["orchestrated_volume"] == Decimal("1000.00")

    def test_empty_ledger_reports_nothing(self, ledger: LedgerService) -> None:
        assert ledger.get_reconciliation() == {}


class TestRevenueAttribution:
    """
    Revenue must accrue against the bank that actually charged the customer.

    Regression guard: the fee was originally priced against `selected_rail`
    (the Smart Router's chosen rail), so a COOP->COOP payment booked its
    receivable against whichever unrelated bank the router happened to pick.
    Volume and revenue then landed on different banks, and no bank's invoice
    could be reconciled.
    """

    def test_receivable_follows_the_debtor_bank(self, ledger: LedgerService) -> None:
        quote = FeeQuote(
            customer_fee=Decimal("2.50"),
            eupi_revenue=Decimal("1.00"),
            transaction_type=TransactionType.INTRA_BANK,
            rule_id="r",
            rule_version=1,
            bank_id="COOP",  # priced against the debtor's bank
        )
        ledger.record_settled_payment(
            payment_id="pay_attr_1",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("2500.00"),
            currency="ETB",
            fee_quote=quote,
        )

        assert ledger.get_account_balance(
            LedgerAccount.fee_receivable_ref("COOP")
        ) == Decimal("1.00")
        assert ledger.get_account_balance(
            LedgerAccount.fee_receivable_ref("CBE")
        ) == Decimal("0")

    def test_volume_and_revenue_land_on_the_same_bank(
        self, ledger: LedgerService
    ) -> None:
        """
        The incoherence that exposed the bug: one bank holding all the volume
        while another holds all the revenue.
        """
        quote = FeeQuote(
            customer_fee=Decimal("2.50"),
            eupi_revenue=Decimal("1.00"),
            transaction_type=TransactionType.INTRA_BANK,
            rule_id="r",
            rule_version=1,
            bank_id="COOP",
        )
        ledger.record_settled_payment(
            payment_id="pay_attr_2",
            debtor_bank_id="COOP",
            debtor_account_number="1000111",
            creditor_bank_id="COOP",
            creditor_account_number="1000222",
            amount=Decimal("2500.00"),
            currency="ETB",
            fee_quote=quote,
        )

        report = ledger.get_reconciliation()
        assert report["COOP"]["orchestrated_volume"] > 0
        assert report["COOP"]["accrued_revenue"] > 0
        assert "CBE" not in report, "No unrelated bank should appear in this report"


class TestImmutability:
    def test_reposting_a_transaction_ref_is_refused(self, db: Database) -> None:
        repo = LedgerRepository(db)
        txn = LedgerTransaction(
            transaction_ref="fixed_ref",
            transaction_type=TransactionType.INTRA_BANK,
            entries=[
                _entry("fixed_ref", "CUSTOMER:COOP:111", EntryDirection.CREDIT, "100.00"),
                _entry("fixed_ref", "CUSTOMER:COOP:222", EntryDirection.DEBIT, "100.00"),
            ],
        )
        repo.post_transaction(txn)

        with pytest.raises(ValueError, match="already been posted"):
            repo.post_transaction(txn)

    def test_repository_exposes_no_mutation_methods(self) -> None:
        """
        Append-only is guaranteed by there being no way to do otherwise.
        A future update_entry/delete_entry would silently break auditability,
        so this asserts the absence.
        """
        forbidden = {"update_entry", "delete_entry", "update", "delete", "edit_entry"}
        exposed = {m for m in dir(LedgerRepository) if not m.startswith("_")}
        assert not (forbidden & exposed), (
            f"Ledger repository exposes mutation methods: {forbidden & exposed}"
        )
