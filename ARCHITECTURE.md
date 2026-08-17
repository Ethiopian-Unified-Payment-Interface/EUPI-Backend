# EUPI — System Architecture

Cross-system reference for the three EUPI repositories: the FastAPI gateway, the
Next.js admin portal, and the Flutter super app.

> This is the version-controlled copy. An identical file sits one directory
> above the three repositories for convenience when working across all of them;
> that location is not a git repository, so this is the authoritative one.

---

## 1. What EUPI is

A **payment and identity platform** for Ethiopia, with three surfaces:

| Surface | What it does |
|---|---|
| **Gateway** | Standardised AIS + PIS over multiple Ethiopian bank rails, Fayda eKYC, fee engine, double-entry ledger |
| **Super App** | Consumer app: aggregated balances, handle-based P2P, merchant payments |
| **Admin Portal** | Internal operations: rails, customers, merchants, pricing, reconciliation, audit |

### One naming correction worth making

The repository currently markets itself as *"Ethiopia's first unified **Open
Banking** API standard."* For the developer-facing product, that is no longer
accurate and should be changed.

The developer API exposes **EUPI's own transaction ledger**, not bank data
brokered with consent. That moves it out of Tink's category (which requires bank
agreements and AISP licensing) and into Stripe/PayPal's. This is a *better*
position — it removes banks from the critical path of the developer product — but
claiming open banking invites a standard EUPI does not meet and regulatory
attention it does not need. Open banking becomes a later phase, when banks sign.

---

## 2. System overview

Status is marked throughout: **solid** = built and verified, **dashed** = not yet
built, **red** = blocked on something outside engineering.

```mermaid
flowchart TB
    subgraph CH["CHANNELS"]
        direction LR
        SA["Super App<br/>Flutter · Riverpod<br/>PIN + Fayda eKYC"]
        AP["Admin Portal<br/>Next.js 16<br/>email + password + RBAC"]
        TPP["Third-party apps<br/>client credentials<br/>NOT BUILT"]
    end

    subgraph L4["LAYER 4 · PRESENTATION — FastAPI routers"]
        direction LR
        V1["/v1<br/>auth · accounts<br/>payments · callbacks"]
        SUP["/v1/superapp<br/>users · accounts · transfers<br/>transactions · consents"]
        ADM["/v1/admin<br/>auth · dashboard · banks<br/>customers · merchants<br/>ledger · audit"]
    end

    subgraph L2["LAYER 2 · APPLICATION — use cases, orchestration only"]
        direction TB
        UC["AISService · PISService · SuperAppTransferService<br/>LedgerService · FeeService · ConsentService<br/>AdminAuthService · AccountLinkingService<br/>UserRegistrationService · Admin*Service"]
        CORE["CORE PORTS<br/>BankPort · IdentityPort · RoutingPort<br/>PasswordHasherPort · IdentityVaultPort<br/>Ledger · FeeRule · Consent · User · AdminUser repos"]
        PLUG["PLUGGABLE SERVICE PORTS — Phase 4<br/>FraudCheckPort · RiskScoringPort<br/>CreditScorePort · FxRatePort"]
    end

    subgraph L1["LAYER 1 · DOMAIN — pure Pydantic, zero framework imports"]
        DOM["Account · Transaction · Payment · Identity<br/>User · LinkedAccount · AdminUser<br/>Ledger · Fee · Consent · pii"]
    end

    subgraph L3["LAYER 3 · INFRASTRUCTURE — the only layer that performs I/O"]
        direction TB
        ADAPT["SmartRouter · FaydaAdapter<br/>Argon2PasswordHasher · FernetIdentityVault"]
        DB["Database — ONE engine, ONE pool<br/>13 repositories · Alembic migrations"]
        CBS["BANK CBS ADAPTERS — all simulated<br/>Coop · CBE · Wegagen · Awash · Abyssinia · Berhan"]
        PLUGADAPT["SERVICE ADAPTERS — Phase 4<br/>in-house fraud rules first, vendors later"]
    end

    subgraph EXT["EXTERNAL"]
        direction LR
        BANKS["Real bank core systems<br/>UNCONNECTED"]
        PG[("PostgreSQL 16")]
        VENDORS["Fraud · Risk · Credit bureau · FX<br/>NOT INTEGRATED"]
        ETHSW["EthSwitch<br/>cross-bank settlement<br/>NOT INTEGRATED"]
    end

    SA -->|"superapp_session<br/>+ per-payment PIN"| L4
    AP -->|"admin_session"| L4
    TPP -.->|"no auth path yet"| L4

    L4 --> UC
    UC --> CORE
    UC -.-> PLUG
    UC --> DOM
    CORE -.->|"implemented by"| ADAPT
    CORE -->|"implemented by"| DB
    CORE -->|"implemented by"| CBS
    PLUG -.->|"implemented by"| PLUGADAPT

    DB --> PG
    CBS -.->|"SIMULATION BOUNDARY<br/>httpx commented out"| BANKS
    PLUGADAPT -.-> VENDORS
    CBS -.-> ETHSW

    classDef built fill:#0f3d2e,stroke:#2e9e6b,color:#e8f5ee
    classDef planned fill:#2a2a2a,stroke:#888,color:#ddd,stroke-dasharray: 5 4
    classDef blocked fill:#3d1f1f,stroke:#c0504d,color:#f5e8e8,stroke-dasharray: 5 4
    classDef store fill:#1f2f3d,stroke:#4a90c0,color:#e8f0f5

    class SA,AP,V1,SUP,ADM,UC,CORE,DOM,ADAPT,DB built
    class TPP,PLUG,PLUGADAPT,VENDORS planned
    class CBS,BANKS,ETHSW blocked
    class PG store
```

