"""
Account Link Repository
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: Concrete implementation of the AccountLinkRepositoryPort abstract interface.
"""

from __future__ import annotations

from datetime import timezone
from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session

from backend.application.ports.account_link_repository_port import (
    AccountLinkRepositoryPort,
)
from backend.domain.models.account import BankID
from backend.domain.models.linked_account import AccountDirection, LinkedAccount
from backend.infrastructure.database.session import RepositoryBase
from backend.infrastructure.database.models import Base, LinkedAccountRecord


class AccountLinkRepository(RepositoryBase, AccountLinkRepositoryPort):
    """
    Relational implementation of AccountLinkRepositoryPort.
    
    Provides CRUD operations for linked bank accounts persisted
    in the `linked_accounts` table.
    """



    def add_link(self, link: LinkedAccount) -> None:
        record = LinkedAccountRecord(
            link_id=link.link_id,
            username=link.username,
            bank_id=link.bank_id.value,
            account_number=link.account_number,
            account_name=link.account_name,
            is_default_sending=link.is_default_sending,
            is_default_receiving=link.is_default_receiving,
            linked_at=link.linked_at.replace(tzinfo=None),
        )
        with self._session() as session:
            session.add(record)

    def list_for_user(self, username: str) -> list[LinkedAccount]:
        with self._session() as session:
            records = session.query(LinkedAccountRecord).filter(
                LinkedAccountRecord.username == username
            ).all()
            return [self._to_domain(r) for r in records]

    def get_link(self, link_id: str) -> LinkedAccount | None:
        with self._session() as session:
            record = session.get(LinkedAccountRecord, link_id)
            return self._to_domain(record) if record else None

    def set_default(self, link_id: str, direction: AccountDirection) -> None:
        with self._session() as session:
            record = session.get(LinkedAccountRecord, link_id)
            if record is None:
                raise ValueError(f"Linked account '{link_id}' not found.")
            
            # Unset previous default for this user+direction
            if direction == AccountDirection.SENDING:
                session.query(LinkedAccountRecord).filter(
                    LinkedAccountRecord.username == record.username,
                    LinkedAccountRecord.is_default_sending == True,  # noqa: E712
                ).update({"is_default_sending": False})
                record.is_default_sending = True
            else:
                session.query(LinkedAccountRecord).filter(
                    LinkedAccountRecord.username == record.username,
                    LinkedAccountRecord.is_default_receiving == True,  # noqa: E712
                ).update({"is_default_receiving": False})
                record.is_default_receiving = True

    def remove_link(self, link_id: str) -> bool:
        with self._session() as session:
            record = session.get(LinkedAccountRecord, link_id)
            if record is None:
                return False
            session.delete(record)
            return True

    @staticmethod
    def _to_domain(record: LinkedAccountRecord) -> LinkedAccount:
        return LinkedAccount(
            link_id=record.link_id,
            username=record.username,
            bank_id=BankID(record.bank_id),
            account_number=record.account_number,
            account_name=record.account_name,
            is_default_sending=record.is_default_sending,
            is_default_receiving=record.is_default_receiving,
            linked_at=record.linked_at.replace(tzinfo=timezone.utc),
        )
