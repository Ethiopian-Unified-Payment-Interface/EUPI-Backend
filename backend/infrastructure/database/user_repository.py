"""
User Repository
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: Concrete implementation of the UserRepositoryPort abstract interface.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.application.ports.user_repository_port import UserRepositoryPort
from backend.application.ports.vault_port import IdentityVaultPort
from backend.domain.models.user import SuperAppUser
from backend.infrastructure.database.session import Database, RepositoryBase
from backend.infrastructure.database.models import UserRecord


class UserRepository(RepositoryBase, UserRepositoryPort):
    """
    Relational implementation of UserRepositoryPort.

    Owns the encryption of the national ID at rest. The `users` table stores
    only ciphertext, a keyed blind index for lookups, and the last four digits
    for masked display — never the plaintext value.
    """

    def __init__(self, db: Database, vault: IdentityVaultPort) -> None:
        """
        Args:
            db:    The shared :class:`Database`.
            vault: Encrypts on write and decrypts on read. Required, not
                   optional — a UserRepository without it could not persist a
                   user at all, and making it optional would invite a code
                   path that writes plaintext.
        """
        super().__init__(db)
        self._vault = vault



    def create_user(self, user: SuperAppUser) -> None:
        record = UserRecord(
            username=user.username,
            fin_encrypted=self._vault.encrypt(user.fin),
            fin_blind_index=self._vault.blind_index(user.fin),
            fin_last4=user.fin[-4:],
            full_name=user.full_name,
            phone_number=user.phone_number,
            created_at=user.created_at.replace(tzinfo=None),
            is_active=user.is_active,
            pin_hash=user.pin_hash,
        )
        with self._session() as session:
            session.add(record)


    def get_by_username(self, username: str) -> SuperAppUser | None:
        with self._session() as session:
            record = session.query(UserRecord).filter(
                UserRecord.username == username
            ).first()
            return self._to_domain(record) if record else None

    def get_by_fin(self, fin: str) -> SuperAppUser | None:
        """
        Look up an account by national ID.

        Matches on the blind index, so "one account per national ID" is
        enforced by an indexed equality lookup without decrypting a single
        stored value.
        """
        with self._session() as session:
            record = session.query(UserRecord).filter(
                UserRecord.fin_blind_index == self._vault.blind_index(fin)
            ).first()
            return self._to_domain(record) if record else None

    def username_exists(self, username: str) -> bool:
        with self._session() as session:
            return session.query(UserRecord).filter(
                UserRecord.username == username
            ).count() > 0

    def _to_domain(self, record: UserRecord) -> SuperAppUser:
        locked_until = record.pin_locked_until
        return SuperAppUser(
            username=record.username,
            # Decrypted per read. Fernet costs microseconds, and the
            # alternative — keeping the plaintext on disk — is the thing this
            # design exists to remove.
            fin=self._vault.decrypt(record.fin_encrypted),
            full_name=record.full_name,
            phone_number=record.phone_number,
            created_at=record.created_at.replace(tzinfo=timezone.utc),
            is_active=record.is_active,
            pin_hash=record.pin_hash,
            failed_pin_attempts=record.failed_pin_attempts or 0,
            pin_locked_until=(
                locked_until.replace(tzinfo=timezone.utc) if locked_until else None
            ),
        )

    def update_pin_hash(self, username: str, pin_hash: str) -> None:
        with self._session() as session:
            record = session.get(UserRecord, username)
            if record is None:
                raise ValueError(f"User '{username}' not found.")
            record.pin_hash = pin_hash

    def update_pin_security(
        self,
        username: str,
        failed_attempts: int,
        locked_until: datetime | None,
    ) -> None:
        with self._session() as session:
            record = session.get(UserRecord, username)
            if record is None:
                raise ValueError(f"User '{username}' not found.")
            record.failed_pin_attempts = failed_attempts
            # Stored naive-UTC to match the rest of this schema.
            record.pin_locked_until = (
                locked_until.replace(tzinfo=None) if locked_until else None
            )