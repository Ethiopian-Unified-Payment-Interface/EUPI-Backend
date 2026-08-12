# EUPI: Ethiopian Unified Payment Integration

> Ethiopia's first unified Open Banking API standard

EUPI is a comprehensive Open Banking platform that sits on top of existing Core Banking System (CBS) integrations for major Ethiopian banks (Cooperative Bank of Oromia, Commercial Bank of Ethiopia, and Wegagen Bank). It provides standardized access to Account Information (AIS) and Payment Initiation (PIS) via a single API, abstracting away the underlying proprietary bank interfaces. It also includes a Super App platform enabling seamless P2P transfers between registered users.

The system is built using a strict **Clean Architecture / Hexagonal (Ports & Adapters)** pattern to ensure high testability, domain isolation, and decoupled infrastructure components.

---

## 🚀 Core Capabilities

1. **AIS (Account Information Service)**: Unified access to account balances and up to 1-year transaction history across all connected banks.
2. **PIS (Payment Initiation Service)**: Standardized 4-step payment lifecycle (Initiate → Verify → Order → Callback).
3. **Identity Engine**: eKYC via Ethiopia's Fayda National ID system with real signed JWT tokens.
4. **Smart Router**: Intelligent payment routing that scores banks by live uptime, latency, and transaction cost with circuit breaker functionality.
5. **Super App Platform**: User registration, bank account linking, and P2P transfers by username.

---

## 🛠 Tech Stack

| Component     | Technology |
|---------------|------------|
| **Backend**   | FastAPI, Python 3.12+ |
| **Validation**| Pydantic v2 |
| **Database**  | SQLAlchemy 2.0 + SQLite (MVP) |
| **Auth**      | PyJWT (HS256 signed tokens) |
| **Config**    | python-dotenv |

---

## 🏛 Architecture

The project strictly follows a 4-layer Clean Architecture. Dependency arrows point inward: inner layers never import from outer layers.

- **Layer 1 (Domain)**: Pure Pydantic models — `Account`, `Transaction`, `Payment`, `Identity`, `User`, `LinkedAccount`
- **Layer 2 (Application)**: Abstract ports (`BankPort`, `IdentityPort`, `RoutingPort`, `UserRepositoryPort`, `AccountLinkRepositoryPort`) + use-case orchestrators (`AISService`, `PISService`, `UserRegistrationService`, `AccountLinkingService`, `SuperAppTransferService`)
- **Layer 3 (Infrastructure)**: Concrete adapters — per-bank CBS adapters (Coop, CBE, Wegagen), `FaydaAdapter`, `SmartRouter`, SQLite repositories, JWT handler, mock Fayda registry
- **Layer 4 (Presentation)**: FastAPI route handlers in `api_v1/`

### Project Structure

```text
backend/
├── main.py                     # COMPOSITION ROOT - Wires all layers together
├── config.py                   # Environment variable settings
├── domain/                     # 🟢 LAYER 1 — Enterprise Business Rules
│   └── models/                 # Pure Pydantic models
├── application/                # 🟡 LAYER 2 — Application Business Rules
│   ├── ports/                  # Abstract interfaces
│   └── use_cases/              # Orchestrators/Services
├── infrastructure/             # 🟠 LAYER 3 — Infrastructure / Driven Adapters
│   ├── adapters/               # Concrete CBS, identity, and router adapters
│   ├── auth/                   # JWT generation and validation
│   ├── database/               # SQLAlchemy models and repositories
│   └── mock_data/              # Mock registry data for development
└── presentation/               # 🔵 LAYER 4 — Presentation / Driving Adapters
    └── api_v1/                 # FastAPI REST endpoints
```

---

## 🔌 API Endpoints (v1)

### Auth
- `POST /v1/auth/fayda` — Initiate Fayda eKYC verification (accepts 14-digit FIN + phone number)
- `POST /v1/auth/fayda/confirm` — Confirm OTP and receive signed JWT

### AIS (Account Information)
- `GET /v1/accounts` — Get aggregated balances across all banks (requires Bearer JWT)
- `GET /v1/accounts/{bank_id}/{account_number}` — Get balance for a specific account
- `GET /v1/accounts/{bank_id}/{account_number}/transactions` — Get transaction history

