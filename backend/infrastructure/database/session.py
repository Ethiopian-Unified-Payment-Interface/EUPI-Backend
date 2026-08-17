"""
Database Session Management
===========================
Layer: 🔴 LAYER 3 — Infrastructure / Database

One engine, one connection pool, one place that knows how to talk to the
database.

Why this exists
---------------
Every repository used to construct its own `create_engine(...)` and call
`Base.metadata.create_all()` in its constructor. With thirteen repositories that
meant thirteen connection pools against the same database, schema creation as an
import side effect, and no way to run two repositories inside one transaction —
so a payment and its ledger entries could not commit atomically no matter how
the calling code was written.

It also made the SQLite→Postgres move impossible to do in one place: the
connect arguments differ, and thirteen call sites each had their own copy.

Dialect differences
-------------------
SQLite needs `check_same_thread=False` because FastAPI serves requests from a
thread pool, and it ignores pool sizing because it is a file, not a server.
Postgres needs neither and wants real pool configuration. Both are handled here
so no caller has to care which one is behind the URL.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.infrastructure.database.models import Base

logger = logging.getLogger(__name__)


class Database:
    """
    Owns the engine and hands out sessions.

    Construct exactly one of these per process, in the composition root, and
    inject it into every repository.
    """

    def __init__(self, url: str, echo: bool = False) -> None:
        """
        Args:
            url:  SQLAlchemy connection URL.
            echo: Log every statement. Useful in tests, far too noisy for a
                  running server.
        """
        self._url = url
        self._engine = create_engine(url, echo=echo, **self._engine_options(url))
        self._session_factory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            # Objects stay usable after commit. Without this, reading an
            # attribute post-commit triggers a refresh against a closed
            # session and raises DetachedInstanceError.
            expire_on_commit=False,
        )
        logger.info("Database initialised (%s)", self.dialect)

    @staticmethod
    def _engine_options(url: str) -> dict[str, Any]:
        """Connection options appropriate to the dialect in the URL."""
        if url.startswith("sqlite"):
            return {
                # FastAPI serves from a thread pool; SQLite otherwise refuses
                # a connection used from a thread other than its creator.
                "connect_args": {"check_same_thread": False},
            }

        return {
            # Verify a connection before handing it out. Without this, a
            # connection killed while idle — a Postgres restart, an idle
            # timeout, a network blip — surfaces as a failed request instead
            # of being transparently replaced.
            "pool_pre_ping": True,
            "pool_size": 10,
            "max_overflow": 20,
            # Recycle before typical proxy and server idle timeouts.
            "pool_recycle": 1800,
        }

    @property
    def dialect(self) -> str:
        """Name of the active dialect, e.g. 'sqlite' or 'postgresql'."""
        return self._engine.dialect.name

    @property
    def engine(self) -> Engine:
        """The underlying engine. For Alembic and diagnostics only."""
        return self._engine

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        A transactional scope: commit on success, roll back on any exception.

        Because every repository shares this factory, several repositories can
        now participate in one transaction when a caller opens the session
        itself — which is what makes atomic payment-plus-ledger writes possible.
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_all(self) -> None:
        """
        Create any missing tables directly from the models.

        For tests and throwaway local databases only. Real schema changes go
        through Alembic: `create_all` cannot alter an existing table, so it
        silently does nothing when a column is added — which is exactly the
        failure that hides a missing migration until production.

        No-ops when Alembic is managing this database. Running both would let
        `create_all` materialise a table at the current model shape, leaving
        Alembic to apply migrations against a schema that already jumped
        ahead — the resulting mismatch is hard to diagnose and easy to avoid.
        """
        if self._alembic_managed():
            logger.info(
                "Schema is Alembic-managed (alembic_version present); "
                "skipping create_all. Run 'alembic upgrade head' to migrate."
            )
            return

        Base.metadata.create_all(self._engine)
        logger.info("Schema ensured via create_all (%s)", self.dialect)

    def _alembic_managed(self) -> bool:
        """True when this database carries Alembic's version table."""
        return inspect(self._engine).has_table("alembic_version")

    def dispose(self) -> None:
        """Close every pooled connection. Called on shutdown."""
        self._engine.dispose()


class RepositoryBase:
    """
    Shared base for repositories that need a session.

    Replaces the per-repository engine construction that used to sit in each
    constructor.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        """Transactional scope, delegated to the shared engine."""
        with self._db.session() as session:
            yield session
