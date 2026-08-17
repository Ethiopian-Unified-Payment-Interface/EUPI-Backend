"""
Admin User Repository
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: Concrete implementation of the AdminUserRepositoryPort abstract interface.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator


from backend.application.ports.admin_user_repository_port import AdminUserRepositoryPort
from backend.domain.models.admin_user import AdminRole, AdminUser
from backend.infrastructure.database.session import RepositoryBase
from backend.infrastructure.database.models import AdminUserRecord, Base


class AdminUserRepository(RepositoryBase, AdminUserRepositoryPort):
    """
    Relational implementation of AdminUserRepositoryPort.

    Emails are normalised to lowercase on both write and read so that
    `Admin@Kifiya.com` and `admin@kifiya.com` cannot become two accounts.
    """



    @staticmethod
    def _normalise(email: str) -> str:
        return email.strip().lower()

    def create(self, admin: AdminUser) -> None:
        if admin.password_hash is None:
            raise ValueError("Cannot persist an admin user without a password hash.")

        email = self._normalise(admin.email)
        with self._session() as session:
            if session.get(AdminUserRecord, email) is not None:
                raise ValueError(f"An admin user already exists for '{email}'.")
            session.add(
                AdminUserRecord(
                    email=email,
                    full_name=admin.full_name,
                    role=admin.role.value,
                    is_active=admin.is_active,
                    created_at=admin.created_at.replace(tzinfo=None),
                    last_login_at=None,
                    password_hash=admin.password_hash,
                )
            )

    def get_by_email(self, email: str) -> AdminUser | None:
        with self._session() as session:
            record = session.get(AdminUserRecord, self._normalise(email))
            return self._to_domain(record) if record else None

    def count(self) -> int:
        with self._session() as session:
            return session.query(AdminUserRecord).count()

    def update_last_login(self, email: str, when: datetime) -> None:
        with self._session() as session:
            record = session.get(AdminUserRecord, self._normalise(email))
            if record is None:
                raise ValueError(f"Admin user '{email}' not found.")
            record.last_login_at = when.replace(tzinfo=None)

    def update_password_hash(self, email: str, password_hash: str) -> None:
        with self._session() as session:
            record = session.get(AdminUserRecord, self._normalise(email))
            if record is None:
                raise ValueError(f"Admin user '{email}' not found.")
            record.password_hash = password_hash

    @staticmethod
    def _to_domain(record: AdminUserRecord) -> AdminUser:
        return AdminUser(
            email=record.email,
            full_name=record.full_name,
            role=AdminRole(record.role),
            is_active=record.is_active,
            created_at=record.created_at.replace(tzinfo=timezone.utc),
            last_login_at=(
                record.last_login_at.replace(tzinfo=timezone.utc)
                if record.last_login_at
                else None
            ),
            password_hash=record.password_hash,
        )
