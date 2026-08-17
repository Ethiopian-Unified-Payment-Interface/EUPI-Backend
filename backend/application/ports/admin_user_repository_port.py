"""
Port: AdminUserRepositoryPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.admin_user import AdminUser


class AdminUserRepositoryPort(ABC):
    """
    Abstract Driven Port: Admin operator persistence.

    Kept separate from `UserRepositoryPort` on purpose. Operators and citizens
    are different principals with different credentials and different blast
    radii; a shared store invites a lookup that accidentally spans both.
    """

    @abstractmethod
    def create(self, admin: AdminUser) -> None:
        """
        Persist a new admin operator.

        Args:
            admin: A fully populated :class:`~domain.models.admin_user.AdminUser`,
                   including a hashed password.

        Raises:
            ValueError: If an operator with that email already exists.
        """
        ...

    @abstractmethod
    def get_by_email(self, email: str) -> AdminUser | None:
        """
        Retrieve an operator by login email.

        Args:
            email: The operator's login email (case-insensitive).

        Returns:
            The :class:`~domain.models.admin_user.AdminUser` if found, else None.
        """
        ...

    @abstractmethod
    def count(self) -> int:
        """
        Total number of operators.

        Used at startup to decide whether bootstrap seeding is required.
        """
        ...

    @abstractmethod
    def update_last_login(self, email: str, when: datetime) -> None:
        """
        Record a successful authentication.

        Args:
            email: The operator's login email.
            when:  UTC timestamp of the login.
        """
        ...

    @abstractmethod
    def update_password_hash(self, email: str, password_hash: str) -> None:
        """
        Replace an operator's stored password hash.

        Args:
            email:         The operator's login email.
            password_hash: New hash from a
                           :class:`~application.ports.password_hasher_port.PasswordHasherPort`.
        """
        ...
