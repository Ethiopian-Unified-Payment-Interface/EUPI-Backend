"""
Use Case: Admin Analytics & Reporting Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.
"""

from __future__ import annotations

import logging

from backend.application.ports.admin_ports import AdminAnalyticsPort, AuditLogRepositoryPort
from backend.domain.models.admin import (
    ActivityItem,
    AuditLog,
    CustomerStats,
    DashboardStats,
    MerchantStats,
    MerchantTxnStats,
    TransactionStats,
    WebhookLog,
)

logger = logging.getLogger(__name__)


class AdminAnalyticsService:
    """
    Admin Analytics, Reporting & Audit Feed Orchestrator.
    """

    def __init__(
        self,
        analytics_repo: AdminAnalyticsPort,
        audit_repo: AuditLogRepositoryPort,
    ) -> None:
        self._analytics_repo = analytics_repo
        self._audit_repo = audit_repo

    def get_dashboard_stats(self) -> DashboardStats:
        """Retrieve system dashboard KPIs."""
        return self._analytics_repo.get_dashboard_stats()

    def get_activity_feed(self, limit: int = 20) -> list[ActivityItem]:
        """Retrieve activity feed events."""
        return self._analytics_repo.get_activity_feed(limit)

    def get_customer_stats(self) -> CustomerStats:
        """Retrieve customer onboarding KPIs."""
        return self._analytics_repo.get_customer_stats()

    def get_transaction_stats(self) -> TransactionStats:
        """Retrieve transaction metrics."""
        return self._analytics_repo.get_transaction_stats()

    def get_merchant_stats(self) -> MerchantStats:
        """Retrieve merchant metrics."""
        return self._analytics_repo.get_merchant_stats()

    def get_merchant_txn_stats(self) -> MerchantTxnStats:
        """Retrieve merchant payment metrics."""
        return self._analytics_repo.get_merchant_txn_stats()

    def list_customers(self, page: int = 1, limit: int = 50) -> tuple[list[dict], int]:
        """Retrieve paginated customers directly from database."""
        return self._analytics_repo.list_customers(page=page, limit=limit)

    def list_transactions(self, page: int = 1, limit: int = 50) -> tuple[list[dict], int]:
        """Retrieve paginated system-wide transactions directly from database."""
        return self._analytics_repo.list_transactions(page=page, limit=limit)

    def list_webhooks(self, limit: int = 50) -> list[WebhookLog]:
        """Retrieve webhook logs."""
        return self._analytics_repo.list_webhooks(limit)

    def list_audit_logs(self, limit: int = 50, offset: int = 0) -> tuple[list[AuditLog], int]:
        """Retrieve paginated administrative audit logs."""
        return self._audit_repo.list_logs(limit, offset)

    def record_audit_log(
        self,
        action: str,
        actor_email: str,
        details: str,
        ip_address: str = "unknown",
    ) -> AuditLog:
        """
        Write an entry to the administrative audit trail.

        Used for security-relevant reads as well as writes — notably unmasked
        PII access, which is authorised but must never be untraceable.

        Args:
            action:      Action code, e.g. "PII_REVEALED".
            actor_email: Operator who performed the action.
            details:     Human-readable description of what was accessed.
            ip_address:  Originating client IP where known.

        Returns:
            The persisted :class:`~domain.models.admin.AuditLog` entry.
        """
        return self._audit_repo.log_action(
            action=action,
            actor_email=actor_email,
            ip_address=ip_address,
            details=details,
        )
