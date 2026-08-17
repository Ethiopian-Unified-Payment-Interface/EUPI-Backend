"""
Alembic environment.

The database URL comes from the application's own settings rather than
alembic.ini, so migrations always target the same database the app does and
there is no second place to keep in sync.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from dotenv import load_dotenv

load_dotenv()

from backend.config import settings  # noqa: E402 — must follow load_dotenv()
from backend.infrastructure.database.models import Base  # noqa: E402

# Importing models is what populates Base.metadata; autogenerate compares the
# live database against it.
target_metadata = Base.metadata

config = context.config

# Injected here rather than written into alembic.ini so the URL — which may
# carry a password — is never committed to the repository.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting, for review or manual application."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type changes, not just added/dropped columns.
            compare_type=True,
            # SQLite cannot ALTER most columns in place; batch mode rewrites
            # the table instead. Harmless on Postgres, essential for local
            # SQLite development.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
