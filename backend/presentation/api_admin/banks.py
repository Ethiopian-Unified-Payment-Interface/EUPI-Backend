"""
Admin Bank Management API Routes
Layer: 🔵 LAYER 4 — Presentation / API Routers
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.domain.models.account import BankID
from backend.domain.models.admin import BankConfig, BankRailStatus
from backend.presentation.api_admin.auth_deps import get_current_admin_user

router = APIRouter(prefix="/banks", tags=["Admin — Bank Rail Management"])


class BankConfigRequest(BaseModel):
    bank_id: BankID = Field(..., description="Unique commercial bank rail code.")
    name: str = Field(..., description="Full commercial bank name.")
    description: str = Field(..., description="Adapter purpose and description.")
    status: BankRailStatus = Field(default=BankRailStatus.ACTIVE, description="Rail operational status.")
    base_url: str = Field(..., description="CBS API base URL.")
    api_key_header_name: str = Field(..., description="Auth HTTP header name.")
    api_key: str | None = Field(default=None, description="API key or token.")
    timeout_ms: int = Field(default=3000, description="HTTP timeout threshold in ms.")
    cost_weight: float = Field(default=0.20, description="Cost weight ratio.")
    circuit_breaker_threshold: float = Field(default=0.50, description="Circuit breaker threshold.")


class BankConfigUpdatePayload(BaseModel):
    name: str = Field(..., description="Full commercial bank name.")
    description: str = Field(..., description="Adapter purpose and description.")
    status: BankRailStatus = Field(default=BankRailStatus.ACTIVE, description="Rail operational status.")
    base_url: str = Field(..., description="CBS API base URL.")
    api_key_header_name: str = Field(..., description="Auth HTTP header name.")
    api_key: str | None = Field(default=None, description="API key or token.")
    timeout_ms: int = Field(default=3000, description="HTTP timeout threshold in ms.")
    cost_weight: float = Field(default=0.20, description="Cost weight ratio.")
    circuit_breaker_threshold: float = Field(default=0.50, description="Circuit breaker threshold.")


class BankResponse(BaseModel):
    success: bool = True
    bank_id: BankID
    message: str = "Bank rail configuration updated successfully."


@router.get(
    "",
    response_model=dict[str, list[BankConfig]],
    status_code=status.HTTP_200_OK,
    summary="List Bank Rails",
    description="Returns all registered commercial bank adapters and their live status.",
)
def list_bank_rails(
    admin: dict = Depends(get_current_admin_user),
) -> dict[str, list[BankConfig]]:
    from backend.main import get_admin_bank_service
    service = get_admin_bank_service()
    banks = service.list_banks()
    return {"banks": banks}


@router.get(
    "/{bank_id}",
    response_model=BankConfig,
    status_code=status.HTTP_200_OK,
    summary="Get Specific Bank Rail Configuration",
)
def get_bank_rail(
    bank_id: str,
    admin: dict = Depends(get_current_admin_user),
) -> BankConfig:
    from backend.main import get_admin_bank_service
    service = get_admin_bank_service()
    try:
        b_enum = BankID(bank_id.upper())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid bank_id '{bank_id}'.")

    config = service.get_bank(b_enum)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Bank rail '{bank_id}' not found.")
    return config


@router.post(
    "",
    response_model=BankResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create New Bank Rail",
)
def create_bank_rail(
    body: BankConfigRequest,
    admin: dict = Depends(get_current_admin_user),
) -> BankResponse:
    from backend.main import get_admin_bank_service
    service = get_admin_bank_service()
    service.update_bank(
        bank_id=body.bank_id,
        name=body.name,
        description=body.description,
        status=body.status,
        base_url=body.base_url,
        api_key_header_name=body.api_key_header_name,
        api_key=body.api_key,
        timeout_ms=body.timeout_ms,
        cost_weight=body.cost_weight,
        circuit_breaker_threshold=body.circuit_breaker_threshold,
        actor_email=admin.get("email", "admin@kifiya.com"),
    )
    return BankResponse(bank_id=body.bank_id, message="Bank rail configuration created successfully.")


@router.put(
    "/{bank_id}",
    response_model=BankResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Bank Rail Configuration",
)
def update_bank_rail(
    bank_id: str,
    body: BankConfigUpdatePayload,
    admin: dict = Depends(get_current_admin_user),
) -> BankResponse:
    from backend.main import get_admin_bank_service
    service = get_admin_bank_service()
    try:
        b_enum = BankID(bank_id.upper())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid bank_id '{bank_id}'.")

    service.update_bank(
        bank_id=b_enum,
        name=body.name,
        description=body.description,
        status=body.status,
        base_url=body.base_url,
        api_key_header_name=body.api_key_header_name,
        api_key=body.api_key,
        timeout_ms=body.timeout_ms,
        cost_weight=body.cost_weight,
        circuit_breaker_threshold=body.circuit_breaker_threshold,
        actor_email=admin.get("email", "admin@kifiya.com"),
    )
    return BankResponse(bank_id=b_enum, message="Bank rail configuration updated successfully.")