Two things this is meant to make obvious:

1. **The bottom edge is closed.** Every bank rail is a simulation. For a sandbox
   product that is the correct answer — it is what Stripe and Tink both ship — but
   no live CBS integration exists, and that gates all revenue.
2. **The top-right edge has no door.** Third-party developers cannot
   authenticate. `/v1` exists but there is no client-credentials flow, no `app_id`
   tenancy scoping, and no rate limits.

### Pluggable services — the Phase 4 seam

The dashed `PLUG` group is the extension point for capabilities EUPI will not
build itself. It is cheap precisely because the hexagonal design already exists:
each is a port alongside `BankPort`, so swapping an in-house implementation for a
vendor touches one adapter and no use case.

```mermaid
flowchart LR
    PIS["PISService"]

    subgraph PORTS["Ports — Layer 2"]
        direction TB
        FR["FraudCheckPort"]
        RS["RiskScoringPort"]
        CS["CreditScorePort"]
        FX["FxRatePort"]
    end

    subgraph IMPL["First implementation — Layer 3"]
        direction TB
        FRI["In-house rules<br/>velocity · amount thresholds<br/>first-time recipient"]
        RSI["Null implementation"]
        CSI["Null implementation"]
        FXI["Interface only —<br/>nothing behind it"]
    end

    subgraph LATER["Later"]
        direction TB
        FRV["Fraud vendor"]
        RSV["Risk vendor"]
        CSV["NBE credit<br/>reference bureau"]
        FXV["FX provider —<br/>DEFERRED"]
    end

    PIS -->|"before order_payment"| FR
    PIS --> RS
    PIS --> CS
    PIS --> FX

    FR --> FRI --> FRV
    RS --> RSI --> RSV
    CS --> CSI --> CSV
    FX --> FXI --> FXV

    classDef planned fill:#2a2a2a,stroke:#888,color:#ddd,stroke-dasharray: 5 4
    classDef built fill:#0f3d2e,stroke:#2e9e6b,color:#e8f5ee
    classDef deferred fill:#3d1f1f,stroke:#c0504d,color:#f5e8e8,stroke-dasharray: 5 4

    class PIS built
    class FR,RS,CS,FRI,RSI,CSI,FRV,RSV,CSV planned
    class FX,FXI,FXV deferred
```

