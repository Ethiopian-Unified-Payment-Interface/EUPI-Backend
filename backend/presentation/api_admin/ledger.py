"""
Admin Ledger & Fee Configuration API Routes
Layer: 🔵 LAYER 4 — Presentation / API Routers

Fee rules are the platform's pricing. Every mutation here requires the ADMIN
role and is written to the audit trail — a silent price change is indisputably
a finance incident.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.application.use_cases.fee_service import NoApplicableFeeRuleError
from backend.domain.models.admin_user import AdminUser
from backend.domain.models.fee import ANY_BANK, FeeRule, FeeType
from backend.domain.models.ledger import TransactionType
from backend.presentation.api_admin.auth_deps import get_current_admin_user, require_admin

router = APIRouter(prefix="/ledger", tags=["Admin — Ledger & Fees"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class FeeRuleResponse(BaseModel):
    rule_id: str
    version: int
    description: str
    bank_id: str
    transaction_type: str
    currency: str
    min_amount: Decimal
    max_amount: Decimal | None
    fee_type: str
    flat_fee: Decimal
    percentage_bps: int
    min_fee: Decimal | None
    max_fee: Decimal | None
    revenue_share_bps: int
    is_active: bool
    effective_from: datetime

    @classmethod
    def of(cls, rule: FeeRule) -> "FeeRuleResponse":
        return cls(
            rule_id=rule.rule_id,
            version=rule.version,
            description=rule.description,
            bank_id=rule.bank_id,
            transaction_type=rule.transaction_type.value,
            currency=rule.currency,
            min_amount=rule.min_amount,
            max_amount=rule.max_amount,
            fee_type=rule.fee_type.value,
            flat_fee=rule.flat_fee,
            percentage_bps=rule.percentage_bps,
            min_fee=rule.min_fee,
            max_fee=rule.max_fee,
            revenue_share_bps=rule.revenue_share_bps,
            is_active=rule.is_active,
            effective_from=rule.effective_from,
        )


class FeeRulePayload(BaseModel):
    """Create or revise a fee rule. Version is assigned by the server."""

    rule_id: str = Field(..., examples=["fee_coop_intra"])
    description: str = Field(default="", examples=["Negotiated Coop intra-bank rate"])
    bank_id: str = Field(default=ANY_BANK, examples=["COOP"])
    transaction_type: TransactionType
    currency: str = Field(default="ETB")
    min_amount: Decimal = Field(default=Decimal("0"), ge=0)
    max_amount: Decimal | None = Field(default=None)
    fee_type: FeeType
    flat_fee: Decimal = Field(default=Decimal("0"), ge=0)
    percentage_bps: int = Field(default=0, ge=0, le=10_000)
    min_fee: Decimal | None = Field(default=None)
    max_fee: Decimal | None = Field(default=None)
    revenue_share_bps: int = Field(
        default=4_000,
        ge=0,
        le=10_000,
        description="EUPI's share of the collected fee, in basis points.",
    )

    def to_domain(self) -> FeeRule:
        return FeeRule(
            rule_id=self.rule_id,
            description=self.description,
            bank_id=self.bank_id.strip().upper(),
            transaction_type=self.transaction_type,
            currency=self.currency.strip().upper(),
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            fee_type=self.fee_type,
            flat_fee=self.flat_fee,
            percentage_bps=self.percentage_bps,
            min_fee=self.min_fee,
            max_fee=self.max_fee,
            revenue_share_bps=self.revenue_share_bps,
        )


class FeeQuotePreview(BaseModel):
    """What a given payment would cost under current pricing."""

    customer_fee: Decimal = Field(..., description="What the bank collects from the customer.")
    eupi_revenue: Decimal = Field(..., description="EUPI's revenue share of that fee.")
    bank_retains: Decimal = Field(..., description="The portion the bank keeps.")
    currency: str
    transaction_type: str
    rule_id: str
    rule_version: int
    bank_id: str


class BankPosition(BaseModel):
    bank_id: str
    orchestrated_volume: Decimal = Field(
        ..., description="Gross value moved at this bank. NOT EUPI revenue."
    )
    accrued_revenue: Decimal = Field(
        ..., description="Revenue share this bank owes EUPI."
    )


class ReconciliationResponse(BaseModel):
    period_start: datetime | None
    period_end: datetime | None
    positions: list[BankPosition]
    total_orchestrated_volume: Decimal
    total_accrued_revenue: Decimal


class LedgerEntryResponse(BaseModel):
    entry_id: str
    transaction_ref: str
    account_ref: str
    direction: str
    amount: Decimal
    currency: str
    is_mirror: bool
    description: str
    created_at: datetime


# ── Fee rule routes ───────────────────────────────────────────────────────────


@router.get(
    "/fee-rules",
    response_model=list[FeeRuleResponse],
    status_code=status.HTTP_200_OK,
    summary="List Fee Rules",
    description="Current pricing. Pass `include_inactive=true` to see retired versions.",
)
def list_fee_rules(
    include_inactive: bool = Query(default=False),
    admin: AdminUser = Depends(get_current_admin_user),
) -> list[FeeRuleResponse]:
    from backend.main import get_fee_service

    rules = get_fee_service().list_rules(include_inactive=include_inactive)
    return [FeeRuleResponse.of(r) for r in rules]


@router.post(
    "/fee-rules",
    response_model=FeeRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Fee Rule",
    description="Create version 1 of a new rule. To change an existing rule's price, use the revise endpoint.",
)
def create_fee_rule(
    body: FeeRulePayload,
    admin: AdminUser = Depends(require_admin),
) -> FeeRuleResponse:
    from backend.main import get_admin_analytics_service, get_fee_service

    try:
        created = get_fee_service().create_rule(body.to_domain())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    _audit(
        get_admin_analytics_service(),
        action="FEE_RULE_CREATED",
        actor=admin.email,
        details=f"Created fee rule {created.rule_id} v{created.version}",
    )
    return FeeRuleResponse.of(created)


@router.post(
    "/fee-rules/{rule_id}/revise",
    response_model=FeeRuleResponse,
    status_code=status.HTTP_200_OK,
    summary="Revise Fee Rule",
    description=(
        "Publish a new version and retire the previous one. The old version is "
        "retained so payments priced under it stay explainable — prices are "
        "never edited in place."
    ),
)
def revise_fee_rule(
    rule_id: str,
    body: FeeRulePayload,
    admin: AdminUser = Depends(require_admin),
) -> FeeRuleResponse:
    from backend.main import get_admin_analytics_service, get_fee_service

    if body.rule_id != rule_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path rule_id '{rule_id}' does not match body rule_id '{body.rule_id}'.",
        )

    try:
        revised = get_fee_service().revise_rule(body.to_domain())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    _audit(
        get_admin_analytics_service(),
        action="FEE_RULE_REVISED",
        actor=admin.email,
        details=f"Published {revised.rule_id} v{revised.version}",
    )
    return FeeRuleResponse.of(revised)


@router.delete(
    "/fee-rules/{rule_id}/versions/{version}",
    status_code=status.HTTP_200_OK,
    summary="Deactivate Fee Rule Version",
    description="Retires a version. The row is kept — deleting it would make historical pricing unexplainable.",
)
def deactivate_fee_rule(
    rule_id: str,
    version: int,
    admin: AdminUser = Depends(require_admin),
) -> dict[str, str]:
    from backend.main import get_admin_analytics_service, get_fee_service

    try:
        get_fee_service().deactivate_rule(rule_id, version)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    _audit(
        get_admin_analytics_service(),
        action="FEE_RULE_DEACTIVATED",
        actor=admin.email,
        details=f"Deactivated {rule_id} v{version}",
    )
    return {"message": f"Fee rule {rule_id} v{version} deactivated."}


@router.get(
    "/fee-rules/preview",
    response_model=FeeQuotePreview,
    status_code=status.HTTP_200_OK,
    summary="Preview Pricing",
    description=(
        "Price a hypothetical payment against current rules. Use this to check "
        "a pricing change before publishing it."
    ),
)
def preview_fee(
    bank_id: str = Query(..., examples=["COOP"]),
    amount: Decimal = Query(..., gt=0, examples=["2500.00"]),
    transaction_type: TransactionType = Query(default=TransactionType.INTRA_BANK),
    currency: str = Query(default="ETB"),
    admin: AdminUser = Depends(get_current_admin_user),
) -> FeeQuotePreview:
    from backend.main import get_fee_service

    try:
        quote = get_fee_service().quote(
            bank_id=bank_id,
            transaction_type=transaction_type,
            amount=amount,
            currency=currency,
        )
    except NoApplicableFeeRuleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return FeeQuotePreview(
        customer_fee=quote.customer_fee,
        eupi_revenue=quote.eupi_revenue,
        bank_retains=quote.bank_retains,
        currency=quote.currency,
        transaction_type=quote.transaction_type.value,
        rule_id=quote.rule_id,
        rule_version=quote.rule_version,
        bank_id=quote.bank_id,
    )


# ── Ledger routes ─────────────────────────────────────────────────────────────


@router.get(
    "/reconciliation",
    response_model=ReconciliationResponse,
    status_code=status.HTTP_200_OK,
    summary="Per-Bank Reconciliation",
    description=(
        "Orchestrated volume and accrued revenue per bank, reported separately. "
        "Volume is money that moved at the banks — EUPI never held it. Revenue "
        "is what the banks owe EUPI. Netting the two produces a meaningless number."
    ),
)
def get_reconciliation(
    days: int = Query(default=30, ge=1, le=365, description="Look-back window in days."),
    admin: AdminUser = Depends(get_current_admin_user),
) -> ReconciliationResponse:
    from backend.main import get_ledger_service

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=days)

    positions = get_ledger_service().get_reconciliation(start=start, end=end)

    rows = [
        BankPosition(
            bank_id=bank_id,
            orchestrated_volume=values["orchestrated_volume"],
            accrued_revenue=values["accrued_revenue"],
        )
        for bank_id, values in positions.items()
    ]

    return ReconciliationResponse(
        period_start=start,
        period_end=end,
        positions=rows,
        total_orchestrated_volume=sum(
            (r.orchestrated_volume for r in rows), Decimal("0")
        ),
        total_accrued_revenue=sum((r.accrued_revenue for r in rows), Decimal("0")),
    )


@router.get(
    "/payments/{payment_id}/entries",
    response_model=list[LedgerEntryResponse],
    status_code=status.HTTP_200_OK,
    summary="Ledger Entries for a Payment",
    description="Every posting produced by one payment, for tracing a specific transaction.",
)
def get_payment_entries(
    payment_id: str,
    admin: AdminUser = Depends(get_current_admin_user),
) -> list[LedgerEntryResponse]:
    from backend.main import get_ledger_service

    entries = get_ledger_service().get_payment_entries(payment_id)
    return [
        LedgerEntryResponse(
            entry_id=e.entry_id,
            transaction_ref=e.transaction_ref,
            account_ref=e.account_ref,
            direction=e.direction.value,
            amount=e.amount,
            currency=e.currency,
            is_mirror=e.is_mirror,
            description=e.description,
            created_at=e.created_at,
        )
        for e in entries
    ]


# ── Internals ─────────────────────────────────────────────────────────────────


def _audit(analytics_service, action: str, actor: str, details: str) -> None:
    """
    Record a pricing change. Best-effort — an audit backend problem must not
    roll back a completed configuration change, but the gap is logged loudly.
    """
    import logging

    try:
        analytics_service.record_audit_log(action=action, actor_email=actor, details=details)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception(
            "Failed to write audit entry for %s by %s", action, actor
        )
