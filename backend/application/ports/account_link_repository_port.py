"""
Port: AccountLinkRepositoryPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.linked_account import AccountDirection, LinkedAccount


class AccountLinkRepositoryPort(ABC):
    """
    Abstract Driven Port: Linked Account Persistence Interface.
    
    Defines the contract for managing explicitly linked bank accounts.
    Super app users link accounts via discovery + verification; this port
    handles the persistence side.
    """
    
    @abstractmethod
    def add_link(self, link: LinkedAccount) -> None:
        """
        Persist a new account link.
        
        Args:
            link: The :class:`~domain.models.linked_account.LinkedAccount` object to persist.
            
        Returns:
            None
            
        Raises:
            AccountAlreadyLinkedError: If this account is already linked for this user.
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...
    
    @abstractmethod
    def list_for_user(self, user_id: str) -> list[LinkedAccount]:
        """
        Retrieve all linked accounts for a given user.
        
        Args:
            user_id: The unique identifier of the super app user.
            
        Returns:
            A list of :class:`~domain.models.linked_account.LinkedAccount` objects belonging to the user.
            
        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...
    
    @abstractmethod
    def get_link(self, link_id: str) -> LinkedAccount | None:
        """
        Retrieve a specific account link by its ID.
        
        Args:
            link_id: The unique identifier of the linked account.
            
        Returns:
            A :class:`~domain.models.linked_account.LinkedAccount` domain object if found, else None.
            
        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...
    
    @abstractmethod
    def set_default(self, link_id: str, direction: AccountDirection) -> None:
        """
        Set an account as the default for a given direction, unsetting any prior default.
        
        Args:
            link_id: The unique identifier of the linked account to set as default.
            direction: The :class:`~domain.models.linked_account.AccountDirection` (SENDING or RECEIVING).
            
        Returns:
            None
            
        Raises:
            LinkNotFoundError: If the account link does not exist.
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...
    
    @abstractmethod
    def remove_link(self, link_id: str) -> bool:
        """
        Remove an account link.
        
        Args:
            link_id: The unique identifier of the linked account to remove.
            
        Returns:
            True if the account link was successfully deleted, False if it was not found.
            
        Raises:
            DatabaseConnectionError: If the underlying storage is unavailable.
        """
        ...
