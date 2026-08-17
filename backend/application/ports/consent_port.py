"""
Ports: UserAppIdentityRepositoryPort, ConsentRepositoryPort, FinVaultRepositoryPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.consent import Consent, ConsentScope, UserAppIdentity


class UserAppIdentityRepositoryPort(ABC):
    """
    Abstract Driven Port: Per-application pseudonym persistence.

    The mapping is deliberately one-way in practice: `resolve` goes from a
    known user to their pseudonym for an app, and `find_by_psu_id` comes back
    the other way for a request already authenticated as that app. There is no
    method that enumerates every pseudonym for a user across applications,
    because nothing legitimate needs it and its existence would be the exact
    correlation capability this design removes.
    """

    @abstractmethod
    def get(self, username: str, app_id: str) -> UserAppIdentity | None:
        """
        Retrieve the pseudonym for a user within an application.

        Args:
            username: Internal Super App handle.
            app_id:   Developer application.

        Returns:
            The mapping, or None if this pair has never interacted.
        """
        ...

    @abstractmethod
    def create(self, identity: UserAppIdentity) -> None:
        """
        Persist a new pseudonym.

        Args:
            identity: The mapping to store.

        Raises:
            ValueError: If a mapping already exists for this (user, app) pair,
                        or if the psu_id collides.
        """
        ...

    @abstractmethod
    def find_by_psu_id(self, psu_id: str, app_id: str) -> UserAppIdentity | None:
        """
        Resolve a pseudonym back to a user, scoped to the calling application.

        `app_id` is required, not optional. Without it, one developer could
        present another developer's pseudonym and receive a valid answer,
        which would defeat the isolation entirely.

        Args:
            psu_id: The pseudonym presented by the caller.
            app_id: The application making the request.

        Returns:
            The mapping, or None if that pseudonym does not belong to this app.
        """
        ...


class ConsentRepositoryPort(ABC):
    """Abstract Driven Port: Consent grant persistence."""

    @abstractmethod
    def grant(self, consent: Consent) -> None:
        """
        Persist a new grant.

        Args:
            consent: The grant to store.
        """
        ...

    @abstractmethod
    def find(self, username: str, app_id: str, scope: ConsentScope) -> Consent | None:
        """
        Retrieve the most recent grant of one scope by one user to one app.

        Args:
            username: Internal Super App handle.
            app_id:   Developer application.
            scope:    The scope in question.

        Returns:
            The grant, or None if never granted.
        """
        ...

    @abstractmethod
    def list_for_user(self, username: str) -> list[Consent]:
        """
        Every grant a user has made, across all applications.

        Backs the user-facing consent screen, which is the one place a person
        can see what they have shared and take it back.

        Args:
            username: Internal Super App handle.

        Returns:
            All grants, most recent first.
        """
        ...

    @abstractmethod
    def list_for_app(self, username: str, app_id: str) -> list[Consent]:
        """
        Every grant a user has made to one application.

        Args:
            username: Internal Super App handle.
            app_id:   Developer application.

        Returns:
            All grants for that pairing.
        """
        ...

    @abstractmethod
    def revoke(self, consent_id: str) -> None:
        """
        Revoke a single grant.

        Args:
            consent_id: The grant to revoke.

        Raises:
            ValueError: If no such grant exists.
        """
        ...

    @abstractmethod
    def revoke_all_for_app(self, username: str, app_id: str) -> int:
        """
        Revoke every active grant a user has made to one application.

        Backs the "disconnect this app" action, which must be a single
        operation — a user withdrawing consent should not have to revoke six
        scopes individually and risk leaving one behind.

        Args:
            username: Internal Super App handle.
            app_id:   Developer application.

        Returns:
            Number of grants revoked.
        """
        ...


class FinVaultRepositoryPort(ABC):
    """
    Abstract Driven Port: Encrypted national ID storage.

    Kept in its own table rather than as columns on the user row, so the
    ciphertext and its index can be permissioned, audited, and eventually
    moved to separate storage without touching the user schema.
    """

    @abstractmethod
    def store(self, username: str, blind_index: str, ciphertext: str) -> None:
        """
        Store or replace a user's encrypted FIN.

        Args:
            username:    Internal Super App handle.
            blind_index: Keyed digest for equality lookups.
            ciphertext:  Encrypted FIN.
        """
        ...

    @abstractmethod
    def get_ciphertext(self, username: str) -> str | None:
        """
        Retrieve a user's encrypted FIN.

        Args:
            username: Internal Super App handle.

        Returns:
            Ciphertext, or None if nothing is vaulted for this user.
        """
        ...

    @abstractmethod
    def find_username_by_blind_index(self, blind_index: str) -> str | None:
        """
        Find a user by the blind index of their FIN.

        This is how "one account per national ID" is enforced without ever
        decrypting the stored values.

        Args:
            blind_index: Keyed digest of the FIN being checked.

        Returns:
            The username, or None if no account exists for that FIN.
        """
        ...
