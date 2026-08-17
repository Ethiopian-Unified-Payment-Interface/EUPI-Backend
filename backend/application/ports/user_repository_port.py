"""
Port: UserRepositoryPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.user import SuperAppUser


class UserRepositoryPort(ABC):
    """
    Abstract Driven Port: Super App User Persistence Interface.
    
    Defines the contract for storing and retrieving super app user accounts.
    The infrastructure layer provides the concrete SQLite implementation.
    """
    
    @abstractmethod
    def create_user(self, user: SuperAppUser) -> None:
        """
        Persist a new super app user.
        
        Args:
            user: The fully populated :class:`~domain.models.user.SuperAppUser` object to save.
            
        Returns:
            None
            
        Raises:
            UserAlreadyExistsError: If a user with the same username or FIN already exists.
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...
    

    @abstractmethod
    def get_by_username(self, username: str) -> SuperAppUser | None:
        """
        Retrieve a user by their unique username.
        
        Args:
            username: The unique handle chosen by the user.
            
        Returns:
            A :class:`~domain.models.user.SuperAppUser` domain object if found, else None.
            
        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...
    
    @abstractmethod
    def get_by_fin(self, fin: str) -> SuperAppUser | None:
        """
        Retrieve a user by their Fayda Identification Number.
        
        Args:
            fin: The 14-digit Fayda Identification Number.
            
        Returns:
            A :class:`~domain.models.user.SuperAppUser` domain object if found, else None.
            
        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...
    
    @abstractmethod
    def username_exists(self, username: str) -> bool:
        """
        Check whether a username is already taken. Used during registration.
        
        Args:
            username: The unique handle to check.
            
        Returns:
            True if the username is already registered, False otherwise.
            
        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...

    @abstractmethod
    def update_pin_hash(self, username: str, pin_hash: str) -> None:
        """Update the stored PIN hash for a user.

        Args:
            username: The user's unique identifier.
            pin_hash: The new salted hash of the PIN, produced by a
                      :class:`~application.ports.password_hasher_port.PasswordHasherPort`.

        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...

    @abstractmethod
    def update_pin_security(
        self,
        username: str,
        failed_attempts: int,
        locked_until: datetime | None,
    ) -> None:
        """Record the PIN brute-force counters for a user.

        Called after every PIN verification — incrementing on failure, clearing
        on success — so lockout state survives a process restart.

        Args:
            username:        The user's unique identifier.
            failed_attempts: Consecutive failed attempts, 0 to clear.
            locked_until:    UTC timestamp until which authentication is refused,
                             or None to clear an existing lock.

        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...