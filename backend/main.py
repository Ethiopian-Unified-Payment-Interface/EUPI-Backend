"""
EUPI — FastAPI Entry Point
================================================
Wires real infrastructure adapters, SQLite persistence, and JWT authentication.

Boot sequence (via lifespan):
  1. Initialise SQLite repositories → creates tables if absent.
  2. Load all existing payments from DB into the in-memory cache.
  3. Wire real bank adapters → AIS, PIS, and Super App use-case orchestrators.
  4. Register all bank rails with the Smart Router.

Run locally:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Swagger UI:  http://localhost:8000/docs
ReDoc:       http://localhost:8000/redoc
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # Load .env file before reading settings

from backend.config import settings  # noqa: E402 — must follow load_dotenv()

# ── Infrastructure: Adapters & Repositories ──────────────────────────────────
from backend.infrastructure.adapters.banks.coop_cbs import CoopCBSAdapter
from backend.infrastructure.adapters.banks.cbe_cbs import CBECBSAdapter
from backend.infrastructure.adapters.banks.wegagen_cbs import WegagenCBSAdapter
from backend.infrastructure.adapters.identity.fayda import FaydaAdapter
from backend.infrastructure.adapters.router.smart_router import SmartRouter
from backend.infrastructure.database.sqlite_repo import SQLiteRepository
from backend.infrastructure.database.user_repository import SQLiteUserRepository
from backend.infrastructure.database.account_link_repository import SQLiteAccountLinkRepository

# ── Application: Use-Case Orchestrators ───────────────────────────────────────
from backend.application.use_cases.ais_service import AISService
from backend.application.use_cases.pis_service import PISService
from backend.application.use_cases.user_registration_service import UserRegistrationService
from backend.application.use_cases.account_linking_service import AccountLinkingService
from backend.application.use_cases.superapp_transfer_service import SuperAppTransferService

# ── Domain ────────────────────────────────────────────────────────────────────
from backend.domain.models.account import BankID

# ── Presentation: API Routers ─────────────────────────────────────────────────
from backend.presentation.api_v1 import accounts, auth, payments, webhooks
from backend.presentation.api_superapp import users, linked_accounts, transfers

# ══════════════════════════════════════════════════════════════════════════════
# Singleton instances (module-level, created once at startup)
# ══════════════════════════════════════════════════════════════════════════════

_repo: SQLiteRepository | None = None
_user_repo: SQLiteUserRepository | None = None
_account_link_repo: SQLiteAccountLinkRepository | None = None

_ais_service: AISService | None = None
_pis_service: PISService | None = None
_identity_port: FaydaAdapter | None = None
_user_registration_service: UserRegistrationService | None = None
_account_linking_service: AccountLinkingService | None = None
_superapp_transfer_service: SuperAppTransferService | None = None


# ── DI Accessors (imported by presentation routers) ──────────────────────────

def get_repo() -> SQLiteRepository:
    assert _repo is not None, "Repository not initialised. Server not started via lifespan."
    return _repo


def get_ais_service() -> AISService:
    assert _ais_service is not None, "AISService not initialised."
    return _ais_service


def get_pis_service() -> PISService:
    assert _pis_service is not None, "PISService not initialised."
    return _pis_service


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


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Lifespan — Boot & Shutdown
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Wire the full DI graph and restore DB state on startup."""
    global _repo, _user_repo, _account_link_repo
    global _ais_service, _pis_service, _identity_port
    global _user_registration_service, _account_linking_service, _superapp_transfer_service

    # 1. Databases & Repositories
    _repo = SQLiteRepository(db_url=settings.DATABASE_URL)
    _user_repo = SQLiteUserRepository(db_url=settings.DATABASE_URL)
    _account_link_repo = SQLiteAccountLinkRepository(db_url=settings.DATABASE_URL)

    # 2. Concrete bank adapters
    bank_ports = {
        BankID.COOP:    CoopCBSAdapter(),
        BankID.CBE:     CBECBSAdapter(),
        BankID.WEGAGEN: WegagenCBSAdapter(),
    }

    # 3. Identity adapter (depends on repo for token revocation)
    _identity_port = FaydaAdapter(repo=_repo)

    # 4. Smart Router — inject bank ports so it can call health_check()
    router = SmartRouter(bank_ports=bank_ports)
    for bank_id in bank_ports:
        router.register_rail(bank_id)

    # 5. Use-case orchestrators (pure DI — no framework magic)
    _ais_service = AISService(bank_ports=bank_ports, identity_port=_identity_port)
    _pis_service = PISService(
        bank_ports=bank_ports,
        identity_port=_identity_port,
        routing_port=router,
    )

    # 6. Super App services
    _user_registration_service = UserRegistrationService(user_repo=_user_repo, identity_port=_identity_port)
    _account_linking_service = AccountLinkingService(
        link_repo=_account_link_repo,
        user_repo=_user_repo,
        bank_ports=bank_ports,
    )
    _superapp_transfer_service = SuperAppTransferService(
        user_repo=_user_repo,
        link_repo=_account_link_repo,
        pis_service=_pis_service,
    )

    # 7. Restore in-memory payment cache from SQLite
    restored = _repo.load_all_payments()
    payments._payment_store.update(restored)
    print(f"✅ Gateway started — {len(restored)} payments restored from DB.")

    yield  # ← Server is running

    print("Gateway shutting down.")


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
        "- **Active Bank Rails**: `COOP`, `CBE`, `WEGAGEN`\n"
    ),
    version="1.0.0",
    contact={"name": "EUPI Engineering Team", "url": "https://kifiya.com"},
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


# ── Root System Health Check ───────────────────────────────────────────────────
@app.get("/", tags=["System Operations"], summary="Gateway Health Check & Telemetry")
def root():
    """Returns gateway status, registered bank rails, and database metadata."""
    return {
        "service": "EUPI: Ethiopian Unified Payment Integration",
        "version": "1.0.0",
        "status": "operational",
        "architecture": "Clean + Hexagonal (Ports & Adapters)",
        "registered_rails": ["COOP", "CBE", "WEGAGEN"],
        "database": settings.DATABASE_URL,
        "docs": "/docs",
        "redoc": "/redoc",
    }