`FraudCheckPort` is the only one with real work behind it: it wires into the
payment flow **before** `order_payment`, so a blocked payment never reaches the
bank. The rest exist so the seam is not a rewrite later.

**`FxRatePort` is deliberately empty.** Ethiopian forex is tightly controlled and
cross-border remittance is a separate licence and a separate business. The
interface should exist; nothing should be built behind it until that is a
deliberate decision.

---

## 3. Clean Architecture, and why it held up

Dependency arrows point **inward**. Layer 1 imports nothing. Layer 2 depends only
on ports it defines. Layer 3 implements those ports. Layer 4 calls Layer 2.

This is worth stating because it paid for itself: adding a ledger, a fee engine,
a consent system, and a national-ID vault was **almost entirely additive**.
Roughly 85% of existing code was untouched or extended, ~10% mechanical
refactor, ~5% rewrite. Had the routes talked directly to SQLAlchemy and httpx,
the same work would have been a rewrite.

The domain vocabulary also already anticipated the developer platform:
`DeveloperApp` carries `client_id` and `allowed_scopes`, and `KYBRequest`,
`Merchant`, `WebhookLog`, and `AuditLog` all exist. Those are designed seams
waiting to be filled, not new ones to cut.

---

## 4. Data model

```mermaid
erDiagram
    USERS ||--o{ LINKED_ACCOUNTS : "links"
    USERS ||--o{ USER_APP_IDENTITIES : "one pseudonym per app"
    USERS ||--o{ CONSENTS : "grants"
    USERS ||--|| FIN_VAULT : "encrypted national ID"
    PAYMENTS ||--o{ LEDGER_ENTRIES : "posts a balanced set"
    PAYMENTS ||--o{ WEBHOOK_EVENTS : "delivery log"
    FEE_RULES ||..o{ PAYMENTS : "priced by rule_id + version"

    USERS {
        string username PK
        text fin_encrypted "Fernet — only place the value survives"
        string fin_blind_index UK "keyed HMAC — lookups without decrypting"
        string fin_last4 "masked suffix — no decryption capability"
        string pin_hash "argon2id"
        int failed_pin_attempts
        datetime pin_locked_until
    }
    LINKED_ACCOUNTS {
        string link_id PK
        string bank_id UK "UNIQUE(username, bank_id, account_number)"
        string account_number UK
        bool is_default_sending
        bool is_default_receiving
    }
    USER_APP_IDENTITIES {
        string psu_id PK "the only user ID a developer sees"
        string app_id UK "UNIQUE(username, app_id)"
    }
    CONSENTS {
        string consent_id PK
        string scope "one row per scope"
        string status
        datetime expires_at "evaluated on read"
    }
    FIN_VAULT {
        string username PK
        string fin_blind_index UK
        text fin_ciphertext
    }
    PAYMENTS {
        string payment_id PK
        string end_to_end_id UK "idempotency key"
        string debtor_bank_id
        string creditor_bank_id
        string selected_rail "router's choice, not the debtor"
        decimal amount "NUMERIC(18,2)"
        text consent_token "carries consent_method"
    }
    LEDGER_ENTRIES {
        string entry_id PK
        string transaction_ref "groups a balanced set"
        string direction "DEBIT or CREDIT"
        decimal amount "NUMERIC(18,2)"
        bool is_mirror "splits the two books"
        string app_id "tenancy — not yet populated"
    }
    FEE_RULES {
        string rule_id PK
        int version PK "never edited in place"
        int revenue_share_bps
        bool is_active
    }
```

Other tables: `admin_users`, `consent_tokens`, `bank_configurations`,
`merchants`, `developer_apps`, `kyb_requests`, `audit_logs`, `alembic_version`.

### Three decisions worth understanding

