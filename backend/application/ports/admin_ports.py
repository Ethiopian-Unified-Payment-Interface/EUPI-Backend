"""
Application Ports: Admin Interfaces
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.account import BankID
from backend.domain.models.admin import (
    ActivityItem,
    AuditLog,
    BankConfig,
    CustomerStats,
    DashboardStats,
    DeveloperApp,
    KYBRequest,
    Merchant,
    MerchantStats,
    MerchantTxnStats,
    TransactionStats,
    WebhookLog,
)


class BankConfigRepositoryPort(ABC):
    """Abstract Driven Port for dynamic commercial bank rail persistence."""

    @abstractmethod
    def list_configs(self) -> list[BankConfig]:
        """Retrieve configurations for all registered bank rails."""
        ...

    @abstractmethod
    def get_config(self, bank_id: BankID) -> BankConfig | None:
        """Retrieve configuration for a specific bank rail."""
        ...

    @abstractmethod
    def save_config(self, config: BankConfig) -> None:
        """Persist or update a bank rail configuration."""
        ...


class MerchantRepositoryPort(ABC):
    """Abstract Driven Port for TPP Merchant, App, and KYB persistence."""

    @abstractmethod
    def list_merchants(self) -> list[Merchant]:
        """Retrieve all registered TPP merchants."""
        ...

    @abstractmethod
    def get_merchant(self, merchant_id: str) -> Merchant | None:
        """Retrieve a merchant by ID."""
        ...

    @abstractmethod
    def list_developer_apps(self) -> list[DeveloperApp]:
        """Retrieve all developer applications."""
        ...

    @abstractmethod
    def list_kyb_requests(self) -> list[KYBRequest]:
        """Retrieve all KYB verification requests."""
        ...

    @abstractmethod
    def update_kyb_status(self, kyb_id: str, status: str, note: str | None = None) -> KYBRequest | None:
        """Approve or reject a KYB request."""
        ...


class AuditLogRepositoryPort(ABC):
    """Abstract Driven Port for administrative audit trail logging."""

    @abstractmethod
    def log_action(self, action: str, actor_email: str, ip_address: str, details: str) -> AuditLog:
        """Create and persist an administrative audit log entry."""
        ...

    @abstractmethod
    def list_logs(self, limit: int = 50, offset: int = 0) -> tuple[list[AuditLog], int]:
        """Retrieve paginated audit logs with total count."""
        ...


class AdminAnalyticsPort(ABC):
    """Abstract Driven Port for system analytics, customer lists, and transaction reports."""

    @abstractmethod
    def get_dashboard_stats(self) -> DashboardStats:
        """Compute high-level system metrics."""
        ...

    @abstractmethod
    def get_activity_feed(self, limit: int = 20) -> list[ActivityItem]:
        """Retrieve recent system activity events."""
        ...

    @abstractmethod
    def get_customer_stats(self) -> CustomerStats:
        """Compute customer onboarding KPIs."""
        ...

    @abstractmethod
    def get_transaction_stats(self) -> TransactionStats:
        """Compute transaction volume and success rate KPIs."""
        ...

    @abstractmethod
    def get_merchant_stats(self) -> MerchantStats:
        """Compute merchant traffic KPIs."""
        ...

    @abstractmethod
    def get_merchant_txn_stats(self) -> MerchantTxnStats:
        """Compute merchant payment KPIs."""
        ...

    @abstractmethod
    def list_customers(self, page: int = 1, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
        """Retrieve paginated registered customers from database."""
        ...

    @abstractmethod
    def list_transactions(self, page: int = 1, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
        """Retrieve paginated system-wide transactions from database."""
        ...

    @abstractmethod
    def list_webhooks(self, limit: int = 50) -> list[WebhookLog]:
        """Retrieve recent webhook delivery logs."""
        ...
