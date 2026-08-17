"""Prevent duplicate linked accounts

Adds a unique constraint on (username, bank_id, account_number).

Nothing previously stopped the same bank account being linked to one profile
repeatedly, and the effects were not cosmetic:

  * The aggregated balance sums every linked account, so a duplicate
    double-counted the money and showed the user a balance they do not have.
  * Default sending/receiving resolution returns the first matching row. Two
    rows for one account could carry conflicting default flags, making the
    account used for a transfer ambiguous.

Existing duplicates are collapsed before the constraint is applied, keeping the
earliest row and merging the default flags onto it — dropping a row that held
`is_default_sending` would otherwise leave the user with no default sender and
break their transfers.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8a52f7b3d41"
down_revision: Union[str, Sequence[str], None] = "b7d41e9c2a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    # Find every (user, bank, account) with more than one row.
    duplicates = connection.execute(
        sa.text(
            """
            SELECT username, bank_id, account_number
            FROM linked_accounts
            GROUP BY username, bank_id, account_number
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    for username, bank_id, account_number in duplicates:
        rows = connection.execute(
            sa.text(
                """
                SELECT link_id, is_default_sending, is_default_receiving
                FROM linked_accounts
                WHERE username = :username
                  AND bank_id = :bank_id
                  AND account_number = :account_number
                ORDER BY linked_at ASC
                """
            ),
            {
                "username": username,
                "bank_id": bank_id,
                "account_number": account_number,
            },
        ).fetchall()

        keeper = rows[0]
        # Merge the flags upward: if any duplicate was a default, the surviving
        # row inherits it, so no user loses a default they had set.
        keep_sending = any(bool(r[1]) for r in rows)
        keep_receiving = any(bool(r[2]) for r in rows)

        connection.execute(
            sa.text(
                """
                UPDATE linked_accounts
                SET is_default_sending = :sending, is_default_receiving = :receiving
                WHERE link_id = :link_id
                """
            ),
            {"sending": keep_sending, "receiving": keep_receiving, "link_id": keeper[0]},
        )

        for row in rows[1:]:
            connection.execute(
                sa.text("DELETE FROM linked_accounts WHERE link_id = :link_id"),
                {"link_id": row[0]},
            )

    with op.batch_alter_table("linked_accounts", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_linked_account", ["username", "bank_id", "account_number"]
        )


def downgrade() -> None:
    # Only the constraint is reversible. The collapsed duplicate rows are not
    # restored: they were double-counting a balance, and recreating them would
    # reintroduce a wrong figure on a user's dashboard.
    with op.batch_alter_table("linked_accounts", schema=None) as batch_op:
        batch_op.drop_constraint("uq_linked_account", type_="unique")
