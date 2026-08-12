"""
Presentation Layer: Handles & User Profile Routes — /v1/handles/*
Layer: LAYER 4 — Driving Adapters (Presentation)
Rule: Handle registration, availability check, and alias resolution.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backend.infrastructure.auth import jwt_handler

router = APIRouter(prefix="/handles", tags=["🆔 Handles & User Profiles"])
_bearer = HTTPBearer()


# Request / Response Schemas

class HandleCheckResponse(BaseModel):
    username: str
    available: bool
    message: str


class HandleRegisterBody(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        pattern=r"^[a-zA-Z0-9_]+$",
        examples=["abebe"],
    )
    pin: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$", examples=["123456"])
    default_bank_id: str | None = Field(None, examples=["CBE"])
    default_account_number: str | None = Field(None, examples=["1000123456789"])


class SetDefaultAccountBody(BaseModel):
    default_bank_id: str = Field(..., examples=["CBE"])
    default_account_number: str = Field(..., examples=["1000123456789"])


class HandleResponse(BaseModel):
    username: str
    handle: str
    fin: str
    default_bank_id: str | None = None
    default_account_number: str | None = None


class HandleResolveResponse(BaseModel):
    username: str
    handle: str
    bank_id: str
    account_number: str
    account_name: str


# Route Handlers

@router.get(
    "/check",
    response_model=HandleCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Check if a handle (@username) is available",
)
def check_handle_availability(
    username: str = Query(..., min_length=3, max_length=30, description="Handle username to check"),
) -> HandleCheckResponse:
    from backend.main import get_repo
    repo = get_repo()
    available = repo.is_handle_available(username)
    clean_handle = username.strip().lstrip("@").lower()
    return HandleCheckResponse(
        username=clean_handle,
        available=available,
        message=f"Handle '{clean_handle}@kifiya' is {'available' if available else 'taken'}.",
    )


@router.post(
    "/register",
    response_model=HandleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a unique handle (@username) and 6-digit security PIN",
)
def register_handle(
    body: HandleRegisterBody,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> HandleResponse:
    from backend.main import get_repo
    repo = get_repo()

    fin = jwt_handler.get_fin(credentials.credentials)
    if not fin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cannot extract customer identity from token.",
        )

    clean_handle = body.username.strip().lstrip("@").lower()
    if not repo.is_handle_available(clean_handle):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Handle '{clean_handle}' is already registered.",
        )

    record = repo.register_handle(
        username=clean_handle,
        fin=fin,
        pin=body.pin,
        default_bank_id=body.default_bank_id,
        default_account_number=body.default_account_number,
    )

    return HandleResponse(
        username=record.username,
        handle=f"{record.username}@kifiya",
        fin=record.fin,
        default_bank_id=record.default_bank_id,
        default_account_number=record.default_account_number,
    )


@router.post(
    "/set-default-account",
    response_model=HandleResponse,
    status_code=status.HTTP_200_OK,
    summary="Set default receiving bank account for user handle",
)
def set_default_account(
    body: SetDefaultAccountBody,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> HandleResponse:
    from backend.main import get_repo
    repo = get_repo()

    fin = jwt_handler.get_fin(credentials.credentials)
    if not fin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cannot extract customer identity from token.",
        )

    record = repo.get_handle_by_fin(fin)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No handle registered for this user identity.",
        )

    updated_record = repo.update_default_account(
        username=record.username,
        default_bank_id=body.default_bank_id,
        default_account_number=body.default_account_number,
    )

    return HandleResponse(
        username=updated_record.username,
        handle=f"{updated_record.username}@kifiya",
        fin=updated_record.fin,
        default_bank_id=updated_record.default_bank_id,
        default_account_number=updated_record.default_account_number,
    )



@router.get(
    "/resolve/{username}",
    response_model=HandleResolveResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve a handle (@username) to recipient bank details",
)
def resolve_handle(username: str) -> HandleResolveResponse:
    from backend.main import get_repo
    repo = get_repo()
    clean_handle = username.strip().lstrip("@").lower()
    record = repo.get_handle(clean_handle)

    if not record:
        # For mock/hackathon demo fallback: resolve default mock names if handle not registered in DB yet
        demo_recipients = {
            "sara": ("CBE", "1000987654321", "Sara Tesfaye"),
            "tadesse": ("AWASH", "2000883211770", "Tadesse Balcha"),
            "abebe": ("COOP", "1000234567890", "Abebe Girma Tadesse"),
        }
        if clean_handle in demo_recipients:
            bank_id, acct_num, name = demo_recipients[clean_handle]
            return HandleResolveResponse(
                username=clean_handle,
                handle=f"{clean_handle}@kifiya",
                bank_id=bank_id,
                account_number=acct_num,
                account_name=name,
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Handle '{clean_handle}@kifiya' not found.",
        )

    return HandleResolveResponse(
        username=record.username,
        handle=f"{record.username}@kifiya",
        bank_id=record.default_bank_id,
        account_number=record.default_account_number,
        account_name=f"{record.username.capitalize()} User",
    )


@router.get(
    "/me",
    response_model=HandleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active user's registered handle and profile",
)
def get_my_profile(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> HandleResponse:
    from backend.main import get_repo
    repo = get_repo()

    fin = jwt_handler.get_fin(credentials.credentials)
    if not fin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cannot extract customer identity from token.",
        )

    record = repo.get_handle_by_fin(fin)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No registered handle found for this account. Please complete handle setup.",
        )

    return HandleResponse(
        username=record.username,
        handle=f"{record.username}@kifiya",
        fin=record.fin,
        default_bank_id=record.default_bank_id,
        default_account_number=record.default_account_number,
    )
