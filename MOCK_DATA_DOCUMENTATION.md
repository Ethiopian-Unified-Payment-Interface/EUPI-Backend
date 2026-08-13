# EUPI Backend — Mock Data & Integration Guide for Frontend Engineers

> **Project**: EUPI (Ethiopian Unified Payment Integration) — Kifiya Open Gateway  
> **Target Audience**: Frontend Engineers building the Super App & Partner TPP Applications  
> **Server Base URL**: `http://localhost:8000`  
> **Interactive Swagger Documentation**: `http://localhost:8000/docs`

---

## Table of Contents

1. [Overview & Mock Architecture](#1-overview--mock-architecture)
2. [Fayda National ID Mock Registry & OTP Credentials](#2-fayda-national-id-mock-registry--otp-credentials)
3. [Mock Core Banking System (CBS) Adapters](#3-mock-core-banking-system-cbs-adapters)
   - 3.1. [Integrated Mock Banks & Configuration Settings](#31-integrated-mock-banks--configuration-settings)
   - 3.2. [Proprietary API Formats & Structural Differences](#32-proprietary-api-formats--structural-differences)
   - 3.3. [Domain Model Normalization (Ports & Adapters)](#33-how-we-normalize-banks-using-hexagonal-ports--adapters)
   - 3.4. [Production Migration: Swapping Mocks for Live CBS Systems](#34-production-migration-how-to-swap-mock-adapters-for-real-cbs-systems)
   - 3.5. [User → Designated Bank Accounts Mapping Matrix](#35-user--designated-bank-accounts-mapping-matrix)
4. [Super App User Handles & PIN Sessions](#4-super-app-user-handles--pin-sessions)
5. [Smart Router & Bank Rail Statuses](#5-smart-router--bank-rail-statuses)
6. [Step-by-Step Frontend Testing Flows](#6-step-by-step-frontend-testing-flows)

---

## 1. Overview & Mock Architecture

The **EUPI Gateway** follows strict Clean Architecture. While production infrastructure relies on live bank CBS APIs and official Fayda OIDC endpoints, the backend provides **deterministic mock adapters** in development mode so frontend teams can test all features end-to-end without external dependencies.

- **Deterministic Identity**: Each 14-digit Fayda FIN maps to a fixed Ethiopian citizen identity.
- **Stateful Bank Account Matching**: Bank account numbers return specific account holder names. The gateway verifies that the legal name on a bank account matches the Fayda National ID identity before allowing account linking.
- **Fixed Development OTP**: In development/debug mode, the OTP for **all** Fayda sessions is **`123456`**.

---

## 2. Fayda National ID Mock Registry & OTP Credentials

### Fixed Development OTP
- **OTP Code**: **`123456`** (valid for all 14-digit FINs during development)
- **OTP Expiration**: 5 minutes (`300` seconds) per session ID.

### Test Citizen Identities Dataset

Use these 14-digit Fayda Identification Numbers (FINs) when testing registration (`POST /superapp/users/register/request-otp`) or Fayda eKYC authentication (`POST /v1/auth/fayda`).

| 14-Digit Fayda FIN | Full Legal Name | Registered Phone | Date of Birth | Gender |
| :--- | :--- | :--- | :--- | :--- |
| **`12345678901234`** *(Sender Test)* | Abebe Girma Tadesse | `+251911234567` | 1990-05-15 | MALE |
| **`21872187218777`** | Daniel Kebede Woldetsadik | `+251904267039` | 2003-03-11 | MALE |
| **`23456789012345`** *(Recipient Test)* | Selamawit Bekele Hailu | `+251922345678` | 1995-08-22 | FEMALE |
| **`34567890123456`** | Tewodros Kassahun | `+251933456789` | 1988-11-10 | MALE |
| **`45678901234567`** | Betelhem Desalegn | `+251944567890` | 1992-02-14 | FEMALE |
| **`56789012345678`** | Yared Ashenafi | `+251955678901` | 1985-06-30 | MALE |
| **`67890123456789`** | Mekdes Worku | `+251966789012` | 1998-09-05 | FEMALE |
| **`78901234567890`** | Henok Tilahun | `+251977890123` | 1991-12-25 | MALE |
| **`89012345678901`** | Hirut Zewdu | `+251988901234` | 1987-04-18 | FEMALE |
| **`90123456789012`** | Ermias Tsegaye | `+251999012345` | 1994-07-12 | MALE |
| **`01234567890123`** | Tigist Alemu | `+251910123456` | 1996-03-08 | FEMALE |
| **`11223344556677`** | Abel Berhanu | `+251920234567` | 1989-10-20 | MALE |
| **`22334455667788`** | Eden Tesfaye | `+251930345678` | 1993-01-15 | FEMALE |

> **Note**: Any FIN **not** present in this table (e.g., `99999999999999`) will be rejected by the backend with **HTTP 400 Bad Request** (`FaydaIdentityNotFoundError`).

---

## 3. Mock Core Banking System (CBS) Adapters

The **EUPI Gateway** integrates 6 primary Ethiopian commercial bank adapters operating in Layer 3 (Infrastructure).

---

### 3.1. Integrated Mock Banks & Configuration Settings

Each bank adapter is configured via runtime settings (`backend/config.py`) sourced from environment variables:

| Bank Code (`BankID`) | Full Institution Name | Config Variable (`backend/config.py`) | Default API Key / Token Header | Source File |
| :--- | :--- | :--- | :--- | :--- |
| **`COOP`** | Cooperative Bank of Oromia | `COOP_CBS_API_KEY` | `X-COOP-API-Key: mock-coop-key` | [`coop_cbs.py`](file:///home/grace/Dev/kifiya/hackathon/kifiya-open-gateway/backend/infrastructure/adapters/banks/coop_cbs.py) |
| **`CBE`** | Commercial Bank of Ethiopia | `CBE_CBS_API_KEY` | `X-CBE-Auth-Token: mock-cbe-key` | [`cbe_cbs.py`](file:///home/grace/Dev/kifiya/hackathon/kifiya-open-gateway/backend/infrastructure/adapters/banks/cbe_cbs.py) |
| **`WEGAGEN`** | Wegagen Bank | `WEGAGEN_CBS_API_KEY` | `Authorization: Bearer mock-wegagen-key` | [`wegagen_cbs.py`](file:///home/grace/Dev/kifiya/hackathon/kifiya-open-gateway/backend/infrastructure/adapters/banks/wegagen_cbs.py) |
| **`AWASH`** | Awash Bank | `AWASH_CBS_API_KEY` | `X-Awash-Key: mock-awash-key` | [`awash_cbs.py`](file:///home/grace/Dev/kifiya/hackathon/kifiya-open-gateway/backend/infrastructure/adapters/banks/awash_cbs.py) |
| **`ABYSSINIA`** | Bank of Abyssinia (Abisiniya) | `ABYSSINIA_CBS_API_KEY` | `X-Abyssinia-Token: mock-abyssinia-key` | [`abyssinia_cbs.py`](file:///home/grace/Dev/kifiya/hackathon/kifiya-open-gateway/backend/infrastructure/adapters/banks/abyssinia_cbs.py) |
| **`BERHAN`** | Berhan Bank | `BERHAN_CBS_API_KEY` | `X-Berhan-Auth: mock-berhan-key` | [`berhan_cbs.py`](file:///home/grace/Dev/kifiya/hackathon/kifiya-open-gateway/backend/infrastructure/adapters/banks/berhan_cbs.py) |

---

### 3.2. Proprietary API Formats & Structural Differences

Because Ethiopian commercial banks run distinct Core Banking Systems (Flexcube, Temenos T24, Finacle), each bank's native API exposes different JSON schemas, authentication headers, error codes, and field naming conventions:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             PROPRIETARY CBS FORMATS                              │
├───────────────┬──────────────────────────────────┬───────────────────────────────┤
│ Bank Adapter  │ Native Payload Keys              │ Header / Auth Protocol        │
├───────────────┼──────────────────────────────────┼───────────────────────────────┤
│ COOP          │ account_no, available_bal,       │ Header: X-COOP-API-Key        │
│               │ hold_amount, cust_name           │                               │
├───────────────┼──────────────────────────────────┼───────────────────────────────┤
│ CBE           │ accountIdentifier, balances[],   │ Header: X-CBE-Auth-Token      │
│               │ balanceType: "BOOK", "AVAIL"     │ ISO-20022 Aligned             │
├───────────────┼──────────────────────────────────┼───────────────────────────────┤
│ WEGAGEN       │ accountDetails: { accNo,         │ Header: Authorization Bearer  │
│               │ availBal, legBal, cc, title }    │ SOAP-wrapped REST JSON        │
├───────────────┼──────────────────────────────────┼───────────────────────────────┤
│ AWASH         │ account_info: { acc_num,         │ Header: X-Awash-Key           │
│               │ bal_avail, bal_ledger, curr }    │ Custom JSON                   │
├───────────────┼──────────────────────────────────┼───────────────────────────────┤
│ ABYSSINIA     │ data: { accountId, ownerName,    │ Header: X-Abyssinia-Token     │
│               │ balance: { available, ledger } } │ Modern REST Schema            │
├───────────────┼──────────────────────────────────┼───────────────────────────────┤
│ BERHAN        │ payload: { account_id,           │ Header: X-Berhan-Auth         │
│               │ net_balance, gross_balance }     │ JSON-RPC Style                │
└───────────────┴──────────────────────────────────┴───────────────────────────────┘
```

---

### 3.3. How We Normalize Banks Using Hexagonal Ports & Adapters

To prevent upstream application services (PIS, AIS, Account Linking, Smart Router) from becoming coupled to any single bank's proprietary format, the gateway enforces **Clean Architecture / Hexagonal Architecture (Ports & Adapters)**:

1. **Domain Model Normalization (Layer 1)**:
   [`AccountBalance`](file:///home/grace/Dev/kifiya/hackathon/kifiya-open-gateway/backend/domain/models/account.py#L39-L70) defines the single, standardized enterprise representation:
   ```python
   class AccountBalance(BaseModel):
       account_number: str
       available_balance: Decimal
       ledger_balance: Decimal
       currency: str = "ETB"
       account_name: str
       status: AccountStatus = AccountStatus.ACTIVE
   ```

2. **Abstract Driven Port Interface (Layer 2)**:
   [`BankPort`](file:///home/grace/Dev/kifiya/hackathon/kifiya-open-gateway/backend/application/ports/bank_port.py#L22-L60) defines the strict abstract contract:
   ```python
   class BankPort(ABC):
       @abstractmethod
       def get_balance(self, account_number: str) -> AccountBalance: ...
       @abstractmethod
       def initiate_transfer(self, request: PaymentInitiateRequest) -> PaymentResult: ...
       @abstractmethod
       def health_check(self) -> bool: ...
   ```

3. **Concrete Infrastructure Adapters (Layer 3)**:
   Each bank adapter implements `BankPort`. Inside `get_balance()`, the adapter converts the bank's proprietary JSON into the unified `AccountBalance` domain object:
   - **COOP Adapter**: Maps `available_bal` $\rightarrow$ `available_balance`, `cust_name` $\rightarrow$ `account_name`.
   - **CBE Adapter**: Extracts `balanceType == "AVAIL"` $\rightarrow$ `available_balance`, `accountHolder` $\rightarrow$ `account_name`.
   - **Wegagen Adapter**: Maps `accountDetails.availBal` $\rightarrow$ `available_balance`, `title` $\rightarrow$ `account_name`.
   - **Awash Adapter**: Maps `account_info.bal_avail` $\rightarrow$ `available_balance`, `holder_name` $\rightarrow$ `account_name`.
   - **Abyssinia Adapter**: Maps `data.balance.available` $\rightarrow$ `available_balance`, `ownerName` $\rightarrow$ `account_name`.
   - **Berhan Adapter**: Maps `payload.net_balance` $\rightarrow$ `available_balance`, `owner_fullname` $\rightarrow$ `account_name`.

---

### 3.4. Production Migration: How to Swap Mock Adapters for Real CBS Systems

Because application services and route handlers interact **exclusively via the `BankPort` interface**, zero code changes are required in domain models or use cases when deploying live production bank integrations.

#### Step-by-Step Production Swap:

1. **Create the Production Adapter Class**:
   Create a new file (e.g., `backend/infrastructure/adapters/banks/live_coop_cbs.py`):
   ```python
   import httpx
   from backend.application.ports.bank_port import BankPort
   from backend.domain.models.account import AccountBalance, AccountStatus

   class LiveCoopCBSAdapter(BankPort):
       def __init__(self, base_url: str, api_key: str, cert_path: str) -> None:
           self._client = httpx.Client(
               base_url=base_url,
               headers={"X-COOP-API-Key": api_key},
               verify=cert_path,  # Mutual TLS (mTLS) certificate
           )

       def get_balance(self, account_number: str) -> AccountBalance:
           resp = self._client.get(f"/cbs/v1/accounts/{account_number}/balance")
           resp.raise_for_status()
           data = resp.json()
           return AccountBalance(
               account_number=data["account_no"],
               available_balance=Decimal(str(data["available_bal"])),
               ledger_balance=Decimal(str(data["available_bal"] + data.get("hold_amount", 0))),
               currency=data.get("currency_code", "ETB"),
               account_name=data["cust_name"],
               status=AccountStatus.ACTIVE,
           )
   ```

2. **Update Dependency Injection Container in `main.py`**:
   In `backend/main.py` (inside the `lifespan` startup hook), toggle adapter instantiation based on environment configuration (`settings.DEBUG`):

   ```python
   # backend/main.py
   if settings.DEBUG:
       # Development mode: use mock deterministic adapters
       coop_adapter = CoopCBSAdapter(api_key=settings.COOP_CBS_API_KEY)
   else:
       # Production mode: instantiate live HTTPX adapters with mTLS certs
       coop_adapter = LiveCoopCBSAdapter(
           base_url=settings.COOP_PROD_URL,
           api_key=settings.COOP_CBS_API_KEY,
           cert_path="/etc/ssl/certs/coop_mtls.pem",
       )

   # Register adapter into DI container mapping
   bank_adapters[BankID.COOP] = coop_adapter
   ```

3. **Verification**:
   Run `pytest` or `e2e_test.py`. Because the application layer consumes `BankPort`, the entire P2P transfer, AIS balance aggregation, and Smart Router pipeline operate seamlessly with zero changes!

---

### 3.5. User → Designated Bank Accounts Mapping Matrix

This table shows **all test users and their designated bank accounts across multiple banks**. Use these account numbers when linking bank accounts (`POST /superapp/accounts/link`) for a registered user.

| Citizen Legal Name | Fayda FIN | Phone Number | Bank Code (`bank_id`) | Designated Account Number |
| :--- | :--- | :--- | :--- | :--- |
| **Abebe Girma Tadesse** | `12345678901234` | `+251911234567` | **`COOP`** | `1000234567890` |
| | | | **`CBE`** | `1000111222333` |
| | | | **`AWASH`** | `1000333444555` |
| | | | **`ABYSSINIA`** | `1000666777888` |
| | | | **`WEGAGEN`** | `1000555666777` |
| | | | **`BERHAN`** | `1000111999888` |
| **Selamawit Bekele Hailu** | `23456789012345` | `+251922345678` | **`CBE`** | `1000987654321` |
| | | | **`AWASH`** | `1000444555666` |
| | | | **`ABYSSINIA`** | `1000777888999` |
| | | | **`WEGAGEN`** | `1000888999000` |
| | | | **`BERHAN`** | `1000222888777` |
| **Daniel Kebede Woldetsadik** | `21872187218777` | `+251904267039` | **`COOP`** | `1000101010101` |
| | | | **`CBE`** | `1000202020202` |
| | | | **`ABYSSINIA`** | `1000303030303` |
| **Tewodros Kassahun** | `34567890123456` | `+251933456789` | **`AWASH`** | `1000404040404` |
| | | | **`CBE`** | `1000505050505` |
| | | | **`BERHAN`** | `1000606060606` |
| **Betelhem Desalegn** | `45678901234567` | `+251944567890` | **`WEGAGEN`** | `1000707070707` |
| | | | **`ABYSSINIA`** | `1000808080808` |
| **Yared Ashenafi** | `56789012345678` | `+251955678901` | **`COOP`** | `1000909090909` |
| | | | **`AWASH`** | `1000121212121` |

---

### Bank → Accounts View

| Bank Code (`bank_id`) | Account Number | Account Holder Name | Matches Citizen FIN |
| :--- | :--- | :--- | :--- |
| **`COOP`** | `1000234567890` | ABEBE GIRMA TADESSE | `12345678901234` |
| **`COOP`** | `1000101010101` | DANIEL KEBEDE WOLDETSADIK | `21872187218777` |
| **`COOP`** | `1000909090909` | YARED ASHENAFI | `56789012345678` |
| **`CBE`** | `1000111222333` | ABEBE GIRMA TADESSE | `12345678901234` |
| **`CBE`** | `1000987654321` | SELAMAWIT BEKELE HAILU | `23456789012345` |
| **`CBE`** | `1000202020202` | DANIEL KEBEDE WOLDETSADIK | `21872187218777` |
| **`CBE`** | `1000505050505` | TEWODROS KASSAHUN | `34567890123456` |
| **`AWASH`** | `1000333444555` | ABEBE GIRMA TADESSE | `12345678901234` |
| **`AWASH`** | `1000444555666` | SELAMAWIT BEKELE HAILU | `23456789012345` |
| **`AWASH`** | `1000404040404` | TEWODROS KASSAHUN | `34567890123456` |
| **`AWASH`** | `1000121212121` | YARED ASHENAFI | `56789012345678` |
| **`ABYSSINIA`** | `1000666777888` | ABEBE GIRMA TADESSE | `12345678901234` |
| **`ABYSSINIA`** | `1000777888999` | SELAMAWIT BEKELE HAILU | `23456789012345` |
| **`ABYSSINIA`** | `1000303030303` | DANIEL KEBEDE WOLDETSADIK | `21872187218777` |
| **`ABYSSINIA`** | `1000808080808` | BETELHEM DESALEGN | `45678901234567` |
| **`WEGAGEN`** | `1000555666777` | ABEBE GIRMA TADESSE | `12345678901234` |
| **`WEGAGEN`** | `1000888999000` | SELAMAWIT BEKELE HAILU | `23456789012345` |
| **`WEGAGEN`** | `1000707070707` | BETELHEM DESALEGN | `45678901234567` |
| **`BERHAN`** | `1000111999888` | ABEBE GIRMA TADESSE | `12345678901234` |
| **`BERHAN`** | `1000222888777` | SELAMAWIT BEKELE HAILU | `23456789012345` |
| **`BERHAN`** | `1000606060606` | TEWODROS KASSAHUN | `34567890123456` |

### Dynamic Account Resolution
For testing other accounts, any valid account number string will resolve cleanly with:
- **Status**: `ACTIVE`
- **Simulated Available Balance**: ETB 3,000.00 – ETB 120,000.00
- **Currency**: `ETB`

> **Warning**: Attempting to link an account whose holder name does **not** match the user's Fayda name (e.g. Abebe attempting to link Selamawit's account `1000987654321`) will fail with **HTTP 400 Bad Request** (`AccountOwnerMismatchError`).

---

## 4. Super App User Handles & PIN Sessions

### Username Handle Entry & Automatic Postfix Handling
- Users **only enter their base handle** when registering or performing any action (e.g. `abebe_girma` or `selamawit_bekele`).
- Users **do not need to type `@eupi`**; the backend automatically sanitizes, normalizes, and appends the `@eupi` postfix internally.
- Entering either `abebe_girma` or `abebe_girma@eupi` works transparently across all endpoints (`POST /superapp/users/login`, `POST /superapp/accounts/link`, `POST /superapp/transfers`, `GET /superapp/users/{username}`, etc.).
- Usernames are **case-insensitive primary keys**.

### PIN Login & Session Tokens
- **Login Authentication**: Super App login uses a 6-digit numeric PIN (`POST /superapp/users/login`).
- **Session Header**: Login returns a `session_token`. All protected Super App endpoints require:
  ```http
  Authorization: Bearer <session_token>
  ```
- **Logout**: `POST /superapp/users/logout` revokes the active session token in SQLite.

---

## 5. Smart Router & Bank Rail Statuses

The **Smart Router** continuously calculates real-time rail scores for transfer routing based on:
- **Uptime Score (0 - 100)**: Measured via live health check pings to bank CBS endpoints.
- **Latency Score (0 - 100)**: Measured in milliseconds (lower latency = higher score).
- **Cost Score (0 - 100)**: Transaction fee weighting.

### Registered Bank Rails:
1. `COOP` — Cooperative Bank of Oromia
2. `CBE` — Commercial Bank of Ethiopia
3. `WEGAGEN` — Wegagen Bank
4. `AWASH` — Awash Bank
5. `ABYSSINIA` — Bank of Abyssinia
6. `BERHAN` — Berhan Bank

---

## 6. Step-by-Step Frontend Testing Flows

### Flow A: Super App User Registration (3-Step Flow)

1. **Step 1: Request Registration OTP**:
   ```http
   POST /v1/superapp/users/register/request-otp
   Content-Type: application/json

   {
     "fin": "12345678901234",
     "phone_number": "+251911234567"
   }
   ```
   *Response*: Returns `"session_id": "FAYDA-SES-..."`

2. **Step 2: Verify Registration OTP**:
   ```http
   POST /v1/superapp/users/register/verify-otp
   Content-Type: application/json

   {
     "session_id": "FAYDA-SES-...",
     "otp_code": "123456"
   }
   ```
   *Response*: Returns `"registration_token": "eyJhbGci..."`, `fin`, `full_name`, and `phone_number`.

3. **Step 3: Complete Registration**:
   ```http
   POST /v1/superapp/users/register/complete
   Content-Type: application/json

   {
     "registration_token": "eyJhbGci...",
     "username": "abebe_girma",
     "pin": "123456"
   }
   ```
   *Response*: Creates profile with username `abebe_girma@eupi` and legal name `Abebe Girma Tadesse`.

---

### Flow B: Super App PIN Login & Session Maintenance

1. **Login with 6-Digit PIN** (base handle without typing `@eupi`):
   ```http
   POST /v1/superapp/users/login
   Content-Type: application/json

   {
     "username": "abebe_girma",
     "pin": "123456"
   }
   ```
   *Response*: Returns `"session_token": "eyJhbGci..."`

2. **Sync Dashboard Connected Accounts & Balances**:
   ```http
   GET /v1/superapp/accounts/sync
   Authorization: Bearer <session_token>
   ```

---

### Flow C: Bank Account Linking with Fayda Ownership Verification

1. **Link COOP Bank Account**:
   ```http
   POST /v1/superapp/accounts/link
   Authorization: Bearer <session_token>
   Content-Type: application/json

   {
     "username": "abebe_girma",
     "bank_id": "COOP",
     "account_number": "1000234567890"
   }
   ```
   *Note*: The first linked account is automatically set as `is_default_sending` and `is_default_receiving`.

---

### Flow D: Peer-to-Peer (P2P) Handle-to-Handle Transfer

1. **Initiate P2P Transfer**:
   ```http
   POST /v1/superapp/transfers
   Authorization: Bearer <session_token>
   Content-Type: application/json

   {
     "sender_username": "abebe_girma",
     "recipient_username": "selamawit_bekele",
     "amount": 250.00,
     "remittance_info": "Dinner share"
   }
   ```
   *Validation*: Automatically checks if Abebe has sufficient balance in his default sending bank account.

---

### Contact & Support
For backend questions or schema updates, refer to the interactive OpenAPI docs at `http://localhost:8000/docs`.
