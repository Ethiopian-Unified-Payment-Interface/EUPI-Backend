# EUPI: Ethiopian Unified Payment Integration

> **High-Performance Unified Payment Switch, Interoperable Banking Gateway, Super App & Developer Platform**

The **Ethiopian Unified Payment Integration (EUPI)** is a unified financial transaction backbone and payment switch for Ethiopia. It sits on top of Core Banking System (CBS) integrations across 6 major commercial banks (**Commercial Bank of Ethiopia (CBE)**, **Cooperative Bank of Oromia (Co-op)**, **Wegagen Bank**, **Awash Bank**, **Bank of Abyssinia**, and **Berhan Bank**). 

EUPI provides a standardized API for Account Information Services (AIS), Payment Initiation Services (PIS), citizen Super App peer-to-peer (P2P) transfers, an immutable double-entry financial ledger, and a comprehensive self-service Developer & TPP Platform.

---

## 🏛 Clean & Hexagonal Architecture

The platform is strictly architected using **Clean Architecture** and **Hexagonal Architecture (Ports and Adapters)**. Inner business domains have zero awareness of external frameworks, HTTP clients, or databases.

```
       ┌──────────────────────────────────────────────────────────┐
       │   LAYER 4: Presentation / Driving Adapters               │
       │   FastAPI Routers: Core v1, Super App, OAuth2, Developer │
       └────────────────────────────┬─────────────────────────────┘
                                    │
       ┌────────────────────────────▼─────────────────────────────┐
       │   LAYER 2: Application / Use Cases & Abstract Ports      │
       │   AISService, PISService, ConsentService, LedgerService  │
       │   DeveloperAuthService, SuperAppTransferService, etc.    │
       └────────────────────────────┬─────────────────────────────┘
                                    │
       ┌────────────────────────────▼─────────────────────────────┐
       │   LAYER 1: Domain / Enterprise Business Rules            │
       │   Payment, Account, User, Consent, LedgerEntry, FeeRule  │
       │   (Pure Python + Pydantic. Zero External Dependencies)   │
       └────────────────────────────▲─────────────────────────────┘
                                    │
       ┌────────────────────────────┴─────────────────────────────┐
       │   LAYER 3: Infrastructure / Driven Adapters              │
       │   PostgreSQL Repositories, 6 Bank CBS Adapters,          │
       │   Fayda Identity Adapter, Smart Router, HMAC Webhooks    │
       └──────────────────────────────────────────────────────────┘
```

---

## 🚀 Core Capabilities

1. **Payment Initiation Service (PIS)**:
   * 4-stage deterministic payment state machine (`PENDING` $\rightarrow$ `VERIFIED` $\rightarrow$ `ORDERED` $\rightarrow$ `SUCCESS`/`FAILED`).
   * Real-time bank settlement callbacks with automated webhook dispatch.
2. **Account Information Service (AIS)**:
   * Universal balance and transaction aggregation fanned out across all Ethiopian banks in parallel worker threads with graceful degradation.
3. **Super App Consumer Platform**:
   * eKYC onboarding via Ethiopia's **Fayda National ID** system.
   * Citizen handle-based (`username@eupi`) P2P transfers with recipient pre-flight lookup and native 6-digit Argon2id PIN authorization.
   * Multi-bank account discovery and default sending/receiving routing.
4. **Smart Router**:
   * Dynamic scoring algorithm evaluating live CBS latency, rolling uptime availability, and transaction fee costs:
     $$\text{Score} = (0.50 \cdot Uptime) + (0.30 \cdot Latency) + (0.20 \cdot Cost)$$
   * Automatic circuit breaker excluding banks with $< 50\%$ rolling availability.
5. **Open Banking OAuth 2.0 Engine (RFC 6749 & RFC 7636)**:
   * Authorization Code Grant with **PKCE S256** verification.
   * Pseudonymous per-app user identifiers (`psu_id`), preventing cross-app user tracking.
   * Token Introspection (**RFC 7662**) and Token Revocation (**RFC 7009**).
6. **Developer Portal & TPP Platform (`/v1/developer/*`)**:
   * Self-service developer signup, email verification, and **instant Sandbox app provisioning**.
   * One-time client secret generation and rotation.
   * Webhook delivery inspector with payload viewer and manual **"Resend Webhook"** retry tool.
   * Tenant-scoped Payment Explorer and volume analytics.
   * Production KYB submission pipeline directly bridged to the Admin Portal.
7. **Double-Entry Financial Accounting Ledger**:
   * Append-only, balance-enforced ledger ensuring mathematically exact accounting:
     $$\sum \text{Debits} - \sum \text{Credits} = 0.00$$
8. **Administrative Control Portal (`/v1/admin/*`)**:
   * Bank rail enabling/disabling, fee rule versioning, KYB compliance reviews, and immutable audit trails.

---

## 🛠 Tech Stack

| Category | Technology |
| :--- | :--- |
| **Language** | Python 3.12+ |
| **API Framework** | FastAPI `0.111.0` + Uvicorn ASGI Server |
| **Database** | PostgreSQL 16 (Relational ACID & Fixed-Point `NUMERIC`) |
| **ORM & Migrations** | SQLAlchemy 2.0 + Psycopg 3 + Alembic (`alembic upgrade head`) |
| **Security & PINs** | `argon2-cffi` (Argon2id memory-hard hashing) |
| **Identity Vault** | Fernet Symmetric Encryption (AES-128-CBC) + HMAC-SHA256 Blind Indexing |
| **Webhooks** | Asynchronous worker with HMAC-SHA256 signatures (`X-EUPI-Signature`) & exponential backoff |
| **Containerization** | Docker & Docker Compose |

