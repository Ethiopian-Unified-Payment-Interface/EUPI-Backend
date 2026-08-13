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

The gateway integrates with 6 primary commercial bank adapters:
- **COOP** — Cooperative Bank of Oromia
- **CBE** — Commercial Bank of Ethiopia
- **WEGAGEN** — Wegagen Bank
- **AWASH** — Awash Bank
- **ABYSSINIA** — Bank of Abyssinia (Abisiniya)
- **BERHAN** — Berhan Bank

---

### User → Designated Bank Accounts Mapping Matrix

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

### Username Formatting
- Base handles chosen during registration auto-append **`@eupi`** (e.g., `abebe_girma` → `abebe_girma@eupi`).
- Usernames are **case-insensitive primary keys** and must be unique.

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

---

## 6. Step-by-Step Frontend Testing Flows

### Flow A: Super App User Registration (2-Step Fayda eKYC OTP)

1. **Request Registration OTP**:
   ```http
   POST /v1/superapp/users/register/request-otp
   Content-Type: application/json

   {
     "fin": "12345678901234",
     "phone_number": "+251911234567"
   }
   ```
   *Response*: Returns `"session_id": "FAYDA-SES-..."`

2. **Complete Registration**:
   ```http
   POST /v1/superapp/users/register
   Content-Type: application/json

   {
     "username": "abebe_girma",
     "fin": "12345678901234",
     "pin": "123456",
     "session_id": "FAYDA-SES-...",
     "otp_code": "123456"
   }
   ```
   *Response*: Returns profile with username `abebe_girma@eupi` and legal name `Abebe Girma Tadesse`.

---

### Flow B: Super App PIN Login & Session Maintenance

1. **Login with 6-Digit PIN**:
   ```http
   POST /v1/superapp/users/login
   Content-Type: application/json

   {
     "username": "abebe_girma@eupi",
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
     "sender_username": "abebe_girma@eupi",
     "recipient_username": "selamawit_bekele@eupi",
     "amount": 250.00,
     "remittance_info": "Dinner share"
   }
   ```
   *Validation*: Automatically checks if Abebe has sufficient balance in his default sending bank account.

---

### Contact & Support
For backend questions or schema updates, refer to the interactive OpenAPI docs at `http://localhost:8000/docs`.