**The national ID is three columns, not one.** `users.fin` used to be plaintext,
indexed, and unique — so anyone who obtained the table obtained every citizen's
Fayda number. It is now `fin_encrypted` (Fernet ciphertext, the only place the
value survives), `fin_blind_index` (a **keyed** HMAC, so equality lookups need no
decryption), and `fin_last4` (the masked suffix). That third column is
least-privilege: the admin analytics repository reads it and has **no decryption
capability at all**, so an operator browsing the customer list cannot obtain a
full national ID through that path even if the presentation layer forgot to mask.

The index must be keyed, not a bare hash. A 14-digit FIN has a 10¹⁴ keyspace; a
plain SHA-256 of one is brute-forceable offline by anyone holding the table.

**The ledger holds two independent books.** Because EUPI operates on revenue
share and never holds customer funds:

- **Mirror entries** (`is_mirror=true`) record value that moved *at the banks*.
  EUPI never controlled it. They answer "what did we orchestrate?"
- **Revenue entries** are EUPI's own receivable and recognised income.

Each balances to zero separately, and reconciliation never nets them — a number
mixing "money we moved" with "money we're owed" means nothing.

**Fee rules are versioned, never updated.** A price change publishes version N+1
and retires N. Every payment records the exact `rule_id` and `version` that
priced it, so re-running last quarter's report produces last quarter's prices.

---

## 5. Authentication and token types

Four token types. **Every decoder asserts its exact type** — this is load-bearing,
not defensive style. Without it a Super App session token (which carries
`sub`/`jti`/`scopes`/`kyc_level`) validates as a gateway AIS/PIS token and grants
access to banking endpoints it was never issued for.

| Type | Issued by | Authorises | TTL |
|---|---|---|---|
| `gateway_access` | Fayda OTP, or a PIN authorisation | AIS reads, PIS payments | 1h / 2min |
| `superapp_session` | PIN login | Super App endpoints — **not payments** | 1h |
| `registration_verification` | OTP during signup | Completing registration | 15min |
| `admin_session` | Operator login | Admin API, gated by role | 8h |

### Consent for a payment

```mermaid
flowchart TB
    subgraph FP["Fayda path — third-party or direct PIS"]
        direction TB
        F1["POST /v1/auth/fayda"] --> F2["OTP dispatched"]
        F2 --> F3["POST /v1/auth/fayda/confirm"]
        F3 --> F4["gateway_access, 1h<br/>consent_method=fayda_otp"]
    end

    subgraph SP["Super App path — handle-based P2P"]
        direction TB
        S1["POST /v1/superapp/transfers<br/>with pin"] --> S2["PIN verified<br/>argon2 + lockout"]
        S2 --> S3["gateway token minted, 2 min<br/>consent_method=superapp_pin"]
    end

    PIS["PIS: initiate → verify → order<br/>ONE validation path —<br/>signature, expiry, revocation, KYC level"]

    F4 --> PIS
    S3 --> PIS

    classDef built fill:#0f3d2e,stroke:#2e9e6b,color:#e8f5ee
    class F1,F2,F3,F4,S1,S2,S3,PIS built
```

Both paths produce a real signed gateway token, tracked for revocation and
carrying a KYC level, so `PISService` has **one** validation path rather than a
second weaker branch.

The PIN is required **per transfer**, not once per session. A session token is a
bearer credential valid for an hour; accepting it as payment authorisation would
make a leaked token sufficient to drain an account — a weaker bar than the OTP it
replaces. The `consent_method` claim records which path was used, because a
PIN-authorised payment and an OTP-authorised one are not equivalent evidence.

---

## 6. Handle-based P2P

The flow the platform is really about: two usernames and an amount in, four
banking details derived.

