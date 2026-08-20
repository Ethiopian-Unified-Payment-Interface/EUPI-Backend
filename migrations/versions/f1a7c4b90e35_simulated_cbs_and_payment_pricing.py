"""Simulated core banking state, and pricing recorded on the payment

Two changes that only make sense together.

**Simulated core banking.** The bank adapters had no state: `transfer()`
formatted an order reference and returned it, and `get_balance()` invented a
figure from a seeded RNG. A P2P transfer therefore never debited or credited
anything, and the balance shown to a user could not change no matter how much
money "moved". Three tables give the simulated banks real books, so a transfer
in the sandbox does what a transfer does.

The `sim_` prefix is deliberate and load-bearing. These are the *banks'* books.
EUPI is a pass-through orchestrator that never holds customer funds, and a
balance here is a fixture, never a liability. When a real CBS is integrated the
adapter stops reading these tables.

**Pricing on the payment.** The fee is now debited alongside the principal, so
the quote that priced the debit has to survive to settlement. It used to be
re-quoted at settlement time, which meant a fee rule published between order and
settlement would make the ledger disagree with the money that actually moved.
The columns are nullable: payments created before this migration were never
priced at initiation and have nothing to backfill.

Additive throughout — no existing column is altered or dropped, so the downgrade
is a clean drop of what this added.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a7c4b90e35"
down_revision: Union[str, Sequence[str], None] = "d9f11a4c7e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Pricing recorded on the payment ──────────────────────────────────────
    with op.batch_alter_table("payments") as batch:
        batch.add_column(sa.Column("customer_fee", sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column("eupi_revenue", sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column("fee_rule_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("fee_rule_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("fee_bank_id", sa.String(20), nullable=True))

    # ── Simulated core banking ───────────────────────────────────────────────
    op.create_table(
        "sim_bank_accounts",
        sa.Column("bank_id", sa.String(20), primary_key=True),
        sa.Column("account_number", sa.String(30), primary_key=True),
        sa.Column("account_name", sa.String(100), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False, server_default="SAVINGS"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ETB"),
        sa.Column("branch_code", sa.String(20), nullable=False, server_default=""),
        sa.Column("available_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("ledger_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sim_bank_entries",
        sa.Column("entry_id", sa.String(64), primary_key=True),
        sa.Column("bank_id", sa.String(20), nullable=False),
        sa.Column("account_number", sa.String(30), nullable=False),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ETB"),
        sa.Column("balance_after", sa.Numeric(18, 2), nullable=False),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("counterparty_bank_id", sa.String(20), nullable=True),
        sa.Column("counterparty_account", sa.String(30), nullable=True),
        sa.Column("counterparty_name", sa.String(100), nullable=True),
        sa.Column("end_to_end_id", sa.String(64), nullable=True),
        sa.Column("order_reference", sa.String(128), nullable=True),
        sa.Column("narration", sa.Text(), nullable=False, server_default=""),
        sa.Column("booked_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_sim_entry_account_booked",
        "sim_bank_entries",
        ["bank_id", "account_number", "booked_at"],
    )
    op.create_index("ix_sim_entry_e2e", "sim_bank_entries", ["end_to_end_id"])

    op.create_table(
        "sim_transfer_orders",
        sa.Column("end_to_end_id", sa.String(64), primary_key=True),
        sa.Column("order_reference", sa.String(128), nullable=False, unique=True),
        sa.Column("debtor_bank_id", sa.String(20), nullable=False),
        sa.Column("debtor_account_number", sa.String(30), nullable=False),
        sa.Column("creditor_bank_id", sa.String(20), nullable=False),
        sa.Column("creditor_account_number", sa.String(30), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("fee_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ETB"),
        sa.Column("status", sa.String(20), nullable=False, server_default="POSTED"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("settle_after", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_sim_order_due", "sim_transfer_orders", ["status", "settle_after"]
    )


def downgrade() -> None:
    op.drop_index("ix_sim_order_due", table_name="sim_transfer_orders")
    op.drop_table("sim_transfer_orders")

    op.drop_index("ix_sim_entry_e2e", table_name="sim_bank_entries")
    op.drop_index("ix_sim_entry_account_booked", table_name="sim_bank_entries")
    op.drop_table("sim_bank_entries")

    op.drop_table("sim_bank_accounts")

    with op.batch_alter_table("payments") as batch:
        batch.drop_column("fee_bank_id")
        batch.drop_column("fee_rule_version")
        batch.drop_column("fee_rule_id")
        batch.drop_column("eupi_revenue")
        batch.drop_column("customer_fee")
