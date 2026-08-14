"""
Use Case: Admin Bank Management Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.
"""

from __future__ import annotations

import logging

from backend.application.ports.admin_ports import AuditLogRepositoryPort, BankConfigRepositoryPort
from backend.domain.models.account import BankID
from backend.domain.models.admin import BankConfig, BankRailStatus

logger = logging.getLogger(__name__)


class AdminBankService:
    """
    Admin Bank Rail Orchestrator.

    Manages bank rail configurations, updates runtime parameters,
    and logs changes to the audit trail.
    """

    def __init__(
        self,
        bank_config_repo: BankConfigRepositoryPort,
        audit_repo: AuditLogRepositoryPort,
        smart_router: Any = None,
    ) -> None:
        self._bank_config_repo = bank_config_repo
        self._audit_repo = audit_repo
        self._smart_router = smart_router

    def list_banks(self) -> list[BankConfig]:
        """Retrieve all bank configurations."""
        return self._bank_config_repo.list_configs()

    def get_bank(self, bank_id: BankID) -> BankConfig | None:
        """Retrieve specific bank configuration."""
        return self._bank_config_repo.get_config(bank_id)

    def update_bank(
        self,
        bank_id: BankID,
        name: str,
        description: str,
        status: BankRailStatus,
        base_url: str,
        api_key_header_name: str,
        api_key: str | None = None,
        timeout_ms: int = 3000,
        cost_weight: float = 0.20,
        circuit_breaker_threshold: float = 0.50,
        actor_email: str = "admin@kifiya.com",
    ) -> BankConfig:
        """
        Update dynamic bank configuration and notify Smart Router.
        """
        existing = self._bank_config_repo.get_config(bank_id)
        current_api_key = api_key or (existing.api_key if existing else "mock-key")

        config = BankConfig(
            bank_id=bank_id,
            name=name,
            description=description,
            status=status,
            base_url=base_url,
            api_key_header_name=api_key_header_name,
            api_key=current_api_key,
            timeout_ms=timeout_ms,
            cost_weight=cost_weight,
            circuit_breaker_threshold=circuit_breaker_threshold,
            rolling_uptime_percent=existing.rolling_uptime_percent if existing else 99.8,
            avg_latency_ms=existing.avg_latency_ms if existing else 145,
        )

        self._bank_config_repo.save_config(config)

        # Audit Log Entry
        self._audit_repo.log_action(
            action="BANK_RAIL_UPDATED",
            actor_email=actor_email,
            ip_address="127.0.0.1",
            details=f"Updated bank rail configuration for {bank_id.value} (Status: {status.value})",
        )

        # Dynamically update Smart Router if attached
        if self._smart_router and hasattr(self._smart_router, "update_rail_config"):
            try:
                self._smart_router.update_rail_config(
                    bank_id=bank_id,
                    status=status.value,
                    cost_weight=cost_weight,
                )
            except Exception as exc:
                logger.warning(f"Could not dynamically notify Smart Router: {exc}")

        logger.info(f"Admin updated bank configuration for {bank_id.value}")
        return config
