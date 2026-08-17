"""
Domain Model: Fees
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.

Fee pricing under the revenue-share model.

Who charges whom
----------------
The **bank** charges the customer. EUPI takes a contracted share of that fee.
EUPI never debits the customer directly and never holds the money — it accrues
a receivable against the bank and recognises revenue.

That is why every quote carries both `customer_fee` (what the bank collects)
and `eupi_revenue` (EUPI's cut of it). Reporting one as the other overstates
revenue by roughly 2.5x at the default share.

Versioning
----------
A `FeeRule` is immutable once it has priced anything. Changing a price creates
a new version and deactivates the old one; the old row stays. Every payment
records the exact `rule_id` and `version` that priced it, so re-running a report
over last quarter produces last quarter's numbers rather than today's prices.

Rules are never edited in place. That is the whole design.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from backend.domain.models.ledger import TransactionType

# Wildcard for a rule that applies to every bank.
ANY_BANK = "*"

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round to two decimal places, half-up — the convention for currency."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


class FeeType(str, Enum):
    """How a fee is computed from the payment amount."""

    FLAT = "FLAT"
    """A fixed charge regardless of amount."""

    PERCENTAGE = "PERCENTAGE"
    """A share of the payment amount, in basis points."""

    HYBRID = "HYBRID"
    """A flat component plus a percentage component."""


class FeeRule(BaseModel):
    """
    A versioned pricing rule.

    Matching is by bank, transaction type, currency, and an amount band.
    Specificity wins: a rule naming a bank beats a wildcard rule, so a
    negotiated rate for one partner overrides the platform default without
    having to restate every other bank's pricing.
    """

    rule_id: str = Field(
        ...,
        description="Stable identifier shared across versions of the same rule.",
        examples=["fee_intra_coop"],
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Increments on every price change. Old versions are retained.",
    )
    description: str = Field(
        default="",
        description="Why this rule exists — read by operators in the admin portal.",
    )

    # ── Matching criteria ─────────────────────────────────────────────────────
    bank_id: str = Field(
        default=ANY_BANK,
        description=f"Bank this applies to, or '{ANY_BANK}' for all banks.",
        examples=["COOP"],
    )
    transaction_type: TransactionType = Field(
        ...,
        description="Whether this prices intra-bank or cross-bank settlement.",
    )
    currency: str = Field(
        default="ETB",
        description="ISO 4217 currency code.",
    )
    min_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Inclusive lower bound of the amount band.",
    )
    max_amount: Decimal | None = Field(
        default=None,
        description="Exclusive upper bound, or None for unbounded.",
    )

    # ── Pricing ───────────────────────────────────────────────────────────────
    fee_type: FeeType = Field(
        ...,
        description="FLAT, PERCENTAGE, or HYBRID.",
    )
    flat_fee: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Fixed component, used by FLAT and HYBRID.",
    )
    percentage_bps: int = Field(
        default=0,
        ge=0,
        le=10_000,
        description=(
            "Percentage component in basis points (100 bps = 1%). Integer "
            "basis points rather than a float percentage so pricing is exact."
        ),
    )
    min_fee: Decimal | None = Field(
        default=None,
        description="Floor applied after computation.",
    )
    max_fee: Decimal | None = Field(
        default=None,
        description="Cap applied after computation.",
    )

    # ── Revenue share ─────────────────────────────────────────────────────────
    revenue_share_bps: int = Field(
        default=4_000,
        ge=0,
        le=10_000,
        description=(
            "EUPI's share of the collected fee, in basis points. Default 4000 "
            "= 40%. The bank keeps the remainder."
        ),
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    is_active: bool = Field(
        default=True,
        description="Only active rules are considered when pricing.",
    )
    effective_from: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp from which this version applies.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp of creation.",
    )

    @model_validator(mode="after")
    def _check_coherent(self) -> "FeeRule":
        """Reject rules that cannot price anything sensibly."""
        if self.max_amount is not None and self.max_amount <= self.min_amount:
            raise ValueError(
                f"max_amount ({self.max_amount}) must exceed min_amount ({self.min_amount})."
            )
        if self.min_fee is not None and self.max_fee is not None and self.min_fee > self.max_fee:
            raise ValueError(
                f"min_fee ({self.min_fee}) cannot exceed max_fee ({self.max_fee})."
            )
        if self.fee_type is FeeType.FLAT and self.flat_fee <= 0:
            raise ValueError("A FLAT rule needs a flat_fee greater than zero.")
        if self.fee_type is FeeType.PERCENTAGE and self.percentage_bps <= 0:
            raise ValueError("A PERCENTAGE rule needs percentage_bps greater than zero.")
        if self.fee_type is FeeType.HYBRID and self.flat_fee <= 0 and self.percentage_bps <= 0:
            raise ValueError("A HYBRID rule needs a flat_fee or percentage_bps.")
        return self

    def matches(
        self,
        bank_id: str,
        transaction_type: TransactionType,
        currency: str,
        amount: Decimal,
    ) -> bool:
        """
        Whether this rule applies to the given payment.

        Args:
            bank_id:          Bank the payment routes through.
            transaction_type: INTRA_BANK or CROSS_BANK.
            currency:         ISO 4217 code.
            amount:           Payment amount.

        Returns:
            True when every criterion matches.
        """
        if not self.is_active:
            return False
        if self.bank_id != ANY_BANK and self.bank_id != bank_id.strip().upper():
            return False
        if self.transaction_type is not transaction_type:
            return False
        if self.currency != currency.strip().upper():
            return False
        if amount < self.min_amount:
            return False
        if self.max_amount is not None and amount >= self.max_amount:
            return False
        return True

    @property
    def specificity(self) -> int:
        """
        Ranking score for choosing between competing matches.

        A bank-specific rule outranks a wildcard, and a bounded amount band
        outranks an open-ended one — the narrower rule is the more deliberate
        one, so it wins.
        """
        score = 0
        if self.bank_id != ANY_BANK:
            score += 10
        if self.max_amount is not None:
            score += 1
        return score

    def price(self, amount: Decimal) -> tuple[Decimal, Decimal]:
        """
        Compute the fee for a payment amount.

        Args:
            amount: The payment amount.

        Returns:
            `(customer_fee, eupi_revenue)` — what the bank collects from the
            customer, and EUPI's share of it. Both rounded to two decimals.

        Examples:
            A 2.50 flat fee at a 40% share on any amount:
            >>> rule = FeeRule(rule_id="r", transaction_type=TransactionType.INTRA_BANK,
            ...                fee_type=FeeType.FLAT, flat_fee=Decimal("2.50"))
            >>> rule.price(Decimal("1000.00"))
            (Decimal('2.50'), Decimal('1.00'))
        """
        fee = Decimal("0")

        if self.fee_type in (FeeType.FLAT, FeeType.HYBRID):
            fee += self.flat_fee
        if self.fee_type in (FeeType.PERCENTAGE, FeeType.HYBRID):
            fee += amount * Decimal(self.percentage_bps) / Decimal(10_000)

        if self.min_fee is not None:
            fee = max(fee, self.min_fee)
        if self.max_fee is not None:
            fee = min(fee, self.max_fee)

        customer_fee = _money(fee)
        eupi_revenue = _money(customer_fee * Decimal(self.revenue_share_bps) / Decimal(10_000))

        return customer_fee, eupi_revenue


class FeeQuote(BaseModel):
    """
    The priced outcome for one payment, with the rule that produced it.

    `rule_id` and `rule_version` are recorded on the payment so the price is
    reproducible forever. Without them, changing a rule silently rewrites
    history in every report that recomputes fees.
    """

    customer_fee: Decimal = Field(
        ...,
        ge=0,
        description="What the bank collects from the customer.",
    )
    eupi_revenue: Decimal = Field(
        ...,
        ge=0,
        description="EUPI's revenue share of that fee.",
    )
    currency: str = Field(default="ETB", description="ISO 4217 currency code.")
    transaction_type: TransactionType = Field(
        ...,
        description="Settlement type this was priced as.",
    )
    rule_id: str = Field(..., description="Rule that priced this payment.")
    rule_version: int = Field(..., description="Exact version of that rule.")
    bank_id: str = Field(..., description="Bank the fee is receivable from.")

    @property
    def bank_retains(self) -> Decimal:
        """The portion of the fee the bank keeps."""
        return self.customer_fee - self.eupi_revenue


def default_fee_rules() -> list[FeeRule]:
    """
    Seed pricing used when no rules have been configured.

    Deliberately conservative and clearly labelled: intra-bank is priced below
    cross-bank because it needs no interbank settlement, which is the same
    asymmetry that makes intra-bank the sensible launch wedge.

    These are placeholders for commercial negotiation, not researched rates.
    """
    return [
        FeeRule(
            rule_id="fee_default_intra_bank",
            description="Default intra-bank transfer — internal book transfer, no interbank settlement.",
            bank_id=ANY_BANK,
            transaction_type=TransactionType.INTRA_BANK,
            fee_type=FeeType.FLAT,
            flat_fee=Decimal("2.50"),
            revenue_share_bps=4_000,
        ),
        FeeRule(
            rule_id="fee_default_cross_bank",
            description="Default cross-bank transfer — requires interbank settlement.",
            bank_id=ANY_BANK,
            transaction_type=TransactionType.CROSS_BANK,
            fee_type=FeeType.HYBRID,
            flat_fee=Decimal("5.00"),
            percentage_bps=10,  # 0.10%
            max_fee=Decimal("50.00"),
            revenue_share_bps=4_000,
        ),
    ]
