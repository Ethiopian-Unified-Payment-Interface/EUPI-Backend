"""
SQLite User Repository
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: Concrete implementation of the UserRepositoryPort abstract interface.
"""

from __future__ import annotations

from datetime import timezone
from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from backend.application.ports.user_repository_port import UserRepositoryPort
from backend.config import settings
from backend.domain.models.user import SuperAppUser
from backend.infrastructure.database.models import Base, UserRecord


class SQLiteUserRepository(UserRepositoryPort):
    """
    SQLite-backed implementation of UserRepositoryPort.
    
    Provides CRUD operations for super app user accounts persisted
    in the `users` table.
    """

    def __init__(self, db_url: str = settings.DATABASE_URL) -> None:
        self._engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=settings.DEBUG,
        )
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine, autoflush=False)

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        """Provide a transactional scope."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_user(self, user: SuperAppUser) -> None:
        record = UserRecord(
            user_id=user.user_id,
            username=user.username,
            fin=user.fin,
            full_name=user.full_name,
            phone_number=user.phone_number,
            created_at=user.created_at.replace(tzinfo=None),
            is_active=user.is_active,
            pin_hash=user.pin_hash,
        )
        with self._session() as session:
            session.add(record)

    def get_by_id(self, user_id: str) -> SuperAppUser | None:
        with self._session() as session:
            record = session.get(UserRecord, user_id)
            return self._to_domain(record) if record else None

    def get_by_username(self, username: str) -> SuperAppUser | None:
        with self._session() as session:
            record = session.query(UserRecord).filter(
                UserRecord.username == username
            ).first()
            return self._to_domain(record) if record else None

    def get_by_fin(self, fin: str) -> SuperAppUser | None:
        with self._session() as session:
            record = session.query(UserRecord).filter(
                UserRecord.fin == fin
            ).first()
            return self._to_domain(record) if record else None

    def username_exists(self, username: str) -> bool:
        with self._session() as session:
            return session.query(UserRecord).filter(
                UserRecord.username == username
            ).count() > 0

    @staticmethod
    def _to_domain(record: UserRecord) -> SuperAppUser:
        return SuperAppUser(
            user_id=record.user_id,
            username=record.username,
            fin=record.fin,
            full_name=record.full_name,
            phone_number=record.phone_number,
            created_at=record.created_at.replace(tzinfo=timezone.utc),
            is_active=record.is_active,
            pin_hash=record.pin_hash,
        )

    def update_pin_hash(self, user_id: str, pin_hash: str) -> None:
        with self._session() as session:
            record = session.get(UserRecord, user_id)
            if record is None:
                raise ValueError(f"User '{user_id}' not found.")
            record.pin_hash = pin_hash