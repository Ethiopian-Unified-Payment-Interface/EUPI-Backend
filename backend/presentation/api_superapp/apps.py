"""
Super App Partner Apps & Marketplace API Routes
Layer: LAYER 4 — Presentation / API Routers

Provides the catalogue of partner services and mini-programs available
inside the Kifiya Super App (e.g. Ethio Telecom, ZayRide, DSTV, Enat Grocery).
"""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/superapp/apps", tags=["Super App — Partner Marketplace"])


class PartnerAppItem(BaseModel):
    app_id: str
    app_name: str
    merchant_name: str
    category: str = Field(..., description="Telecom & Utilities, Transport & Delivery, Shopping & Grocery, Bills & Entertainment")
    description: str
    icon_name: str
    is_popular: bool = False
    service_type: str = Field(..., description="airtime, ride, grocery, bill, shopping")
    creditor_account_number: str
    creditor_bank_id: str
    packages: Optional[List[dict]] = None


class PartnerAppsCatalogResponse(BaseModel):
    apps: List[PartnerAppItem]
    categories: List[str]
    total: int


# Mock partner catalog fixtures representing pre-integrated Telebirr-style partner apps
FEATURED_PARTNER_APPS: List[PartnerAppItem] = [
    PartnerAppItem(
        app_id="app-ethio-telecom",
        app_name="Ethio Telecom",
        merchant_name="Ethio Telecom Enterprise",
        category="Telecom & Utilities",
        description="Buy Airtime, Voice, and Data bundles instantly",
        icon_name="phone_android",
        is_popular=True,
        service_type="airtime",
        creditor_account_number="CBE-ETHIO-TEL-1000",
        creditor_bank_id="CBE",
        packages=[
            {"id": "pkg-50", "title": "50 ETB Airtime", "amount": 50},
            {"id": "pkg-100", "title": "100 ETB Airtime", "amount": 100},
            {"id": "pkg-data-daily", "title": "Daily 1GB Data Package", "amount": 35},
            {"id": "pkg-data-monthly", "title": "Monthly 10GB Data Package", "amount": 250},
        ],
    ),
    PartnerAppItem(
        app_id="app-zayride",
        app_name="ZayRide Ethiopia",
        merchant_name="ZayRide Technologies",
        category="Transport & Delivery",
        description="Book rides and pay trip fares seamlessly",
        icon_name="local_taxi",
        is_popular=True,
        service_type="ride",
        creditor_account_number="AWASH-ZAYRIDE-2000",
        creditor_bank_id="AWASH",
    ),
    PartnerAppItem(
        app_id="app-dstv",
        app_name="DSTV Ethiopia",
        merchant_name="MultiChoice Ethiopia",
        category="Bills & Entertainment",
        description="Renew TV subscriptions & decoder packages",
        icon_name="tv",
        is_popular=True,
        service_type="bill",
        creditor_account_number="DASHEN-DSTV-3000",
        creditor_bank_id="CBE",
        packages=[
            {"id": "dstv-access", "title": "DSTV Access Package", "amount": 450},
            {"id": "dstv-family", "title": "DSTV Family Package", "amount": 890},
            {"id": "dstv-compact", "title": "DSTV Compact Package", "amount": 1850},
            {"id": "dstv-premium", "title": "DSTV Premium Package", "amount": 3400},
        ],
    ),
    PartnerAppItem(
        app_id="app-enat-grocery",
        app_name="Enat Grocery",
        merchant_name="Enat Fresh Market PLC",
        category="Shopping & Grocery",
        description="Order fresh food and home essentials online",
        icon_name="shopping_basket",
        is_popular=True,
        service_type="grocery",
        creditor_account_number="COOP-ENAT-4000",
        creditor_bank_id="COOP",
    ),
    PartnerAppItem(
        app_id="app-zemen-gebeya",
        app_name="ZemenGebeya",
        merchant_name="Zemen Digital Commerce",
        category="Shopping & Grocery",
        description="Electronics, fashion, and home goods marketplace",
        icon_name="storefront",
        is_popular=False,
        service_type="shopping",
        creditor_account_number="WEGAGEN-ZEMEN-5000",
        creditor_bank_id="WEGAGEN",
    ),
    PartnerAppItem(
        app_id="app-eeu-power",
        app_name="EEU Power Utility",
        merchant_name="Ethiopian Electric Utility",
        category="Telecom & Utilities",
        description="Pay prepaid & postpaid electricity bills",
        icon_name="bolt",
        is_popular=False,
        service_type="bill",
        creditor_account_number="CBE-EEU-POWER-6000",
        creditor_bank_id="CBE",
    ),
]


@router.get(
    "",
    response_model=PartnerAppsCatalogResponse,
    status_code=status.HTTP_200_OK,
    summary="List Partner Marketplace Apps",
    description="Returns the curated list of partner mini-apps and services for the Super App Marketplace.",
)
def list_partner_apps() -> PartnerAppsCatalogResponse:
    categories = list(dict.fromkeys(app.category for app in FEATURED_PARTNER_APPS))
    return PartnerAppsCatalogResponse(
        apps=FEATURED_PARTNER_APPS,
        categories=categories,
        total=len(FEATURED_PARTNER_APPS),
    )
