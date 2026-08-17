"""Encrypt national ID at rest

Replaces the plaintext, indexed, unique `users.fin` column with three columns:

    fin_encrypted   Fernet ciphertext — the only place the value survives.
    fin_blind_index Keyed HMAC, indexed and unique, so "one account per
                    national ID" can be enforced without decrypting anything.
    fin_last4       Masked suffix, so the admin analytics repository can render
                    a mask with no decryption capability at all.

Why a hand-written migration
----------------------------
Autogenerate can add and drop columns but cannot encrypt. Existing rows hold
plaintext Fayda numbers that must be encrypted with the configured key before
the old column is dropped, and that backfill has to happen inside this
migration — between the add and the drop — or the values are lost.

Irreversibility
---------------
`downgrade()` decrypts back to plaintext, which only works while the same
FIN_ENCRYPTION_KEY is configured. It exists so a bad deploy can be rolled back
promptly; it is not a way to recover data after a key change.

Run with the same FIN_ENCRYPTION_KEY and FIN_BLIND_INDEX_PEPPER the
application uses. A mismatch produces rows that cannot be read back, and the
migration refuses to run rather than write them.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d41e9c2a10"
down_revision: Union[str, Sequence[str], None] = "ae32cbf33580"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _vault():
    """
    Build the vault from application settings.

    Imported inside the function so that merely loading this migration module —
    which Alembic does for every revision on every command — does not require
    the encryption keys to be present.
    """
    from backend.infrastructure.auth.identity_vault import FernetIdentityVault

    return FernetIdentityVault()


def upgrade() -> None:
    vault = _vault()
    connection = op.get_bind()

    # 1. Add the new columns as nullable so existing rows survive the ALTER.
    #    They are tightened to NOT NULL after the backfill.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fin_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("fin_blind_index", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("fin_last4", sa.String(length=4), nullable=True))

    # 2. Encrypt every existing plaintext FIN.
    rows = connection.execute(sa.text("SELECT username, fin FROM users")).fetchall()
    for username, fin in rows:
        if fin is None:
            continue
        connection.execute(
            sa.text(
                "UPDATE users SET fin_encrypted = :enc, fin_blind_index = :idx, "
                "fin_last4 = :last4 WHERE username = :username"
            ),
            {
                "enc": vault.encrypt(fin),
                "idx": vault.blind_index(fin),
                "last4": fin[-4:],
                "username": username,
            },
        )

    # 3. Verify before destroying the source. Dropping the plaintext column
    #    while a single row failed to encrypt would lose that national ID
    #    permanently, and there is no way to reconstruct it.
    unmigrated = connection.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE fin_encrypted IS NULL")
    ).scalar()
    if unmigrated:
        raise RuntimeError(
            f"{unmigrated} user row(s) were not encrypted. Refusing to drop the "
            f"plaintext column — investigate before re-running."
        )

    # 4. Drop the plaintext column and its index, then enforce NOT NULL.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_fin"))
        batch_op.drop_column("fin")
        batch_op.alter_column("fin_encrypted", nullable=False)
        batch_op.alter_column("fin_blind_index", nullable=False)
        batch_op.alter_column("fin_last4", nullable=False)
        batch_op.create_index(
            batch_op.f("ix_users_fin_blind_index"), ["fin_blind_index"], unique=True
        )


def downgrade() -> None:
    vault = _vault()
    connection = op.get_bind()

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fin", sa.String(length=14), nullable=True))

    rows = connection.execute(
        sa.text("SELECT username, fin_encrypted FROM users")
    ).fetchall()
    for username, ciphertext in rows:
        if ciphertext is None:
            continue
        connection.execute(
            sa.text("UPDATE users SET fin = :fin WHERE username = :username"),
            {"fin": vault.decrypt(ciphertext), "username": username},
        )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_fin_blind_index"))
        batch_op.drop_column("fin_last4")
        batch_op.drop_column("fin_blind_index")
        batch_op.drop_column("fin_encrypted")
        batch_op.alter_column("fin", nullable=False)
        batch_op.create_index(batch_op.f("ix_users_fin"), ["fin"], unique=True)
