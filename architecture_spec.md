# EUPI: Ethiopian Unified Payment Integration — Enterprise Specification
**Master Context File for Autonomous Agent (`agy`)**

## 1. Project Mission & Scope
*   **Objective:** Build Ethiopia’s first unified Open Banking API standard. The system sits on top of existing Core Banking System (CBS) integrations (e.g., Coop, Wegagen, CBE, Awash). 
*   **Core Capabilities:**
    1.  **AIS (Account Info):** Unified access to account balances, KYC metadata, and 1-year transaction history across all banks.
    2.  **PIS (Payment Initiation):** Standardized 4-step lifecycle (Initiate -> Verify -> Order -> Callback).
    3.  **Identity Engine:** Unified eKYC (for customers via Fayda National ID) and KYB (for developer onboarding).
    4.  **Smart Routing System:** An intelligent payment router that evaluates latency, uptime, and transaction costs to dynamically select the best banking rail.

## 2. Tech Stack Ecosystem
*   **Backend:** FastAPI (Python), Pydantic, SQLAlchemy (SQLite for MVP).
*   **Frontend (Dev Portal):** Next.js (React), Tailwind CSS.
*   **Mobile (Super App):** Flutter (Dart).

## 3. Architecture Blueprint: Clean + Hexagonal
*Agent Instruction: Dependencies must strictly point INWARD. Outer layers depend on inner layers. Inner layers NEVER import from outer layers.*

```text
kifiya_open_gateway/
├── backend/
│   ├── main.py                  # Mounts FastAPI routers and initializes the database.
│   │
│   ├── domain/                  # 🟢 LAYER 1: ENTERPRISE BUSINESS RULES
│   │   │                        # Strict Rule: No external framework imports (No FastAPI, no SQL).
│   │   ├── models/
│   │   │   ├── account.py       # Defines standard Account schema (balance, currency, bank_id).
│   │   │   ├── transaction.py   # Defines standardized ISO 20022 transaction schema.
│   │   │   ├── payment.py       # Defines payment states (PENDING, VERIFIED, ORDERED, SUCCESS).
│   │   │   └── identity.py      # Defines Fayda eKYC schemas (Name, KYC Level).
│   │   │
│   ├── application/             # 🟡 LAYER 2: PORTS & USE CASES
│   │   │                        # Strict Rule: Orchestrates logic using abstract interfaces, not real APIs.
│   │   ├── ports/               # The "Contracts" (Abstract Base Classes)
│   │   │   ├── bank_port.py     # abstract def get_balance(), abstract def transfer()
│   │   │   ├── identity_port.py # abstract def verify_fayda_kyc()
│   │   │   └── routing_port.py  # abstract def get_optimal_route(amount, target_bank)
│   │   ├── use_cases/           # The "Business Logic Orchestrators"
│   │   │   ├── ais_service.py   # Loops through all bank ports, fetches balances, normalizes data.
│   │   │   └── pis_service.py   # Executes the 4-step Initiate -> Verify -> Order -> Callback flow.
│   │
│   ├── infrastructure/          # 🔴 LAYER 3: DRIVEN ADAPTERS
│   │   │                        # Strict Rule: This is the ONLY layer allowed to make HTTP/DB calls.
│   │   ├── adapters/            
│   │   │   ├── banks/
│   │   │   │   ├── coop_cbs.py    # Inherits from bank_port. Mocks Coop Bank API responses.
│   │   │   │   ├── cbe_cbs.py     # Inherits from bank_port. Mocks CBE API responses.
│   │   │   │   └── wegagen_cbs.py # Inherits from bank_port. Mocks Wegagen API responses.
│   │   │   ├── identity/
│   │   │   │   └── fayda.py       # Inherits from identity_port. Mocks Fayda FIN/OTP verification.
│   │   │   └── router/
│   │   │       └── smart_router.py # Inherits from routing_port. Logic matrix to select best bank adapter.
│   │   └── database/
│   │       └── sqlite_repo.py     # SQLAlchemy configuration for storing tokens and webhooks.
│   │
│   └── presentation/            # 🔵 LAYER 4: DRIVING ADAPTERS
│       │                        # Strict Rule: API routing only. Unpacks JSON, calls Use Cases, returns 200/400.
│       ├── api_v1/
│       │   ├── accounts.py      # GET /v1/accounts (Requires Fayda Bearer Token).
│       │   ├── payments.py      # POST /v1/payments/initiate (Requires Developer API Key).
│       │   ├── webhooks.py      # POST /v1/callbacks (Fires async receipts to developers).
│       │   └── auth.py          # POST /v1/auth/fayda (Returns JWT to the user).
