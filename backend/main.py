"""
EUPI — FastAPI Entry Point
================================================
Wires real infrastructure adapters, SQLite persistence, and JWT authentication.

Boot sequence (via lifespan):
  1. Initialise repositories → creates tables if absent.
  2. Provision the simulated core banking system's accounts.
  3. Wire bank adapters → AIS, PIS, and Super App use-case orchestrators.
  4. Register all bank rails with the Smart Router.
  5. Start the webhook delivery and bank settlement workers.

Run locally:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Swagger UI:  http://localhost:8000/docs
ReDoc:       http://localhost:8000/redoc
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # Load .env file before reading settings

from backend.config import settings  # noqa: E402 — must follow load_dotenv()

logger = logging.getLogger(__name__)

# ── Infrastructure: Adapters & Repositories ──────────────────────────────────
from backend.infrastructure.adapters.banks.coop_cbs import CoopCBSAdapter
from backend.infrastructure.adapters.banks.cbe_cbs import CBECBSAdapter
from backend.infrastructure.adapters.banks.wegagen_cbs import WegagenCBSAdapter
from backend.infrastructure.adapters.banks.awash_cbs import AwashCBSAdapter
from backend.infrastructure.adapters.banks.abyssinia_cbs import AbyssiniaCBSAdapter
from backend.infrastructure.adapters.banks.berhan_cbs import BerhanCBSAdapter
from backend.infrastructure.adapters.banks.simulation.engine import (
    SimulatedCoreBankingEngine,
)
from backend.infrastructure.adapters.banks.simulation.settlement_worker import (
    settlement_worker_loop,
)
from backend.infrastructure.adapters.identity.fayda import FaydaAdapter
from backend.infrastructure.adapters.router.smart_router import SmartRouter
from backend.infrastructure.auth.password_hasher import Argon2PasswordHasher
from backend.infrastructure.auth.identity_vault import FernetIdentityVault
from backend.infrastructure.database.session import Database
from backend.infrastructure.database.payment_repository import PaymentRepository
from backend.infrastructure.database.user_repository import UserRepository
from backend.infrastructure.database.admin_user_repository import AdminUserRepository
from backend.infrastructure.database.account_link_repository import AccountLinkRepository
from backend.infrastructure.database.consent_repository import (
    ConsentRepository,
    FinVaultRepository,
    UserAppIdentityRepository,
)
from backend.infrastructure.database.ledger_repository import (
    FeeRuleRepository,
    LedgerRepository,
)
from backend.infrastructure.database.admin_repositories import (
    AdminAnalyticsRepository,
    AuditLogRepository,
    BankConfigRepository,
    MerchantRepository,
)

# ── Application: Use-Case Orchestrators ───────────────────────────────────────
from backend.application.use_cases.ais_service import AISService
from backend.application.use_cases.pis_service import PISService
from backend.application.use_cases.payment_settlement_service import (
    PaymentSettlementService,
)
from backend.application.use_cases.user_registration_service import UserRegistrationService
from backend.application.use_cases.account_linking_service import AccountLinkingService
from backend.application.use_cases.superapp_transfer_service import SuperAppTransferService
from backend.application.use_cases.admin_auth_service import AdminAuthService
from backend.application.use_cases.consent_service import ConsentService
from backend.application.use_cases.fee_service import FeeService
from backend.application.use_cases.ledger_service import LedgerService
from backend.application.use_cases.admin_bank_service import AdminBankService
from backend.application.use_cases.admin_merchant_service import AdminMerchantService
from backend.application.use_cases.admin_analytics_service import AdminAnalyticsService
from backend.application.use_cases.developer_auth_service import DeveloperAuthService

# ── Domain ────────────────────────────────────────────────────────────────────
from backend.domain.models.account import BankID

# ── Presentation: API Routers ─────────────────────────────────────────────────
from backend.presentation.api_v1 import accounts, auth, payments, webhooks
from backend.presentation.api_superapp import (
    users,
    linked_accounts,
    transfers,
    consents,
    transactions as superapp_transactions,
    apps as superapp_apps,
)
from backend.presentation.api_oauth import oauth_router
from backend.presentation.api_developer import (
    auth as developer_auth,
    apps as developer_apps,
    webhooks as developer_webhooks,
    explorer as developer_explorer,
    kyb as developer_kyb,
)
from backend.presentation.api_admin import admin_router

# ══════════════════════════════════════════════════════════════════════════════
# Singleton instances (module-level, created once at startup)
# ══════════════════════════════════════════════════════════════════════════════

_db: Database | None = None

_repo: PaymentRepository | None = None
_user_repo: UserRepository | None = None
_admin_user_repo: AdminUserRepository | None = None
_account_link_repo: AccountLinkRepository | None = None
_bank_config_repo: BankConfigRepository | None = None
_merchant_repo: MerchantRepository | None = None
_audit_repo: AuditLogRepository | None = None
_analytics_repo: AdminAnalyticsRepository | None = None
_ledger_repo: LedgerRepository | None = None
_fee_rule_repo: FeeRuleRepository | None = None
_app_identity_repo: UserAppIdentityRepository | None = None
_consent_repo: ConsentRepository | None = None
_fin_vault_repo: FinVaultRepository | None = None

_password_hasher: Argon2PasswordHasher | None = None
_identity_vault: FernetIdentityVault | None = None

_ledger_service: LedgerService | None = None
_fee_service: FeeService | None = None
_consent_service: ConsentService | None = None

_cbs_engine: SimulatedCoreBankingEngine | None = None

_ais_service: AISService | None = None
_pis_service: PISService | None = None
_settlement_service: PaymentSettlementService | None = None
_identity_port: FaydaAdapter | None = None
_user_registration_service: UserRegistrationService | None = None
_account_linking_service: AccountLinkingService | None = None
_superapp_transfer_service: SuperAppTransferService | None = None
_admin_auth_service: AdminAuthService | None = None
_admin_bank_service: AdminBankService | None = None
_admin_merchant_service: AdminMerchantService | None = None
_admin_analytics_service: AdminAnalyticsService | None = None
_developer_auth_service: DeveloperAuthService | None = None


# ── DI Accessors (imported by presentation routers) ──────────────────────────

def get_repo() -> PaymentRepository:
    assert _repo is not None, "Repository not initialised. Server not started via lifespan."
    return _repo


def get_user_repository() -> UserRepository:
    assert _user_repo is not None, "UserRepository not initialised."
    return _user_repo


def get_admin_user_repository() -> AdminUserRepository:
    assert _admin_user_repo is not None, "AdminUserRepository not initialised."
    return _admin_user_repo


def get_admin_auth_service() -> AdminAuthService:
    assert _admin_auth_service is not None, "AdminAuthService not initialised."
    return _admin_auth_service


def get_ledger_service() -> LedgerService:
    assert _ledger_service is not None, "LedgerService not initialised."
    return _ledger_service


def get_fee_service() -> FeeService:
    assert _fee_service is not None, "FeeService not initialised."
    return _fee_service


def get_consent_service() -> ConsentService:
    assert _consent_service is not None, "ConsentService not initialised."
    return _consent_service


def get_ais_service() -> AISService:
    assert _ais_service is not None, "AISService not initialised."
    return _ais_service


def get_pis_service() -> PISService:
    assert _pis_service is not None, "PISService not initialised."
    return _pis_service


def get_payment_settlement_service() -> PaymentSettlementService:
    assert _settlement_service is not None, "PaymentSettlementService not initialised."
    return _settlement_service


def get_cbs_engine() -> SimulatedCoreBankingEngine:
    assert _cbs_engine is not None, "Simulated core banking engine not initialised."
    return _cbs_engine


def get_identity_port() -> FaydaAdapter:
    assert _identity_port is not None, "IdentityPort not initialised."
    return _identity_port


def get_user_registration_service() -> UserRegistrationService:
    assert _user_registration_service is not None, "UserRegistrationService not initialised."
    return _user_registration_service


def get_account_linking_service() -> AccountLinkingService:
    assert _account_linking_service is not None, "AccountLinkingService not initialised."
    return _account_linking_service


def get_superapp_transfer_service() -> SuperAppTransferService:
    assert _superapp_transfer_service is not None, "SuperAppTransferService not initialised."
    return _superapp_transfer_service


def get_admin_bank_service() -> AdminBankService:
    assert _admin_bank_service is not None, "AdminBankService not initialised."
    return _admin_bank_service


def get_admin_merchant_service() -> AdminMerchantService:
    assert _admin_merchant_service is not None, "AdminMerchantService not initialised."
    return _admin_merchant_service


def get_admin_analytics_service() -> AdminAnalyticsService:
    assert _admin_analytics_service is not None, "AdminAnalyticsService not initialised."
    return _admin_analytics_service


def get_developer_auth_service() -> DeveloperAuthService:
    assert _developer_auth_service is not None, "DeveloperAuthService not initialised."
    return _developer_auth_service


# ══════════════════════════════════════════════════════════════════════════════
# Admin Bootstrap
# ══════════════════════════════════════════════════════════════════════════════

def _bootstrap_admin(auth_service: AdminAuthService) -> None:
    """
    Ensure a first admin operator exists so the Admin Portal is reachable.

    There is deliberately no unauthenticated path into the Admin API, so
    without a seeded operator the portal would be permanently locked out.
    Runs only when the operator table is empty.

    Credentials come from ADMIN_BOOTSTRAP_EMAIL / ADMIN_BOOTSTRAP_PASSWORD.
    In DEBUG a development default is used and loudly announced; outside DEBUG
    the variables are required and startup logs a clear error if absent.
    """
    email = os.getenv("ADMIN_BOOTSTRAP_EMAIL", "").strip()
    password = os.getenv("ADMIN_BOOTSTRAP_PASSWORD", "")

    if not email or not password:
        if not settings.DEBUG:
            logger.error(
                "No admin operator exists and ADMIN_BOOTSTRAP_EMAIL / "
                "ADMIN_BOOTSTRAP_PASSWORD are unset. The Admin Portal is "
                "unreachable until an operator is created."
            )
            return
        email = email or "admin@kifiya.com"
        password = password or "ChangeMe!Dev123"

    created = auth_service.bootstrap_first_admin(email=email, password=password)
    if created is None:
        return

    if settings.DEBUG:
        logger.warning(
            "Seeded development admin %s with a well-known password. "
            "Set ADMIN_BOOTSTRAP_EMAIL / ADMIN_BOOTSTRAP_PASSWORD before any "
            "shared deployment.",
            created.email,
        )
    else:
        logger.info("Seeded initial admin operator %s.", created.email)


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Lifespan — Boot & Shutdown
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Wire the full DI graph and restore DB state on startup."""
    global _db
    global _repo, _user_repo, _admin_user_repo, _account_link_repo
    global _bank_config_repo, _merchant_repo, _audit_repo, _analytics_repo
    global _ledger_repo, _fee_rule_repo
    global _app_identity_repo, _consent_repo, _fin_vault_repo, _identity_vault
    global _consent_service
    global _password_hasher
    global _ledger_service, _fee_service
    global _cbs_engine, _settlement_service
    global _ais_service, _pis_service, _identity_port
    global _user_registration_service, _account_linking_service, _superapp_transfer_service
    global _admin_auth_service, _admin_bank_service, _admin_merchant_service, _admin_analytics_service
    global _developer_auth_service

    # 0. Shared security primitives
    # Security primitives first: UserRepository needs the vault to encrypt
    # the national ID before it can persist a single user.
    _password_hasher = Argon2PasswordHasher()
    _identity_vault = FernetIdentityVault()

    # 1. One engine, one pool, one schema bootstrap — shared by every
    #    repository below. Previously each of these built its own engine.
    _db = Database(url=settings.DATABASE_URL, echo=False)
    _db.create_all()

    # Repositories — all sharing the single Database above.
    _repo = PaymentRepository(_db)
    _user_repo = UserRepository(_db, _identity_vault)
    _admin_user_repo = AdminUserRepository(_db)
    _account_link_repo = AccountLinkRepository(_db)
    _bank_config_repo = BankConfigRepository(_db)
    _merchant_repo = MerchantRepository(_db)
    _audit_repo = AuditLogRepository(_db)
    _analytics_repo = AdminAnalyticsRepository(_db)
    _ledger_repo = LedgerRepository(_db)
    _fee_rule_repo = FeeRuleRepository(_db)
    _app_identity_repo = UserAppIdentityRepository(_db)
    _consent_repo = ConsentRepository(_db)
    _fin_vault_repo = FinVaultRepository(_db)

    # 2. Bank rails.
    #
    # One core banking simulator shared by all six adapters: they are distinct
    # banks, but inside a single simulator, which is what lets a cross-bank
    # transfer debit and credit in one atomic step. Provisioning is idempotent,
    # so a restart never resets a balance someone is mid-demo with.
    #
    # Going live means swapping an adapter for one that talks to a real CBS.
    # Nothing above this line changes, because nothing above it knows which it
    # is talking to.
    _cbs_engine = SimulatedCoreBankingEngine(
        _db, settlement_delay_seconds=settings.CBS_SETTLEMENT_DELAY_SECONDS
    )
    _cbs_engine.provision()
    logger.warning(
        "Bank rails are SIMULATED. Balances and transfers are sandbox "
        "fixtures, not customer money."
    )

    bank_ports = {
        BankID.COOP:      CoopCBSAdapter(_cbs_engine),
        BankID.CBE:       CBECBSAdapter(_cbs_engine),
        BankID.WEGAGEN:   WegagenCBSAdapter(_cbs_engine),
        BankID.AWASH:     AwashCBSAdapter(_cbs_engine),
        BankID.ABYSSINIA: AbyssiniaCBSAdapter(_cbs_engine),
        BankID.BERHAN:    BerhanCBSAdapter(_cbs_engine),
    }

    # 3. Identity adapter (depends on repo for token revocation)
    _identity_port = FaydaAdapter(repo=_repo)

    # 4. Smart Router — inject bank ports so it can call health_check()
    router = SmartRouter(bank_ports=bank_ports)
    for bank_id in bank_ports:
        router.register_rail(bank_id)

    # 5. Accounting stack — must exist before PISService, which posts to it.
    _ledger_service = LedgerService(ledger_repo=_ledger_repo)
    _fee_service = FeeService(fee_rule_repo=_fee_rule_repo)
    _fee_service.seed_defaults_if_empty()
    _consent_service = ConsentService(
        identity_repo=_app_identity_repo,
        consent_repo=_consent_repo,
        vault_repo=_fin_vault_repo,
        vault=_identity_vault,
        user_repo=_user_repo,
    )

    # 6. Use-case orchestrators (pure DI — no framework magic)
    _ais_service = AISService(bank_ports=bank_ports, identity_port=_identity_port)
    _pis_service = PISService(
        bank_ports=bank_ports,
        identity_port=_identity_port,
        routing_port=router,
        ledger_service=_ledger_service,
        fee_service=_fee_service,
    )
    _settlement_service = PaymentSettlementService(
        payment_repo=_repo,
        pis_service=_pis_service,
    )

    # 7. Super App services
    _user_registration_service = UserRegistrationService(
        user_repo=_user_repo,
        password_hasher=_password_hasher,
        identity_port=_identity_port,
    )
    _account_linking_service = AccountLinkingService(
        link_repo=_account_link_repo,
        user_repo=_user_repo,
        bank_ports=bank_ports,
    )
    _superapp_transfer_service = SuperAppTransferService(
        user_repo=_user_repo,
        link_repo=_account_link_repo,
        pis_service=_pis_service,
        # Both required for PIN-authorised transfers: one verifies the PIN,
        # the other mints the consent token derived from that verification.
        identity_port=_identity_port,
        registration_service=_user_registration_service,
        # Settlement has to run in this request: the bank adapter already
        # posted the debit and credit, and returning ORDERED is what the
        # Super App renders as a pending transfer that never settled.
        payment_repo=_repo,
        settlement_service=_settlement_service,
    )

    # 8. Admin Services
    _admin_auth_service = AdminAuthService(
        admin_repo=_admin_user_repo,
        password_hasher=_password_hasher,
    )
    _bootstrap_admin(_admin_auth_service)

    _admin_bank_service = AdminBankService(
        bank_config_repo=_bank_config_repo,
        audit_repo=_audit_repo,
        smart_router=router,
    )
    _admin_merchant_service = AdminMerchantService(
        merchant_repo=_merchant_repo,
        audit_repo=_audit_repo,
    )
    _admin_analytics_service = AdminAnalyticsService(
        analytics_repo=_analytics_repo,
        audit_repo=_audit_repo,
    )
    _developer_auth_service = DeveloperAuthService(
        db=_db,
        password_hasher=_password_hasher,
    )

    # 10. Background workers.
    from backend.infrastructure.webhooks.delivery_worker import webhook_worker_loop

    # The simulated banks' settlement dispatcher. Without it a payment reaches
    # ORDERED and stays there: the callback endpoint exists, but in a sandbox
    # there is no bank to call it.
    background = [
        asyncio.create_task(webhook_worker_loop(_db, poll_interval=10.0)),
        asyncio.create_task(
            settlement_worker_loop(
                engine=_cbs_engine,
                settlement=_settlement_service,
                poll_interval=settings.CBS_SETTLEMENT_POLL_INTERVAL_SECONDS,
                failure_rate=settings.CBS_SETTLEMENT_FAILURE_RATE,
            )
        ),
    ]

    yield  # ← Server is running

    logger.info("Gateway shutting down.")
    for task in background:
        task.cancel()
    await asyncio.gather(*background, return_exceptions=True)


