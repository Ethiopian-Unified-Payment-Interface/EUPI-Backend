"""
Simulated core banking tests.

These cover the properties that make a sandbox transfer a real movement rather
than a returned string: money leaves one account, arrives at another, and the
total never changes. A failure here means the platform can report a payment as
sent while no balance moved — which is the exact defect this module exists to
remove — so treat it as a release blocker.

Run:  py -m pytest tests/test_simulated_cbs.py -v
"""

from __future__ import annotations

import os
import tempfile
import threading
from decimal import Decimal
from pathlib import Path

import pytest

# Isolated DB per session, and DEBUG on so config validation stays permissive.
_TEST_DB = Path(tempfile.gettempdir()) / "eupi_sim_cbs_tests.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB.as_posix()}")
os.environ.setdefault("DEBUG", "true")

from backend.application.ports.bank_port import (  # noqa: E402
    AccountNotFoundError,
    DuplicateTransferError,
    InactiveAccountError,
    InsufficientFundsError,
)
from backend.domain.models.account import BankID  # noqa: E402
from backend.infrastructure.adapters.banks.cbe_cbs import CBECBSAdapter  # noqa: E402
from backend.infrastructure.adapters.banks.coop_cbs import CoopCBSAdapter  # noqa: E402
from backend.infrastructure.adapters.banks.simulation import catalogue  # noqa: E402
from backend.infrastructure.adapters.banks.simulation.engine import (  # noqa: E402
    FEE_INCOME_ACCOUNT,
    ORDER_POSTED,
    ORDER_REVERSED,
    ORDER_SETTLED,
    SimulatedCoreBankingEngine,
)
from backend.infrastructure.database.models import (  # noqa: E402
    SimulatedTransferOrderRecord,
)
from backend.infrastructure.database.session import Database  # noqa: E402

# Two accounts held by different people, at different banks. Both are in the
# catalogue, so both exist once the engine is provisioned.
PAYER = "1000111222333"      # Abebe
PAYEE = "1000987654321"      # Selamawit


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """A fresh SQLite database per test, so no test sees another's balances."""
    database = Database(url=f"sqlite:///{(tmp_path / 'sim.db').as_posix()}")
    database.create_all()
    return database


@pytest.fixture()
def engine(db: Database) -> SimulatedCoreBankingEngine:
    """A provisioned simulator that settles immediately when asked."""
    cbs = SimulatedCoreBankingEngine(db, settlement_delay_seconds=0)
    cbs.provision()
    return cbs


def order_status(db: Database, end_to_end_id: str) -> str:
    """Read one order's lifecycle state straight from the bank's table."""
    with db.session() as session:
        record = session.get(SimulatedTransferOrderRecord, end_to_end_id)
        assert record is not None, f"No order for '{end_to_end_id}'"
        return record.status


# ── Provisioning ──────────────────────────────────────────────────────────────


class TestProvisioning:
    def test_catalogue_accounts_exist_and_others_do_not(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        Provisioning is strict. An account number nobody opened does not exist,
        which is what makes account linking a real check rather than a
        formality that always passes.
        """
        assert engine.get_account(BankID.CBE, PAYER).account_number == PAYER

        with pytest.raises(AccountNotFoundError):
            engine.get_account(BankID.CBE, "9999999999999")

    def test_reprovisioning_does_not_reset_balances(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        Every boot calls `provision()`. If that reset balances, a restart would
        silently undo every transfer made since the last one.
        """
        engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.CBE,
            creditor_account=PAYEE,
            amount=Decimal("100.00"),
            currency="ETB",
            end_to_end_id="E2E-REPROVISION",
            order_reference="CBE-ORD-1",
        )
        after_transfer = engine.get_account(BankID.CBE, PAYER).available_balance

        assert engine.provision() == 0
        assert engine.get_account(BankID.CBE, PAYER).available_balance == after_transfer

    def test_opening_balance_is_the_same_in_every_process(self) -> None:
        """
        Seeds come from a keyed digest, not `hash()`, which Python salts per
        process. The old seeding gave an account a different balance after
        every restart and a different one in each uvicorn worker.
        """
        first = catalogue.seed_for(BankID.CBE, PAYER)
        second = catalogue.seed_for(BankID.CBE, PAYER)
        assert first is not None and second is not None
        assert first.opening_balance == second.opening_balance
        # Pinned literally: a change here means every demo balance moved.
        assert first.opening_balance == Decimal("72027.62")


# ── Movement ──────────────────────────────────────────────────────────────────


