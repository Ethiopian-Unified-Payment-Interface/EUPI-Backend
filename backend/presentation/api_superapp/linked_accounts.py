"""
Presentation Layer: Super App Account Linking Routes
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)
Rule: Route handlers only. Unpack JSON → call use case → return HTTP response.
      NO business logic lives here.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.domain.models.linked_account import AccountDirection

router = APIRouter(prefix="/superapp/accounts", tags=["Super App — Account Linking"])


# ── Request / Response Schemas ─────────────────────────────────────────────────

class LinkAccountRequest(BaseModel):
    """Payload to link a bank account to a Super App user profile."""

    user_id: str = Field(
        ...,
        description="Super App user ID (from /superapp/users/register).",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    bank_id: str = Field(
        ...,
        description="Bank rail code (COOP, CBE, or WEGAGEN).",
        examples=["COOP"],
    )
    account_number: str = Field(
        ...,
        description="Account number at the bank.",
        examples=["1000123456789"],
    )


class SetDefaultRequest(BaseModel):
    """Payload to designate a linked account as default for a transfer direction."""

    user_id: str = Field(
        ...,
        description="Super App user ID (ownership verification).",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    direction: AccountDirection = Field(
        ...,
        description="Transfer direction role: SENDING (outgoing) or RECEIVING (incoming).",
        examples=["SENDING"],
    )


class LinkedAccountResponse(BaseModel):
    """Full linked bank account detail."""

    link_id: str = Field(..., description="Unique account link ID.", examples=["LNK-A1B2C3D4"])
    user_id: str = Field(..., description="Super App user ID.", examples=["550e8400-e29b-41d4-a716-446655440000"])
    bank_id: str = Field(..., description="Bank rail code.", examples=["COOP"])
    account_number: str = Field(..., description="Account number.", examples=["1000123456789"])
    account_name: str = Field(..., description="Account holder name at the bank.", examples=["Abebe Girma Tadesse"])
    is_default_sending: bool = Field(..., description="Whether this is the default outgoing transfer account.", examples=[True])
    is_default_receiving: bool = Field(..., description="Whether this is the default incoming transfer account.", examples=[True])
    linked_at: datetime = Field(..., description="Timestamp of when the account was linked.")


class MessageResponse(BaseModel):
    """Standard operation result message."""

    message: str = Field(..., description="Operation result.", examples=["Operation completed successfully."])


# ── Route Handlers ─────────────────────────────────────────────────────────────

@router.post(
    "/link",
    response_model=LinkedAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="1. Link Bank Account",
    description=(
        "**Verify and link a bank account to a Super App profile.**\n\n"
        "The account is verified at the target bank (via `get_balance()`). "
        "The first account linked is automatically set as default for both sending and receiving."
    ),
)
def link_account(body: LinkAccountRequest) -> LinkedAccountResponse:
    from backend.main import get_account_linking_service
    from backend.domain.models.account import BankID
    service = get_account_linking_service()

    try:
        link = service.link_account(
            user_id=body.user_id,
            bank_id=BankID(body.bank_id.upper()),
            account_number=body.account_number,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return LinkedAccountResponse(
        link_id=link.link_id,
        user_id=link.user_id,
        bank_id=link.bank_id.value,
        account_number=link.account_number,
        account_name=link.account_name,
        is_default_sending=link.is_default_sending,
        is_default_receiving=link.is_default_receiving,
        linked_at=link.linked_at,
    )


@router.get(
    "/user/{user_id}",
    response_model=list[LinkedAccountResponse],
    status_code=status.HTTP_200_OK,
    summary="2. List Linked Accounts",
    description="Returns all bank accounts linked to a Super App user.",
)
def list_linked_accounts(user_id: str) -> list[LinkedAccountResponse]:
    from backend.main import get_account_linking_service
    service = get_account_linking_service()

    links = service.list_linked_accounts(user_id=user_id)
    return [
        LinkedAccountResponse(
            link_id=lnk.link_id,
            user_id=lnk.user_id,
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
def set_default_account(link_id: str, body: SetDefaultRequest) -> MessageResponse:
    from backend.main import get_account_linking_service
    service = get_account_linking_service()

    try:
        service.set_default_account(user_id=body.user_id, link_id=link_id, direction=body.direction)
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
    description="Removes a linked bank account from a Super App profile. Requires the owning user's ID.",
)
def remove_linked_account(link_id: str, user_id: str) -> MessageResponse:
    from backend.main import get_account_linking_service
    service = get_account_linking_service()

    try:
        service.remove_linked_account(user_id=user_id, link_id=link_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return MessageResponse(message=f"Linked account '{link_id}' removed.")
