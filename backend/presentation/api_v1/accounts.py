"""
Presentation Layer: Account Routes — GET /v1/accounts
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backend.infrastructure.auth import jwt_handler

router = APIRouter(prefix="/accounts", tags=["Account Information (AIS)"])
_bearer = HTTPBearer()


# ── Response schemas ───────────────────────────────────────────────────────────

class AccountResponse(BaseModel):
    account_id: str
    bank_id: str
    account_number: str
    account_type: str
    currency: str
    available_balance: Decimal
    ledger_balance: Decimal
    account_name: str
    is_active: bool
    last_updated_at: datetime


class TransactionResponse(BaseModel):
    transaction_id: str
    account_id: str
    bank_id: str
    transaction_type: str
    status: str
    amount: Decimal
    currency: str
    value_date: datetime
    booking_date: datetime
    channel: str | None = None
    counterparty_name: str | None = None
    remittance_info: dict | None = None


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[AccountResponse],
    status_code=status.HTTP_200_OK,
    summary="Get all accounts across all bank rails",
    description=(
        "Returns aggregated account balances from every registered bank rail. "
        "Requires a valid Fayda Bearer token with the `accounts:read` scope. "
        "Bank rails that are temporarily unreachable are skipped — partial "
        "results are returned with the healthy banks."
    ),
)
def get_all_accounts(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> list[AccountResponse]:
    from backend.main import get_ais_service
    ais = get_ais_service()

    # Bug 3 fix: decode the JWT to extract the FIN (stable customer identifier)
    # so the seeded RNG in bank adapters produces consistent account data per customer.
    fin = jwt_handler.get_fin(credentials.credentials)
    if fin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cannot extract customer identity from token.",
        )

    try:
        accounts = ais.get_all_balances(
            consent_token=credentials.credentials,
            customer_fin=fin,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    return [AccountResponse(**acct.model_dump()) for acct in accounts]


@router.get(
    "/{bank_id}/{account_number}",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Get balance for a specific account",
    description="Returns balance and metadata for a single account at a specific bank rail.",
)
def get_single_account(
    bank_id: str,
    account_number: str,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> AccountResponse:
    from backend.main import get_ais_service
    from backend.domain.models.account import BankID
    ais = get_ais_service()
    try:
        account = ais.get_balance_for_bank(
            consent_token=credentials.credentials,
            bank_id=BankID(bank_id.upper()),
            account_number=account_number,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return AccountResponse(**account.model_dump())


@router.get(
    "/{bank_id}/{account_number}/transactions",
    response_model=list[TransactionResponse],
    status_code=status.HTTP_200_OK,
    summary="Get transaction history (up to 1 year)",
    description=(
        "Returns up to 365 days of transaction history for an account. "
        "The date range is clamped to the 1-year maximum per the AIS spec."
    ),
)
def get_transactions(
    bank_id: str,
    account_number: str,
    from_date: datetime | None = Query(default=None, description="Start of history window (UTC ISO 8601)."),
    to_date: datetime | None = Query(default=None, description="End of history window (UTC ISO 8601)."),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> list[TransactionResponse]:
    from backend.main import get_ais_service
    from backend.domain.models.account import BankID
    ais = get_ais_service()

    # Bug 1 fix: FastAPI parses query datetimes without timezone info.
    # Coerce to UTC so the AIS service comparison with datetime.now(tz=timezone.utc) works.
    if from_date is not None and from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=timezone.utc)
    if to_date is not None and to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)

    try:
        txns = ais.get_transactions(
            consent_token=credentials.credentials,
            bank_id=BankID(bank_id.upper()),
            account_number=account_number,
            from_date=from_date,
            to_date=to_date,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return [TransactionResponse(**t.model_dump()) for t in txns]
