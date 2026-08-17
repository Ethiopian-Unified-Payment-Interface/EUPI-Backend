"""
Consent, Pseudonym & FIN Vault Repositories
Layer: 🔴 LAYER 3 — Infrastructure / Database
Rule: Concrete implementations of the consent port interfaces.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator


from backend.application.ports.consent_port import (
    ConsentRepositoryPort,
    FinVaultRepositoryPort,
    UserAppIdentityRepositoryPort,
)
from backend.domain.models.consent import (
    Consent,
    ConsentScope,
    ConsentStatus,
    UserAppIdentity,
)
from backend.infrastructure.database.session import RepositoryBase
from backend.infrastructure.database.models import (
    Base,
    ConsentRecord,
    FinVaultRecord,
    UserAppIdentityRecord,
)



class UserAppIdentityRepository(RepositoryBase, UserAppIdentityRepositoryPort):
    """Relational implementation of UserAppIdentityRepositoryPort."""

    def get(self, username: str, app_id: str) -> UserAppIdentity | None:
        with self._session() as session:
            record = (
                session.query(UserAppIdentityRecord)
                .filter(
                    UserAppIdentityRecord.username == username,
                    UserAppIdentityRecord.app_id == app_id,
                )
                .first()
            )
            return self._to_domain(record) if record else None

    def create(self, identity: UserAppIdentity) -> None:
        with self._session() as session:
            existing = (
                session.query(UserAppIdentityRecord)
                .filter(
                    UserAppIdentityRecord.username == identity.username,
                    UserAppIdentityRecord.app_id == identity.app_id,
                )
                .first()
            )
            if existing is not None:
                raise ValueError(
                    f"A pseudonym already exists for this user and app "
                    f"({identity.app_id}). Pseudonyms are stable and never reissued."
                )
            session.add(
                UserAppIdentityRecord(
                    psu_id=identity.psu_id,
                    username=identity.username,
                    app_id=identity.app_id,
                    created_at=identity.created_at.replace(tzinfo=None),
                )
            )

    def find_by_psu_id(self, psu_id: str, app_id: str) -> UserAppIdentity | None:
        with self._session() as session:
            # Filtering on app_id as well as psu_id is the isolation guarantee:
            # presenting another app's pseudonym resolves to nothing.
            record = (
                session.query(UserAppIdentityRecord)
                .filter(
                    UserAppIdentityRecord.psu_id == psu_id,
                    UserAppIdentityRecord.app_id == app_id,
                )
                .first()
            )
            return self._to_domain(record) if record else None

    @staticmethod
    def _to_domain(record: UserAppIdentityRecord) -> UserAppIdentity:
        return UserAppIdentity(
            psu_id=record.psu_id,
            username=record.username,
            app_id=record.app_id,
            created_at=record.created_at.replace(tzinfo=timezone.utc),
        )


class ConsentRepository(RepositoryBase, ConsentRepositoryPort):
    """Relational implementation of ConsentRepositoryPort."""

    def grant(self, consent: Consent) -> None:
        with self._session() as session:
            session.add(
                ConsentRecord(
                    consent_id=consent.consent_id,
                    username=consent.username,
                    app_id=consent.app_id,
                    scope=consent.scope.value,
                    status=consent.status.value,
                    granted_at=consent.granted_at.replace(tzinfo=None),
                    expires_at=(
                        consent.expires_at.replace(tzinfo=None)
                        if consent.expires_at
                        else None
                    ),
                    revoked_at=(
                        consent.revoked_at.replace(tzinfo=None)
                        if consent.revoked_at
                        else None
                    ),
                )
            )

    def find(self, username: str, app_id: str, scope: ConsentScope) -> Consent | None:
        with self._session() as session:
            record = (
                session.query(ConsentRecord)
                .filter(
                    ConsentRecord.username == username,
                    ConsentRecord.app_id == app_id,
                    ConsentRecord.scope == scope.value,
                )
                .order_by(ConsentRecord.granted_at.desc())
                .first()
            )
            return self._to_domain(record) if record else None

    def list_for_user(self, username: str) -> list[Consent]:
        with self._session() as session:
            records = (
                session.query(ConsentRecord)
                .filter(ConsentRecord.username == username)
                .order_by(ConsentRecord.granted_at.desc())
                .all()
            )
            return [self._to_domain(r) for r in records]

    def list_for_app(self, username: str, app_id: str) -> list[Consent]:
        with self._session() as session:
            records = (
                session.query(ConsentRecord)
                .filter(
                    ConsentRecord.username == username,
                    ConsentRecord.app_id == app_id,
                )
                .order_by(ConsentRecord.granted_at.desc())
                .all()
            )
            return [self._to_domain(r) for r in records]

    def revoke(self, consent_id: str) -> None:
        with self._session() as session:
            record = session.get(ConsentRecord, consent_id)
            if record is None:
                raise ValueError(f"Consent '{consent_id}' not found.")
            record.status = ConsentStatus.REVOKED.value
            record.revoked_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    def revoke_all_for_app(self, username: str, app_id: str) -> int:
        with self._session() as session:
            records = (
                session.query(ConsentRecord)
                .filter(
                    ConsentRecord.username == username,
                    ConsentRecord.app_id == app_id,
                    ConsentRecord.status == ConsentStatus.GRANTED.value,
                )
                .all()
            )
            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            for record in records:
                record.status = ConsentStatus.REVOKED.value
                record.revoked_at = now
            return len(records)

    @staticmethod
    def _to_domain(record: ConsentRecord) -> Consent:
        return Consent(
            consent_id=record.consent_id,
            username=record.username,
            app_id=record.app_id,
            scope=ConsentScope(record.scope),
            status=ConsentStatus(record.status),
            granted_at=record.granted_at.replace(tzinfo=timezone.utc),
            expires_at=(
                record.expires_at.replace(tzinfo=timezone.utc)
                if record.expires_at
                else None
            ),
            revoked_at=(
                record.revoked_at.replace(tzinfo=timezone.utc)
                if record.revoked_at
                else None
            ),
        )


class FinVaultRepository(RepositoryBase, FinVaultRepositoryPort):
    """Relational implementation of FinVaultRepositoryPort."""

    def store(self, username: str, blind_index: str, ciphertext: str) -> None:
        with self._session() as session:
            record = session.get(FinVaultRecord, username)
            if record is None:
                session.add(
                    FinVaultRecord(
                        username=username,
                        fin_blind_index=blind_index,
                        fin_ciphertext=ciphertext,
                        created_at=datetime.now(tz=timezone.utc).replace(tzinfo=None),
                    )
                )
            else:
                record.fin_blind_index = blind_index
                record.fin_ciphertext = ciphertext

    def get_ciphertext(self, username: str) -> str | None:
        with self._session() as session:
            record = session.get(FinVaultRecord, username)
            return record.fin_ciphertext if record else None

    def find_username_by_blind_index(self, blind_index: str) -> str | None:
        with self._session() as session:
            record = (
                session.query(FinVaultRecord)
                .filter(FinVaultRecord.fin_blind_index == blind_index)
                .first()
            )
            return record.username if record else None
