"""
Presentation Layer: Super App Account Linking Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.domain.models.linked_account import AccountDirection
from backend.domain.models.user import SuperAppUser
from backend.presentation.api_superapp.auth_deps import get_current_superapp_user

router = APIRouter(prefix="/superapp/accounts", tags=["Super App — Account Linking"])


# ── Request / Response Schemas ─────────────────────────────────────────────────

class LinkAccountRequest(BaseModel):
    """Payload to link a bank account to a Super App user profile."""

    username: str = Field(
        ...,
        description="Super App username handle (e.g. 'abebe_girma'). The @eupi postfix is automatically handled.",
        examples=["abebe_girma"],
    )
    bank_id: str = Field(
        ...,
        description="Bank rail code (COOP, CBE, WEGAGEN, AWASH, ABYSSINIA, or BERHAN).",
        examples=["COOP"],
    )
    account_number: str = Field(
        ...,
        description="Account number at the bank.",
        examples=["1000234567890"],
    )


class SetDefaultRequest(BaseModel):
    """Payload to designate a linked account as default for a transfer direction."""

    username: str = Field(
        ...,
        description="Super App username handle (e.g. 'abebe_girma'). The @eupi postfix is automatically handled.",
        examples=["abebe_girma"],
    )
    direction: AccountDirection = Field(
        ...,
        description="Transfer direction role: SENDING (outgoing) or RECEIVING (incoming).",
        examples=["SENDING"],
    )


class LinkedAccountResponse(BaseModel):
    """Full linked bank account detail."""

    link_id: str = Field(..., description="Unique account link ID.", examples=["LNK-A1B2C3D4"])
    username: str = Field(..., description="Super App username.", examples=["abebe_girma@eupi"])
    bank_id: str = Field(..., description="Bank rail code.", examples=["COOP"])
    account_number: str = Field(..., description="Account number.", examples=["1000123456789"])
    account_name: str = Field(..., description="Account holder name at the bank.", examples=["Abebe Girma Tadesse"])
    is_default_sending: bool = Field(..., description="Whether this is the default outgoing transfer account.", examples=[True])
    is_default_receiving: bool = Field(..., description="Whether this is the default incoming transfer account.", examples=[True])
    linked_at: datetime = Field(..., description="Timestamp of when the account was linked.")


class SyncedAccountBalanceResponse(BaseModel):
    """Dashboard view of a linked bank account with live balance synchronization."""

    link_id: str = Field(..., description="Unique account link ID.", examples=["LNK-A1B2C3D4"])
    username: str = Field(..., description="Super App username.", examples=["abebe_girma@eupi"])
    bank_id: str = Field(..., description="Bank rail code.", examples=["COOP"])
    account_number: str = Field(..., description="Account number.", examples=["1000123456789"])
    account_name: str = Field(..., description="Account holder name at the bank.", examples=["Abebe Girma Tadesse"])
    available_balance: Decimal = Field(..., description="Live available balance at the bank.", examples=["12500.50"])
    ledger_balance: Decimal = Field(..., description="Live ledger balance at the bank.", examples=["13000.00"])
    currency: str = Field(default="ETB", description="Currency code.", examples=["ETB"])
    is_default_sending: bool = Field(..., description="Default outgoing sending account flag.")
    is_default_receiving: bool = Field(..., description="Default incoming receiving account flag.")
    linked_at: datetime = Field(..., description="Timestamp of when the account was linked.")


class MessageResponse(BaseModel):
    """Standard operation result message."""

    message: str = Field(..., description="Operation result.", examples=["Operation completed successfully."])


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/link",
    response_model=LinkedAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="1. Link Bank Account (with Fayda FIN Verification)",
    description=(
        "**Verify and link a bank account to a Super App profile.**\n\n"
        "Requires active session header. Verifies that the bank account exists AND that the "
        "account holder name at the bank matches the user's Fayda National ID identity.\n\n"
        "The first account linked is automatically set as default for both sending and receiving."
    ),
)
def link_account(
    body: LinkAccountRequest,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> LinkedAccountResponse:
    from backend.main import get_account_linking_service
    from backend.domain.models.account import BankID
    from backend.domain.models.user import normalize_username
    service = get_account_linking_service()

    if normalize_username(current_user.username) != normalize_username(body.username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot link an account for another user.")

    try:
        link = service.link_account(
            username=body.username,
            bank_id=BankID(body.bank_id.upper()),
            account_number=body.account_number,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return LinkedAccountResponse(
        link_id=link.link_id,
        username=link.username,
        bank_id=link.bank_id.value,
        account_number=link.account_number,
        account_name=link.account_name,
        is_default_sending=link.is_default_sending,
        is_default_receiving=link.is_default_receiving,
        linked_at=link.linked_at,
    )


@router.get(
    "/sync",
    response_model=list[SyncedAccountBalanceResponse],
    status_code=status.HTTP_200_OK,
    summary="Sync Connected Banks & Live Balances",
    description=(
        "**Queries live balances across all connected bank accounts for the authenticated session user.**\n\n"
        "Provides real-time balance synchronization across connected bank rails."
    ),
)
def sync_connected_banks(
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> list[SyncedAccountBalanceResponse]:
    from backend.main import get_account_linking_service
    service = get_account_linking_service()

    synced = service.sync_user_accounts(username=current_user.username)
    return [SyncedAccountBalanceResponse(**item) for item in synced]


@router.get(
    "/user/{username}",
    response_model=list[LinkedAccountResponse],
    status_code=status.HTTP_200_OK,
    summary="2. List Linked Accounts",
    description="Returns all bank accounts linked to a Super App user. Requires active session.",
)
def list_linked_accounts(
    username: str,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> list[LinkedAccountResponse]:
    from backend.main import get_account_linking_service
    from backend.domain.models.user import normalize_username
    service = get_account_linking_service()

    if normalize_username(current_user.username) != normalize_username(username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view accounts of another user.")

    links = service.list_linked_accounts(username=username)
    return [
        LinkedAccountResponse(
            link_id=lnk.link_id,
            username=lnk.username,
            bank_id=lnk.bank_id.value,
            account_number=lnk.account_number,
            account_name=lnk.account_name,
            is_default_sending=lnk.is_default_sending,
            is_default_receiving=lnk.is_default_receiving,
            linked_at=lnk.linked_at,
        )
        for lnk in links
    ]


@router.put(
    "/{link_id}/default",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="3. Set Default Account",
    description="Sets a linked account as the default for outgoing (SENDING) or incoming (RECEIVING) transfers.",
)
def set_default_account(
    link_id: str,
    body: SetDefaultRequest,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> MessageResponse:
    from backend.main import get_account_linking_service
    from backend.domain.models.user import normalize_username
    service = get_account_linking_service()

    if normalize_username(current_user.username) != normalize_username(body.username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify account of another user.")

    try:
        service.set_default_account(username=body.username, link_id=link_id, direction=body.direction)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return MessageResponse(
        message=f"Account '{link_id}' set as default for {body.direction.value}.",
    )


@router.delete(
    "/{link_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="4. Unlink Bank Account",
    description="Removes a linked bank account from a Super App profile.",
)
def remove_linked_account(
    link_id: str,
    username: str,
    current_user: SuperAppUser = Depends(get_current_superapp_user),
) -> MessageResponse:
    from backend.main import get_account_linking_service
    from backend.domain.models.user import normalize_username
    service = get_account_linking_service()

    if normalize_username(current_user.username) != normalize_username(username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot unlink account of another user.")

    try:
        service.remove_linked_account(username=username, link_id=link_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return MessageResponse(message=f"Linked account '{link_id}' removed.")
