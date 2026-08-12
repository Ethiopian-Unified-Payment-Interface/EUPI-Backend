"""
Kifiya Open Consent Gateway — FastAPI Entry Point
================================================
Phase 3: Real infrastructure adapters + SQLite persistence + JWT auth.

Boot sequence (via lifespan):
  1. Initialise SQLiteRepository → creates tables if absent.
  2. Load all existing payments from DB into the in-memory cache.
  3. Wire real bank adapters → AIS & PIS use-case orchestrators.
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

# ── Infrastructure: Real Adapters (Phase 3) ────────────────────────────────────
from backend.infrastructure.adapters.banks.coop_cbs import CoopCBSAdapter
from backend.infrastructure.adapters.banks.cbe_cbs import CBECBSAdapter
from backend.infrastructure.adapters.banks.wegagen_cbs import WegagenCBSAdapter
from backend.infrastructure.adapters.identity.fayda import FaydaAdapter
from backend.infrastructure.adapters.router.smart_router import SmartRouter
from backend.infrastructure.database.sqlite_repo import SQLiteRepository

# ── Application: Use-Case Orchestrators ───────────────────────────────────────
from backend.application.use_cases.ais_service import AISService
from backend.application.use_cases.pis_service import PISService

# ── Domain ────────────────────────────────────────────────────────────────────
from backend.domain.models.account import BankID

# ── Presentation: API Routers ─────────────────────────────────────────────────
from backend.presentation.api_v1 import accounts, auth, handles, payments, webhooks

# ══════════════════════════════════════════════════════════════════════════════
# Singleton instances (module-level, created once at startup)
# ══════════════════════════════════════════════════════════════════════════════

_repo: SQLiteRepository | None = None
_ais_service: AISService | None = None
_pis_service: PISService | None = None
_identity_port: FaydaAdapter | None = None


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


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Lifespan — Boot & Shutdown
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Wire the full DI graph and restore DB state on startup."""
    global _repo, _ais_service, _pis_service, _identity_port

    # 1. Database
    _repo = SQLiteRepository(db_url=settings.DATABASE_URL)

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

    # 6. Restore in-memory payment cache from SQLite
    restored = _repo.load_all_payments()
    payments._payment_store.update(restored)
    print(f"✅ Gateway started — {len(restored)} payments restored from DB.")

    yield  # ← Server is running

    # Shutdown: nothing to clean up for SQLite
    print("Gateway shutting down.")


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Application
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Kifiya Open Consent Gateway",
    description=(
        "## Ethiopia's first unified Open Banking API standard.\n\n"
        "Provides standardised access to account information (AIS) and payment "
        "initiation (PIS) across multiple Ethiopian banking rails via a single API.\n\n"
        "### Quick-start (mock CBS mode)\n"
        "1. **Auth** — `POST /v1/auth/fayda` with any 14-digit FIN → get `session_id`\n"
        "2. **Confirm OTP** — `POST /v1/auth/fayda/confirm` with OTP `123456` → get a **real signed JWT**\n"
        "3. **AIS** — `GET /v1/accounts` with `Bearer <jwt>` → see balances across COOP, CBE, Wegagen\n"
        "4. **PIS** — `POST /v1/payments/initiate` → `verify` → `order` → `POST /v1/callbacks`\n\n"
        "### Phase 3 upgrades\n"
        "- Real HS256 JWT tokens (PyJWT) with expiry, scopes, KYC level\n"
        "- SQLite persistence — payments survive server restarts\n"
        "- JWT revocation tracked in DB\n"
        "- Live health_check() polling in Smart Router with rolling uptime scores\n"
        "- Bank adapters simulate distinct proprietary API formats per bank\n\n"
        "### Architecture\n"
        "Clean + Hexagonal. Dependencies point strictly inward.\n"
        "`domain ← application ← infrastructure ← presentation`"
    ),
    version="0.3.0-alpha",
    contact={"name": "Kifiya Financial Technologies", "url": "https://kifiya.com"},
    license_info={"name": "Proprietary"},
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount API v1 Routers ───────────────────────────────────────────────────────
API_V1_PREFIX = "/v1"
app.include_router(auth.router,     prefix=API_V1_PREFIX)
app.include_router(handles.router,  prefix=API_V1_PREFIX)
app.include_router(accounts.router, prefix=API_V1_PREFIX)
app.include_router(payments.router, prefix=API_V1_PREFIX)
app.include_router(webhooks.router, prefix=API_V1_PREFIX)



# ── Root health check ──────────────────────────────────────────────────────────
@app.get("/", tags=["⚙️ System"], summary="Health check")
def root():
    """Returns gateway status, registered rails, and DB path."""
    return {
        "service": "Kifiya Open Consent Gateway",
        "version": "0.3.0-alpha",
        "status": "operational",
        "phase": "3 — Real adapters + SQLite + JWT",
        "registered_rails": ["COOP", "CBE", "WEGAGEN"],
        "database": settings.DATABASE_URL,
        "docs": "/docs",
        "redoc": "/redoc",
    }