```mermaid
sequenceDiagram
    autonumber
    participant App as Super App
    participant API as /v1/superapp/transfers
    participant Reg as UserRegistrationService
    participant Fayda as FaydaAdapter
    participant Xfer as SuperAppTransferService
    participant PIS as PISService
    participant Fee as FeeService
    participant Bank as Bank CBS
    participant Ldg as LedgerService

    App->>API: sender, recipient, amount, pin, client_reference
    API->>API: idempotency check — return original if seen
    API->>Xfer: send_money(...)

    Xfer->>Reg: authorise_with_pin
    Note over Reg: argon2 verify + lockout.<br/>PIN required per transfer:<br/>a session token is a bearer<br/>credential and would let a<br/>leaked token drain the account.
    Reg-->>Xfer: payer

    Xfer->>Xfer: resolve recipient by handle
    Xfer->>Xfer: sender's default SENDING → debtor
    Xfer->>Xfer: recipient's default RECEIVING → creditor
    Xfer->>Xfer: classify INTRA_BANK vs CROSS_BANK
    Xfer->>Bank: balance check at debtor bank

    Xfer->>Fayda: issue_delegated_consent_token
    Note over Fayda: 2-min gateway token,<br/>consent_method=superapp_pin
    Fayda-->>Xfer: consent token

    Xfer->>PIS: initiate → verify → order
    PIS->>Fee: quote — debtor's bank, not routed rail
    Fee-->>PIS: customer_fee + eupi_revenue
    PIS->>Bank: submit debit order
    Bank-->>PIS: bank_order_reference
    PIS-->>App: ORDERED

    Bank->>API: POST /v1/callbacks — confirmed
    API->>PIS: process_callback
    PIS->>Ldg: record_settled_payment
    Note over Ldg: Two balanced books:<br/>mirror legs for bank movement,<br/>revenue legs for EUPI's share.<br/>Signed total must be 0.
    PIS-->>API: SUCCESS
```

`INTRA_BANK` matters strategically: both accounts in one CBS is an internal book
transfer needing **no interbank settlement**, so it is the case that can go live
with a single bank agreement. It is priced separately for the same reason.

The debit account is **not** selectable by the client. The server resolves it
from the sender's default, so a UI offering a choice would let a user select one
bank and watch another be debited.

---

## 7. Deployment

```mermaid
flowchart LR
    subgraph HOST["docker compose up --build"]
        direction LR
        PG[("postgres:16-alpine<br/>:5432<br/>volume: eupi-postgres")]
        BE["backend :8000<br/>entrypoint:<br/>wait for db →<br/>alembic upgrade head →<br/>uvicorn"]
        FE["admin-portal<br/>host :3001 → :3000<br/>Next.js standalone"]
    end

    BROWSER["Browser"]
    DEVICE["Android device<br/>adb reverse tcp:8000"]

    BE -->|"depends_on: service_healthy"| PG
    FE -->|"depends_on: service_healthy"| BE
    BROWSER --> FE
    BROWSER -->|"NEXT_PUBLIC_API_URL<br/>baked at build time"| BE
    DEVICE -->|"127.0.0.1:8000<br/>tunnelled over USB/WiFi"| BE

    classDef svc fill:#0f3d2e,stroke:#2e9e6b,color:#e8f5ee
    classDef store fill:#1f2f3d,stroke:#4a90c0,color:#e8f0f5
    classDef client fill:#2f2a3d,stroke:#8a7fc0,color:#efe8f5
    class BE,FE svc
    class PG store
    class BROWSER,DEVICE client
```

**Migrations run in the entrypoint, not application startup.** A failed migration
stops the container rather than leaving a process serving against a half-migrated
schema.

**Postgres, not SQLite,** for two concrete reasons: SQLite serialises writers
behind a single lock (measured: 20 concurrent reads in 312ms and 10/10 concurrent
writes on Postgres — SQLite would queue them), and it has no real decimal type,
while the ledger needs exact `NUMERIC(18,2)` arithmetic.

`create_all()` no-ops when it detects `alembic_version`, so the two schema
mechanisms cannot fight.

The portal maps to host **3001** because a local `next dev` usually owns 3000.
`NEXT_PUBLIC_API_URL` is inlined at build time and must be the *browser's* URL.

### Device testing

