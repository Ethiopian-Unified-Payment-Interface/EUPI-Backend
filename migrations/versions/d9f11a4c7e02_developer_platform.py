"""Developer platform migration

Revision ID: d9f11a4c7e02
Revises: c8a52f7b3d41
Create Date: 2026-08-18 11:45:00.000000

Adds developer platform schema elements:
  - developer_apps columns: client_secret_hash, webhook_url, redirect_uris, rate_limit_per_min, etc.
  - payments columns: app_id, request_fingerprint, composite unique constraint uq_payment_app_e2e
  - new table: authorization_codes
  - new table: rate_limit_counters
  - webhook_events columns: app_id, event_type, next_attempt_at
  - merchants columns: password_hash, contact_name, is_active
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9f11a4c7e02"
down_revision: Union[str, Sequence[str], None] = "c8a52f7b3d41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    # 1. developer_apps columns
    op.add_column("developer_apps", sa.Column("client_secret_hash", sa.String(255), nullable=True))
    op.add_column("developer_apps", sa.Column("secret_created_at", sa.DateTime(), nullable=True))
    op.add_column("developer_apps", sa.Column("secret_rotated_at", sa.DateTime(), nullable=True))
    op.add_column("developer_apps", sa.Column("webhook_url", sa.String(512), nullable=True))
    op.add_column("developer_apps", sa.Column("webhook_secret", sa.Text(), nullable=True))
    op.add_column("developer_apps", sa.Column("redirect_uris", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("developer_apps", sa.Column("rate_limit_per_min", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("developer_apps", sa.Column("suspended_reason", sa.Text(), nullable=True))

    # 2. payments columns & composite idempotency constraint
    op.add_column("payments", sa.Column("app_id", sa.String(64), nullable=True))
    op.create_index("ix_payments_app_id", "payments", ["app_id"])
    op.add_column("payments", sa.Column("request_fingerprint", sa.String(64), nullable=True))

    # Handle Postgres vs SQLite unique constraint on end_to_end_id
    if connection.dialect.name == "postgresql":
        op.execute("ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_end_to_end_id_key")
        op.execute("DROP INDEX IF EXISTS ix_payments_end_to_end_id")
    op.create_unique_constraint("uq_payment_app_e2e", "payments", ["app_id", "end_to_end_id"])

    # 3. authorization_codes table
    op.create_table(
        "authorization_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.String(512), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("code_challenge_method", sa.String(8), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_authorization_codes_app_id", "authorization_codes", ["app_id"])

    # 4. rate_limit_counters table
    op.create_table(
        "rate_limit_counters",
        sa.Column("client_id", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(), primary_key=True),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # 5. webhook_events columns
    op.add_column("webhook_events", sa.Column("app_id", sa.String(64), nullable=True))
    op.create_index("ix_webhook_events_app_id", "webhook_events", ["app_id"])
    op.add_column("webhook_events", sa.Column("event_type", sa.String(64), nullable=False, server_default="payment.settled"))
    op.add_column("webhook_events", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
    op.create_index("ix_webhook_events_next_attempt_at", "webhook_events", ["next_attempt_at"])

    # 6. merchants columns
    op.add_column("merchants", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column("merchants", sa.Column("contact_name", sa.String(100), nullable=True))
    op.add_column("merchants", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    connection = op.get_bind()

    # 6. merchants
    op.drop_column("merchants", "is_active")
    op.drop_column("merchants", "contact_name")
    op.drop_column("merchants", "password_hash")

    # 5. webhook_events
    op.drop_index("ix_webhook_events_next_attempt_at", table_name="webhook_events")
    op.drop_column("webhook_events", "next_attempt_at")
    op.drop_column("webhook_events", "event_type")
    op.drop_index("ix_webhook_events_app_id", table_name="webhook_events")
    op.drop_column("webhook_events", "app_id")

    # 4. rate_limit_counters
    op.drop_table("rate_limit_counters")

    # 3. authorization_codes
    op.drop_index("ix_authorization_codes_app_id", table_name="authorization_codes")
    op.drop_table("authorization_codes")

    # 2. payments
    op.drop_constraint("uq_payment_app_e2e", "payments", type_="unique")
    if connection.dialect.name == "postgresql":
        op.create_unique_constraint("payments_end_to_end_id_key", "payments", ["end_to_end_id"])
    op.drop_column("payments", "request_fingerprint")
    op.drop_index("ix_payments_app_id", table_name="payments")
    op.drop_column("payments", "app_id")

    # 1. developer_apps
    op.drop_column("developer_apps", "suspended_reason")
    op.drop_column("developer_apps", "rate_limit_per_min")
    op.drop_column("developer_apps", "redirect_uris")
    op.drop_column("developer_apps", "webhook_secret")
    op.drop_column("developer_apps", "webhook_url")
    op.drop_column("developer_apps", "secret_rotated_at")
    op.drop_column("developer_apps", "secret_created_at")
    op.drop_column("developer_apps", "client_secret_hash")