class TestTransfer:
    def test_money_leaves_one_account_and_arrives_at_the_other(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        payer_before = engine.get_account(BankID.CBE, PAYER).available_balance
        payee_before = engine.get_account(BankID.COOP, PAYEE).available_balance

        engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("500.25"),
            currency="ETB",
            end_to_end_id="E2E-MOVES",
            order_reference="CBE-ORD-MOVES",
            fee_amount=Decimal("5.50"),
        )

        payer_after = engine.get_account(BankID.CBE, PAYER).available_balance
        payee_after = engine.get_account(BankID.COOP, PAYEE).available_balance

        # The payer funds the fee; the beneficiary receives the principal.
        assert payer_before - payer_after == Decimal("505.75")
        assert payee_after - payee_before == Decimal("500.25")

    def test_the_fee_is_collected_rather_than_destroyed(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        The fee lands in the debtor bank's income book. Letting it vanish would
        make the conservation check below meaningless — the one assertion that
        detects a half-applied transfer.
        """
        before = engine.total_balance()

        engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("1000.00"),
            currency="ETB",
            end_to_end_id="E2E-FEE",
            order_reference="CBE-ORD-FEE",
            fee_amount=Decimal("12.00"),
        )

        assert engine.total_balance() == before

    def test_the_statement_shows_the_movement(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        Statements are the account's own journal now, not invented history. A
        transfer must therefore be visible on both sides.
        """
        from datetime import datetime, timedelta, timezone

        engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("250.00"),
            currency="ETB",
            end_to_end_id="E2E-STATEMENT",
            order_reference="CBE-ORD-STATEMENT",
        )

        now = datetime.now(tz=timezone.utc)
        window = (now - timedelta(days=1), now + timedelta(days=1))

        payer_entries = engine.get_entries(BankID.CBE, PAYER, *window)
        payee_entries = engine.get_entries(BankID.COOP, PAYEE, *window)

        debit = next(e for e in payer_entries if e.end_to_end_id == "E2E-STATEMENT")
        credit = next(e for e in payee_entries if e.end_to_end_id == "E2E-STATEMENT")

        assert debit.direction == "DEBIT"
        assert credit.direction == "CREDIT"
        assert debit.amount == credit.amount == Decimal("250.00")
        # `balance_after` must agree with the account row, or a statement and a
        # balance could tell a customer two different stories.
        assert credit.balance_after == engine.get_account(
            BankID.COOP, PAYEE
        ).available_balance

    def test_a_bank_fee_account_is_not_addressable(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """A bank's internal book is not a destination a caller may pay into."""
        with pytest.raises(AccountNotFoundError):
            engine.transfer(
                debtor_bank_id=BankID.CBE,
                debtor_account=PAYER,
                creditor_bank_id=BankID.CBE,
                creditor_account=FEE_INCOME_ACCOUNT,
                amount=Decimal("10.00"),
                currency="ETB",
                end_to_end_id="E2E-INTERNAL",
                order_reference="CBE-ORD-INTERNAL",
            )


class TestRefusals:
    def test_insufficient_funds_moves_nothing(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        payer_before = engine.get_account(BankID.CBE, PAYER).available_balance
        payee_before = engine.get_account(BankID.COOP, PAYEE).available_balance

        with pytest.raises(InsufficientFundsError):
            engine.transfer(
                debtor_bank_id=BankID.CBE,
                debtor_account=PAYER,
                creditor_bank_id=BankID.COOP,
                creditor_account=PAYEE,
                amount=payer_before + Decimal("1.00"),
                currency="ETB",
                end_to_end_id="E2E-BROKE",
                order_reference="CBE-ORD-BROKE",
            )

        assert engine.get_account(BankID.CBE, PAYER).available_balance == payer_before
        assert engine.get_account(BankID.COOP, PAYEE).available_balance == payee_before

    def test_the_fee_counts_towards_affordability(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        A transfer the payer can afford only by ignoring the fee must be
        refused. Checking the principal alone would let a balance go negative.
        """
        balance = engine.get_account(BankID.CBE, PAYER).available_balance

        with pytest.raises(InsufficientFundsError):
            engine.transfer(
                debtor_bank_id=BankID.CBE,
                debtor_account=PAYER,
                creditor_bank_id=BankID.COOP,
                creditor_account=PAYEE,
                amount=balance,
                currency="ETB",
                end_to_end_id="E2E-FEE-TIPS-IT",
                order_reference="CBE-ORD-FEE-TIPS-IT",
                fee_amount=Decimal("0.01"),
            )

    def test_an_unknown_beneficiary_is_refused(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        with pytest.raises(AccountNotFoundError):
            engine.transfer(
                debtor_bank_id=BankID.CBE,
                debtor_account=PAYER,
                creditor_bank_id=BankID.COOP,
                creditor_account="9999999999999",
                amount=Decimal("10.00"),
                currency="ETB",
                end_to_end_id="E2E-NOBODY",
                order_reference="CBE-ORD-NOBODY",
            )

    def test_a_closed_account_cannot_transact(
        self, db: Database, engine: SimulatedCoreBankingEngine
    ) -> None:
        from backend.infrastructure.database.models import SimulatedBankAccountRecord

        with db.session() as session:
            record = session.get(
                SimulatedBankAccountRecord, (BankID.CBE.value, PAYER)
            )
            record.is_active = False

        with pytest.raises(InactiveAccountError):
            engine.transfer(
                debtor_bank_id=BankID.CBE,
                debtor_account=PAYER,
                creditor_bank_id=BankID.COOP,
                creditor_account=PAYEE,
                amount=Decimal("10.00"),
                currency="ETB",
                end_to_end_id="E2E-CLOSED",
                order_reference="CBE-ORD-CLOSED",
            )


class TestIdempotency:
    def test_replaying_a_reference_does_not_pay_twice(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        A retried submission is normal: a timeout tells the caller nothing
        about whether the bank acted. The second attempt must be a no-op that
        returns the first attempt's reference.
        """
        first = engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("300.00"),
            currency="ETB",
            end_to_end_id="E2E-RETRY",
            order_reference="CBE-ORD-FIRST",
        )
        after_first = engine.get_account(BankID.CBE, PAYER).available_balance

        second = engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("300.00"),
            currency="ETB",
            end_to_end_id="E2E-RETRY",
            order_reference="CBE-ORD-SECOND",
        )

        assert second == first == "CBE-ORD-FIRST"
        assert engine.get_account(BankID.CBE, PAYER).available_balance == after_first

    def test_reusing_a_reference_for_a_different_transfer_is_refused(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        Returning the original silently would confirm a payment that never
        happened; moving the money would break the idempotency the caller was
        relying on. Neither is acceptable, so this is an error.
        """
        engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("300.00"),
            currency="ETB",
            end_to_end_id="E2E-REUSED",
            order_reference="CBE-ORD-REUSED",
        )

        with pytest.raises(DuplicateTransferError):
            engine.transfer(
                debtor_bank_id=BankID.CBE,
                debtor_account=PAYER,
                creditor_bank_id=BankID.COOP,
                creditor_account=PAYEE,
                amount=Decimal("999.00"),
                currency="ETB",
                end_to_end_id="E2E-REUSED",
                order_reference="CBE-ORD-REUSED-2",
            )


class TestConcurrency:
    def test_parallel_transfers_cannot_overdraw(self, db: Database) -> None:
        """
        The load-bearing test for double spending.

        Twenty threads each try to send a fifth of the balance at the same
        moment. At most five can succeed. The advisory check in the transfer
        service cannot enforce this — it reads a balance and then acts on a
        stale snapshot — so the guarantee has to come from the engine holding a
        lock across the read and the write.
        """
        cbs = SimulatedCoreBankingEngine(db, settlement_delay_seconds=0)
        cbs.provision()

        opening = cbs.get_account(BankID.CBE, PAYER).available_balance
        total_before = cbs.total_balance()
        slice_ = (opening / 5).quantize(Decimal("0.01"))

        barrier = threading.Barrier(20)
        outcomes: list[bool] = []
        lock = threading.Lock()

        def send(index: int) -> None:
            barrier.wait()
            try:
                cbs.transfer(
                    debtor_bank_id=BankID.CBE,
                    debtor_account=PAYER,
                    creditor_bank_id=BankID.COOP,
                    creditor_account=PAYEE,
                    amount=slice_,
                    currency="ETB",
                    end_to_end_id=f"E2E-RACE-{index}",
                    order_reference=f"CBE-ORD-RACE-{index}",
                )
            except (InsufficientFundsError, DuplicateTransferError):
                with lock:
                    outcomes.append(False)
            else:
                with lock:
                    outcomes.append(True)

        threads = [threading.Thread(target=send, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sum(outcomes) <= 5, "More transfers succeeded than the balance allowed"
        assert cbs.get_account(BankID.CBE, PAYER).available_balance >= Decimal("0.00")
        assert cbs.total_balance() == total_before


class TestSettlementLifecycle:
    def test_a_posted_order_becomes_due_and_can_be_settled(
        self, db: Database, engine: SimulatedCoreBankingEngine
    ) -> None:
        engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("75.00"),
            currency="ETB",
            end_to_end_id="E2E-SETTLE",
            order_reference="CBE-ORD-SETTLE",
        )
        assert order_status(db, "E2E-SETTLE") == ORDER_POSTED

        due = engine.claim_due_orders()
        assert [order.end_to_end_id for order in due] == ["E2E-SETTLE"]
        assert due[0].attempts == 1

        engine.mark_settled("E2E-SETTLE")
        assert order_status(db, "E2E-SETTLE") == ORDER_SETTLED
        assert engine.claim_due_orders() == []

    def test_an_order_is_not_due_before_its_delay_elapses(self, db: Database) -> None:
        """
        Settlement is asynchronous at a real bank. A sandbox that confirmed
        instantly would hide every bug that only exists while a payment is in
        flight — which is the class of bug that left payments stuck.
        """
        cbs = SimulatedCoreBankingEngine(db, settlement_delay_seconds=3600)
        cbs.provision()
        cbs.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("75.00"),
            currency="ETB",
            end_to_end_id="E2E-NOT-YET",
            order_reference="CBE-ORD-NOT-YET",
        )

        assert cbs.claim_due_orders() == []

    def test_reversal_returns_the_money_including_the_fee(
        self, db: Database, engine: SimulatedCoreBankingEngine
    ) -> None:
        payer_before = engine.get_account(BankID.CBE, PAYER).available_balance
        payee_before = engine.get_account(BankID.COOP, PAYEE).available_balance

        engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("400.00"),
            currency="ETB",
            end_to_end_id="E2E-REVERSE",
            order_reference="CBE-ORD-REVERSE",
            fee_amount=Decimal("6.00"),
        )

        assert engine.reverse("E2E-REVERSE", "Bank rejected it.") is True

        assert engine.get_account(BankID.CBE, PAYER).available_balance == payer_before
        assert engine.get_account(BankID.COOP, PAYEE).available_balance == payee_before
        assert order_status(db, "E2E-REVERSE") == ORDER_REVERSED

    def test_a_settled_transfer_cannot_be_reversed(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        Reversing a confirmed transfer would move money a second time on the
        strength of a stale message. The caller is told nothing happened.
        """
        engine.transfer(
            debtor_bank_id=BankID.CBE,
            debtor_account=PAYER,
            creditor_bank_id=BankID.COOP,
            creditor_account=PAYEE,
            amount=Decimal("50.00"),
            currency="ETB",
            end_to_end_id="E2E-DONE",
            order_reference="CBE-ORD-DONE",
        )
        engine.mark_settled("E2E-DONE")
        balance = engine.get_account(BankID.CBE, PAYER).available_balance

        assert engine.reverse("E2E-DONE", "Too late.") is False
        assert engine.get_account(BankID.CBE, PAYER).available_balance == balance


class TestAdaptersShareTheBooks:
    def test_a_transfer_through_one_adapter_is_visible_through_another(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        The six adapters are separate banks inside one simulator. That shared
        core is what lets a cross-bank transfer debit and credit atomically
        instead of each rail keeping its own unreconciled fiction.
        """
        cbe = CBECBSAdapter(engine)
        coop = CoopCBSAdapter(engine)

        payee_before = coop.get_balance(PAYEE).available_balance

        reference = cbe.transfer(
            debtor_account=PAYER,
            creditor_account=PAYEE,
            creditor_bank_id=BankID.COOP,
            amount=Decimal("125.00"),
            currency="ETB",
            end_to_end_id="E2E-ADAPTERS",
        )

        assert reference.startswith(f"{CBECBSAdapter._ORDER_PREFIX}-")
        assert coop.get_balance(PAYEE).available_balance - payee_before == Decimal(
            "125.00"
        )

    def test_each_order_reference_is_unique(
        self, engine: SimulatedCoreBankingEngine
    ) -> None:
        """
        References were once derived from the tail of the caller's reference,
        so two transfers between the same pair of users collided on the order
        table's unique index and the second was rejected as a duplicate.
        """
        cbe = CBECBSAdapter(engine)
        references = {
            cbe.transfer(
                debtor_account=PAYER,
                creditor_account=PAYEE,
                creditor_bank_id=BankID.CBE,
                amount=Decimal("10.00"),
                currency="ETB",
                end_to_end_id=f"E2E-UNIQUE-{index}-abebe-selam",
            )
            for index in range(5)
        }
        assert len(references) == 5
