"""
Use Case: Admin Merchant & KYB Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.
"""

from __future__ import annotations

import logging

from backend.application.ports.admin_ports import AuditLogRepositoryPort, MerchantRepositoryPort
from backend.domain.models.admin import DeveloperApp, KYBRequest, Merchant, WebhookLog

logger = logging.getLogger(__name__)


class AdminMerchantService:
    """
    Admin Merchant, Developer Apps & KYB Verification Orchestrator.
    """

    def __init__(
        self,
        merchant_repo: MerchantRepositoryPort,
        audit_repo: AuditLogRepositoryPort,
    ) -> None:
        self._merchant_repo = merchant_repo
        self._audit_repo = audit_repo

    def list_merchants(self) -> list[Merchant]:
        """Retrieve all TPP merchants."""
        return self._merchant_repo.list_merchants()

    def list_apps(self) -> list[DeveloperApp]:
        """Retrieve all registered developer applications."""
        return self._merchant_repo.list_developer_apps()

    def list_kyb_requests(self) -> list[KYBRequest]:
        """Retrieve all KYB verification requests."""
        return self._merchant_repo.list_kyb_requests()

    def review_kyb_request(
        self,
        kyb_id: str,
        status: str,
        note: str | None = None,
        actor_email: str = "admin@kifiya.com",
    ) -> KYBRequest:
        """
        Approve or reject a KYB verification request and log to audit trail.
        """
        updated = self._merchant_repo.update_kyb_status(kyb_id, status, note)
        if updated is None:
            raise ValueError(f"KYB request '{kyb_id}' not found.")

        self._audit_repo.log_action(
            action=f"KYB_{status.upper()}",
            actor_email=actor_email,
            ip_address="127.0.0.1",
            details=f"Reviewed KYB request '{kyb_id}' for company '{updated.company_name}' -> {status}",
        )

        logger.info(f"Admin reviewed KYB request {kyb_id}: {status}")
        return updated
