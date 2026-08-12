"""
Port: UserRepositoryPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

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
    def get_by_id(self, user_id: str) -> SuperAppUser | None:
        """
        Retrieve a user by their gateway-assigned unique user_id.

        This is the primary lookup used to verify a user exists before
        acting on their behalf (e.g., before linking a bank account),
        since the authenticated caller is identified by user_id, not
        username or FIN.

        Args:
            user_id: The gateway-assigned unique identifier of the user.

        Returns:
            A :class:`~domain.models.user.SuperAppUser` domain object if found, else None.

        Raises:
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
    def update_pin_hash(self, user_id: str, pin_hash: str) -> None:
        """Update the stored PIN hash for a user.
        
        Args:
            user_id: The user's unique identifier.
            pin_hash: The new SHA-256 hash of the PIN.
            
        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...