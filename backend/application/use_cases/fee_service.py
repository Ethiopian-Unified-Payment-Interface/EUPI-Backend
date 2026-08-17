"""
Use Case: Fee Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Prices payments and manages the versioned rule set.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from backend.application.ports.ledger_port import FeeRuleRepositoryPort
from backend.domain.models.fee import FeeQuote, FeeRule, default_fee_rules
from backend.domain.models.ledger import TransactionType

logger = logging.getLogger(__name__)


class FeeError(Exception):
    """Base exception for fee pricing failures."""


class NoApplicableFeeRuleError(FeeError):
    """
    Raised when nothing prices a payment.

    Deliberately fatal rather than defaulting to zero. A silent zero fee looks
    identical to a correctly-priced free transaction, and the difference is
    revenue nobody notices is missing.
    """


class FeeService:
    """
    Fee pricing and rule administration.

    Injected dependencies (constructor injection / Dependency Inversion):
      - fee_rule_repo: Persistence for versioned fee rules.
    """

    def __init__(self, fee_rule_repo: FeeRuleRepositoryPort) -> None:
        self._fee_rule_repo = fee_rule_repo

    # ── Pricing ───────────────────────────────────────────────────────────────

    def quote(
        self,
        bank_id: str,
        transaction_type: TransactionType,
        amount: Decimal,
        currency: str = "ETB",
    ) -> FeeQuote:
        """
        Price a payment.

        Resolution is deterministic: among all matching active rules, the most
        specific wins; ties break on the highest version. Determinism matters
        because the same payment must price identically on a retry.

        Args:
            bank_id:          Bank the payment routes through.
            transaction_type: INTRA_BANK or CROSS_BANK.
            amount:           Payment amount.
            currency:         ISO 4217 code.

        Returns:
            A :class:`~domain.models.fee.FeeQuote` recording the price and the
            exact rule version that produced it.

        Raises:
            NoApplicableFeeRuleError: If no active rule matches.
        """
        normalised_bank = bank_id.strip().upper()
        normalised_currency = currency.strip().upper()

        candidates = [
            rule
            for rule in self._fee_rule_repo.list_active()
            if rule.matches(normalised_bank, transaction_type, normalised_currency, amount)
        ]

        if not candidates:
            raise NoApplicableFeeRuleError(
                f"No active fee rule prices a {transaction_type.value} payment of "
                f"{amount} {normalised_currency} on {normalised_bank}. "
                f"Configure one in the admin portal before accepting this traffic."
            )

        winner = max(candidates, key=lambda r: (r.specificity, r.version))
        customer_fee, eupi_revenue = winner.price(amount)

        logger.debug(
            "Priced payment",
            extra={
                "bank_id": normalised_bank,
                "transaction_type": transaction_type.value,
                "rule_id": winner.rule_id,
                "rule_version": winner.version,
            },
        )

        return FeeQuote(
            customer_fee=customer_fee,
            eupi_revenue=eupi_revenue,
            currency=normalised_currency,
            transaction_type=transaction_type,
            rule_id=winner.rule_id,
            rule_version=winner.version,
            bank_id=normalised_bank,
        )

    def explain(self, rule_id: str, version: int) -> FeeRule | None:
        """
        Retrieve the exact rule version that priced a historical payment.

        Args:
            rule_id: Recorded on the payment.
            version: Recorded on the payment.

        Returns:
            The rule as it was, or None if that version never existed.
        """
        return self._fee_rule_repo.get_version(rule_id, version)

    # ── Administration ────────────────────────────────────────────────────────

    def list_rules(self, include_inactive: bool = False) -> list[FeeRule]:
        """
        List configured rules.

        Args:
            include_inactive: Include retired versions.

        Returns:
            Matching rules.
        """
        if include_inactive:
            return self._fee_rule_repo.list_all()
        return self._fee_rule_repo.list_active()

    def create_rule(self, rule: FeeRule) -> FeeRule:
        """
        Create the first version of a new rule.

        Args:
            rule: The rule to create. Its version is forced to 1.

        Returns:
            The persisted rule.

        Raises:
            ValueError: If the rule_id already exists — use `revise_rule`.
        """
        if self._fee_rule_repo.latest_version(rule.rule_id) > 0:
            raise ValueError(
                f"Rule '{rule.rule_id}' already exists. Use revise_rule to change its price."
            )

        first = rule.model_copy(
            update={"version": 1, "created_at": datetime.now(tz=timezone.utc)}
        )
        self._fee_rule_repo.create(first)
        logger.info("Fee rule created", extra={"rule_id": first.rule_id})
        return first

    def revise_rule(self, rule: FeeRule) -> FeeRule:
        """
        Publish a new version of an existing rule and retire the previous one.

        The old version is retained, not overwritten — payments priced under it
        must remain explainable. This is the only supported way to change a
        price.

        Args:
            rule: The revised rule. Its version is assigned automatically.

        Returns:
            The newly published version.

        Raises:
            ValueError: If the rule_id has never been created.
        """
        current = self._fee_rule_repo.latest_version(rule.rule_id)
        if current == 0:
            raise ValueError(
                f"Rule '{rule.rule_id}' does not exist. Use create_rule first."
            )

        now = datetime.now(tz=timezone.utc)
        revision = rule.model_copy(
            update={
                "version": current + 1,
                "is_active": True,
                "effective_from": now,
                "created_at": now,
            }
        )
        self._fee_rule_repo.create(revision)
        self._fee_rule_repo.deactivate(rule.rule_id, current)

        logger.info(
            "Fee rule revised",
            extra={"rule_id": revision.rule_id, "version": revision.version},
        )
        return revision

    def deactivate_rule(self, rule_id: str, version: int) -> None:
        """
        Retire a rule version.

        Args:
            rule_id: The rule identifier.
            version: The version to retire.
        """
        self._fee_rule_repo.deactivate(rule_id, version)
        logger.info("Fee rule deactivated", extra={"rule_id": rule_id, "version": version})

    def seed_defaults_if_empty(self) -> int:
        """
        Install placeholder pricing when no rules exist.

        Called at startup so a fresh deployment can price traffic instead of
        rejecting every payment with NoApplicableFeeRuleError. Idempotent.

        Returns:
            Number of rules created — 0 when rules already existed.
        """
        if self._fee_rule_repo.list_all():
            return 0

        seeded = default_fee_rules()
        for rule in seeded:
            self._fee_rule_repo.create(rule)

        logger.warning(
            "Seeded %d placeholder fee rules. These are defaults for development, "
            "not commercially negotiated rates — review them before charging real traffic.",
            len(seeded),
        )
        return len(seeded)