### PIS (Payment Initiation)
- `POST /v1/payments/initiate` — Step 1: Create payment (→ PENDING)
- `POST /v1/payments/{payment_id}/verify` — Step 2: Verify consent (→ VERIFIED)
- `POST /v1/payments/{payment_id}/order` — Step 3: Submit to bank (→ ORDERED)
- `GET /v1/payments/{payment_id}` — Get payment status
- `POST /v1/payments/{payment_id}/cancel` — Cancel a payment

### Webhooks
- `POST /v1/callbacks` — Receive bank callback to finalize payment (→ SUCCESS/FAILED)

### System
- `GET /` — Health check

---

## ⚙️ Environment Variables

The system is configured via a `.env` file. Below are the variables derived from `.env.example`:

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | Secret used for signing JWT tokens |
| `JWT_TOKEN_TTL_SECONDS` | Time to live for JWT tokens (default: 3600) |
| `DATABASE_URL` | Connection string for the database (default: `sqlite:///./kifiya_gateway.db`) |
| `COOP_CBS_API_KEY` | API key for Cooperative Bank of Oromia integration |
| `CBE_CBS_API_KEY` | API key for Commercial Bank of Ethiopia integration |
| `WEGAGEN_CBS_API_KEY` | API key for Wegagen Bank integration |
| `FAYDA_API_BASE_URL` | Base URL for the Fayda national ID system API |
| `FAYDA_CLIENT_ID` | Client ID for Fayda integration |
| `FAYDA_CLIENT_SECRET` | Client secret for Fayda integration |
| `ROUTER_WEIGHT_UPTIME` | Routing algorithm weight for bank uptime (must sum to 1.0 with others) |
| `ROUTER_WEIGHT_LATENCY` | Routing algorithm weight for bank latency (must sum to 1.0 with others) |
| `ROUTER_WEIGHT_COST` | Routing algorithm weight for transaction cost (must sum to 1.0 with others) |
| `DEBUG` | Enable/disable debug mode |
| `CORS_ORIGINS` | Allowed CORS origins for the API (e.g., `http://localhost:3000`) |

---

## 🏃 Quick Start (Local Development)

1. **Clone the repo**
2. **Create a virtual environment**: 
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. **Install dependencies**: 
   ```bash
   pip install -r requirements.txt
   ```
4. **Setup environment variables**: 
   ```bash
   cp .env.example .env
   ```
5. **Run the server**: 
   ```bash
   uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
   ```
6. **Open Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🧪 Testing the API

Here is a quick walkthrough to test the core flows using the mock data:

1. **Auth**: 
   Send a `POST` request to `/v1/auth/fayda` with the payload:
   ```json
   {"fin": "12345678901234", "phone_number": "+251911234567", "consent_scope": "accounts:read,transactions:read"}
   ```
   *Returns a `session_id`.*

2. **Confirm Auth**: 
   Send a `POST` request to `/v1/auth/fayda/confirm` with:
   ```json
   {"session_id": "<from step 1>", "otp_code": "123456", "fin": "12345678901234"}
   ```
   *Returns a `JWT token`.*

3. **AIS**: 
   Send a `GET` request to `/v1/accounts` with header `Authorization: Bearer <jwt>`.
   *Returns balances across COOP, CBE, and Wegagen.*

4. **PIS**: 
   Send a `POST` request to `/v1/payments/initiate` using the Bearer token to initiate a payment.

### Mock Data Details
- 12 test identities exist in the Fayda registry. (Use FIN `12345678901234` for testing).
- The OTP is always `123456` in development mode.
- Banks return deterministic mock data seeded by account number.
- Connected banks for testing: COOP, CBE, WEGAGEN.

### Database Operations
- A SQLite database is auto-created at `kifiya_gateway.db`.
- It contains 5 tables: `payments`, `consent_tokens`, `webhook_events`, `users`, `linked_accounts`.
- Payments are persisted and survive server restarts.

---

*Proprietary — Kifiya Financial Technologies*