# ══════════════════════════════════════════════════════════════════════════════
# OpenAPI Tags Metadata
# ══════════════════════════════════════════════════════════════════════════════

tags_metadata = [
    {
        "name": "Authentication",
        "description": (
            "**Step 1 of gateway access.** Authenticate Ethiopian citizens via Fayda eKYC. "
            "Dispatches OTP to registered phone numbers and issues cryptographically signed HS256 JWT tokens."
        ),
    },
    {
        "name": "Account Information (AIS)",
        "description": (
            "**Open Banking AIS Endpoints.** Query aggregated real-time account balances "
            "and ISO 20022 transaction history across COOP, CBE, and Wegagen Bank rails."
        ),
    },
    {
        "name": "Payment Initiation (PIS)",
        "description": (
            "**Open Banking PIS Endpoints.** Execute multi-bank payments via a standardized 4-step state machine "
            "(Initiate → Verify → Order → Callback) with automated Smart Router rail selection."
        ),
    },
    {
        "name": "Webhooks & Callbacks",
        "description": (
            "**Asynchronous Settlement.** Receives final debit/credit confirmation from bank Core Banking Systems "
            "to drive payments to SUCCESS or FAILED state."
        ),
    },
    {
        "name": "Super App — User Management",
        "description": (
            "**Platform Registration.** Register Super App user accounts after Fayda eKYC and "
            "look up public profiles by username for P2P recipient verification."
        ),
    },
    {
        "name": "Super App — Account Linking",
        "description": (
            "**Bank Account Management.** Link, list, and manage bank accounts attached to Super App profiles. "
            "Set default sending/receiving accounts for P2P transfers."
        ),
    },
    {
        "name": "Super App — P2P Transfers",
        "description": (
            "**Handle-Based Transfers.** Send money to other Super App users by username. "
            "Resolves default accounts, selects optimal banking rail, and creates a PIS payment."
        ),
    },
    {
        "name": "System Operations",
        "description": "**Gateway Telemetry.** Operational health check, active bank rails, and database metadata.",
    },
]

# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Application Configuration
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="EUPI: Ethiopian Unified Payment Integration",
    description=(
        "## Ethiopia's Unified Open Banking & Payment API Standard\n\n"
        "EUPI provides a standardized Open Banking interface for **Account Information Services (AIS)**, "
        "**Payment Initiation Services (PIS)**, and a **Super App Platform** for handle-based P2P transfers — "
        "all across multiple Ethiopian commercial banking rails.\n\n"
        "---\n\n"
        "### How to Test in Swagger UI\n\n"
        "1. **Dispatch OTP** — `POST /v1/auth/fayda` (pre-filled with test FIN `12345678901234`). Copy the `session_id`.\n"
        "2. **Get JWT** — `POST /v1/auth/fayda/confirm` with OTP `123456`. Copy the `access_token`.\n"
        "3. **Authorize** — Click the **Authorize** button (top right) and paste `Bearer <token>`.\n"
        "4. **Query AIS** — `GET /v1/accounts` → aggregated balances across COOP, CBE, Wegagen.\n"
        "5. **Execute PIS** — `POST /v1/payments/initiate` → `/verify` → `/order` → `/callbacks`.\n"
        "6. **Super App** — Register a user, link a bank account, then send money by username.\n\n"
        "---\n\n"
        "### Test Data & Credentials\n"
        "- **Test FINs**: `12345678901234` (Abebe Girma Tadesse), `23456789012345` (Selamawit Bekele Hailu)\n"
        "- **Mock OTP Code**: `123456`\n"
        "- **Active Bank Rails**: `COOP`, `CBE`, `WEGAGEN`, `AWASH`, `ABYSSINIA`, `BERHAN`\n"
    ),
    version="1.0.0",
    license_info={"name": "Proprietary"},
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── CORS Middleware ────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount API Routers ──────────────────────────────────────────────────────────
API_V1_PREFIX = "/v1"
app.include_router(auth.router,            prefix=API_V1_PREFIX)
app.include_router(accounts.router,        prefix=API_V1_PREFIX)
app.include_router(payments.router,        prefix=API_V1_PREFIX)
app.include_router(webhooks.router,        prefix=API_V1_PREFIX)
app.include_router(users.router,           prefix=API_V1_PREFIX)
app.include_router(linked_accounts.router, prefix=API_V1_PREFIX)
app.include_router(transfers.router,       prefix=API_V1_PREFIX)
app.include_router(consents.router,        prefix=API_V1_PREFIX)
app.include_router(superapp_transactions.router, prefix=API_V1_PREFIX)
app.include_router(superapp_apps.router,    prefix=API_V1_PREFIX)
app.include_router(oauth_router.router,    prefix=API_V1_PREFIX)
app.include_router(developer_auth.router,   prefix=API_V1_PREFIX)
app.include_router(developer_apps.router,   prefix=API_V1_PREFIX)
app.include_router(developer_webhooks.router, prefix=API_V1_PREFIX)
app.include_router(developer_explorer.router, prefix=API_V1_PREFIX)
app.include_router(developer_kyb.router,      prefix=API_V1_PREFIX)
app.include_router(admin_router)


# ── Root System Health Check ───────────────────────────────────────────────────
@app.get("/", tags=["System Operations"], summary="Gateway Health Check & Telemetry")
def root():
    """Returns gateway status, registered bank rails, and database metadata."""
    return {
        "service": "EUPI: Ethiopian Unified Payment Integration",
        "version": "1.0.0",
        "status": "operational",
        "architecture": "Clean + Hexagonal (Ports & Adapters)",
        "registered_rails": [bank.value for bank in BankID],
        "database": settings.DATABASE_URL,
        "docs": "/docs",
        "redoc": "/redoc",
    }