```
adb connect <device-ip>:<port>          # wireless debugging (port rotates)
adb reverse tcp:8000 tcp:8000           # device localhost:8000 → host
```

The app targets `127.0.0.1:8000`, tunnelled through adb.

---

## 8. Competitive position

EUPI overlaps three different kinds of company, and no one of them describes it.

| | What it fundamentally is | Money custody |
|---|---|---|
| **UPI** | National payment *standard + switch* (NPCI, RBI mandate) | Never holds funds |
| **Tink** | *Middleware* over existing PSD2 bank APIs | Never holds funds |
| **PayPal** | Closed-loop *network + wallet* | Holds funds; is the counterparty |
| **EUPI** | All three at once | Never holds funds — pass-through |

**Closest to UPI** in shape: handle-based addressing (`username@eupi` ≈ VPA),
national ID as the identity root (Fayda ≈ Aadhaar), multi-bank linking with
defaults, a central switch. **The critical difference is mandate.** NPCI is
bank-owned under RBI authority, so banks *had* to connect. EUPI is a private
platform hoping they will — which is why six adapters are still mocks, and it is
the largest non-technical risk.

**Closest to Tink** in product: one clean API over many banks' incompatible
interfaces. The `_normalise_account` methods in each adapter are Tink's entire
engineering thesis in miniature. But Tink integrates against APIs banks were
*legally forced* to build; Ethiopia has no PSD2 equivalent.

**Closest to PayPal** in developer surface: OAuth2 client credentials, sandbox,
webhooks, KYB onboarding. But PayPal is closed-loop and holds your money; EUPI is
strictly pass-through orchestration — no ledger of customer funds, no float. A
much lighter regulatory posture.

**Unique to EUPI:** the Smart Router. UPI routes deterministically to the payee's
bank; Tink connects to whichever single bank you name; PayPal routes internally.
Nothing else scores banks as interchangeable rails on live uptime, latency, and
cost with circuit breaking. Honest caveat: for most payments you cannot choose
which bank holds the recipient's money, so its real applicability today is
funding-side selection.

---

## 9. Where this stands

### Done and verified

Real admin authentication with RBAC · argon2id PINs with lockout · token-type
separation · FIN encrypted at rest with a keyed blind index · per-app pseudonyms ·
consent with per-scope revocation · double-entry ledger balancing to zero ·
versioned fee engine · per-bank reconciliation · Postgres with Alembic · one
engine across 13 repositories · PIN-authorised P2P with idempotency · 100 tests ·
Dockerised stack · Super App journey driven on a physical device

### Gated on a bank agreement

Everything that earns revenue. No amount of engineering unblocks it. The
architecture is arranged so that when the first bank signs, going live is an
adapter swap behind `BankPort` — weeks of integration, not months of
re-architecture.

**Intra-bank first** is the wedge: same-CBS transfers need no interbank
settlement, so one agreement yields a complete live product for that bank's
customers.

### Not built

- **Developer platform** — no TPP authentication, no `app_id` tenancy scoping, no
  rate limits, no client credentials. `app_id` columns exist in preparation. The
  tenancy scoping is the highest-risk change remaining: one missed query filter
  leaks one developer's data into another's.
- **Cross-bank settlement** — should interoperate with EthSwitch rather than
  rebuild national interbank settlement.
- **Pluggable services** — fraud, risk, credit scoring, FX. Architecturally cheap
  given the existing ports; strategically useful for the platform story.
- **Mini-app platform** — third parties listed as apps in the Super App. This is
  the answer to "why integrate with EUPI rather than the bank directly?":
  distribution.
- **Structured logging, CI, key rotation.**

### Two questions for counsel, not engineering

- Does orchestration-plus-revenue-share itself trigger NBE payment-operator
  licensing?
- Does the pseudonymity design satisfy Ethiopia's personal data protection
  regime? It is built to be defensible, but that judgement is not engineering's
  to make.

These run on legal timelines rather than sprint timelines, so they are worth
starting early.