---

## 🔌 API Surfaces Reference

### 1. Core Banking APIs (`/v1`)
* `POST /v1/auth/request-ekyc` — Initiate Fayda eKYC verification
* `POST /v1/auth/confirm-ekyc` — Confirm OTP and receive signed `gateway_access` JWT
* `GET /v1/accounts/balances` — Aggregated balances across all connected banks
* `GET /v1/accounts/{bank_id}/{account_number}` — Specific account balance lookup
* `POST /v1/payments/initiate` — Step 1: Create payment (`PENDING`)
* `POST /v1/payments/{payment_id}/verify` — Step 2: Verify consent & balance (`VERIFIED`)
* `POST /v1/payments/{payment_id}/order` — Step 3: Dispatch transfer to CBS (`ORDERED`)
* `GET /v1/payments/{payment_id}` — Get payment status & failure reason
* `POST /v1/callbacks` — Bank settlement callback endpoint (`SUCCESS`/`FAILED`)

### 2. Super App Platform (`/v1/superapp`)
* `POST /v1/superapp/users/register` — Super App citizen registration with 6-digit PIN
* `POST /v1/superapp/users/login` — Login with username & PIN
* `GET /v1/superapp/users/me` — Authenticated profile metadata
* `GET /v1/superapp/users/profile/{username}` — Public handle resolution for P2P transfers
* `GET /v1/superapp/linked-accounts` — List citizen's linked bank accounts
* `POST /v1/superapp/linked-accounts` — Link and verify a bank account
* `POST /v1/superapp/transfers` — Execute instant P2P transfer by handle with PIN
* `GET /v1/superapp/consents` — View active third-party app permissions & revoke

### 3. Open Banking OAuth2 Server (`/v1/oauth`)
* `GET /v1/oauth/authorize` — OAuth 2.0 consent authorization request (PKCE S256)
* `POST /v1/oauth/consent/{request_id}/approve` — Citizen scope approval with PIN
* `POST /v1/oauth/token` — Token issuance (`client_credentials` & `authorization_code`)
* `POST /v1/oauth/introspect` — RFC 7662 Token Introspection
* `POST /v1/oauth/revoke` — RFC 7009 Token Revocation

### 4. Developer Portal & Console (`/v1/developer`)
* `POST /v1/developer/register` — Self-service developer signup
* `POST /v1/developer/verify-email` — Email verification with instant Sandbox credentials
* `POST /v1/developer/login` — Developer session authentication
* `GET /v1/developer/me` — Developer profile & application summary
* `GET /v1/developer/apps` — List developer applications
* `POST /v1/developer/apps` — Create a new application
* `POST /v1/developer/apps/{app_id}/rotate-secret` — Rotate client secret with one-time view
* `GET /v1/developer/apps/{app_id}/webhooks` — Live webhook delivery logs
* `POST /v1/developer/webhooks/{event_id}/retry` — Manual test retry for webhook delivery
* `GET /v1/developer/apps/{app_id}/payments` — Tenant-scoped payment explorer
* `GET /v1/developer/apps/{app_id}/analytics` — Transaction volume, success rate, and latency metrics
* `GET /v1/developer/apps/{app_id}/consents` — Aggregated consent distribution (`psu_id`)
* `POST /v1/developer/kyb-requests` — Submit KYB business verification for production
* `GET /v1/developer/kyb-status` — Track compliance review state

### 5. Administrative Operations (`/v1/admin`)
* `POST /v1/admin/auth/login` — Admin session login
* `GET /v1/admin/dashboard/summary` — Real-time gateway volume & operational telemetry
* `GET /v1/admin/banks` / `PUT /v1/admin/banks/{bank_id}` — Configure bank CBS rails
* `GET /v1/admin/developers/kyb-requests` — Compliance KYB review queue
* `PUT /v1/admin/developers/kyb-requests/{kyb_id}` — Approve/Reject KYB requests
* `GET /v1/admin/ledger/payments/{payment_id}/entries` — Inspect double-entry ledger entries

---

## 🏃 Running the System

### Docker Compose (Recommended)

From the project root:

```bash
# Start all containers (Backend, Postgres, Admin Portal, Adminer DB UI)
docker compose up --build -d

# Check operational status
docker compose ps
```

#### Service URLs:
* **Gateway API & Telemetry**: `http://localhost:8000/`
* **Swagger Interactive Docs**: `http://localhost:8000/docs`
* **ReDoc Technical Specs**: `http://localhost:8000/redoc`
* **Admin Portal UI**: `http://localhost:3001`
* **Adminer Web Database Manager**: `http://localhost:8080`

---

## 🧪 Testing the Platform

### Running Automated Test Suite

```bash
# Execute the full 100-test pytest suite
docker compose exec -e PYTHONPATH=. backend /home/eupi/.local/bin/pytest tests/
```

### Mock Test Data:

* **Mock Fayda National ID Registry**:
  * `12345678901234` — Abebe Girma Tadesse (`+251911234567`, Male)
  * `23456789012345` — Selamawit Bekele Hailu (`+251922345678`, Female)
  * `21872187218777` — Daniel Kebede Woldetsadik (`+251904267039`, Male)
* **Development OTP**: `123456`
* **Default Admin Operator**:
  * Email: `admin@kifiya.com`
  * Password: `ChangeMe!Dev123`
* **PostgreSQL Database Credentials**:
  * Host: `localhost:5432` (or `postgres` inside Docker network)
  * Database: `eupi`
  * Username: `eupi`
  * Password: `eupi-local-development-password`

---

*Proprietary — Kifiya Financial Technologies*
