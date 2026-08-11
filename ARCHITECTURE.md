================================================================================
EUPI — ARCHITECTURE OVERVIEW
Clean Architecture + Hexagonal (Ports & Adapters)
================================================================================

1. THE CORE IDEA
--------------------------------------------------------------------------------


    LAYER 1 (domain)          <-- pure business objects, no imports from
        ^                          anything outside this project
        |
    LAYER 2 (application)     <-- business logic (use cases) + abstract
        ^                          contracts ("ports") that outer layers
        |                          must implement
        |
    LAYER 3 (infrastructure)  <-- concrete implementations of the ports:
        ^                          real/mock bank APIs, database, JWT signing
        |
    LAYER 4 (presentation)    <-- FastAPI routes: the outermost layer,
                                   translates HTTP <-> use cases

This is "Hexagonal" because Layer 2's ports are the hexagon's edges: any
number of "driven adapters" (Layer 3 — banks, DB, identity provider) can plug
into one side, and any number of "driving adapters" (Layer 4 — REST API,
could also be a CLI or gRPC service) can plug into the other side, without
either side needing to know about the other's implementation details.

Every source file in this project opens with a comment stating exactly which
layer it belongs to and what it's allowed to do, e.g.:

    Layer: 🟢 LAYER 1 — Enterprise Business Rules
    Rule: ZERO external framework imports. Pure Python + Pydantic only.

This is enforced by convention/discipline rather than tooling, but it is
followed consistently across the whole codebase.


2. FOLDER-BY-FOLDER, FILE-BY-FILE BREAKDOWN
--------------------------------------------------------------------------------

kifiya-open-gateway/
│
├── architecture_spec.md         Design document. Describes the target system
│                                 (this backend + a planned developer portal +
│                                 mobile app) and the 4-layer rules summarized
│                                 above. The spec this codebase was built from.
│
├── requirements.txt              Python dependencies: fastapi, uvicorn,
│                                 pydantic, PyJWT, sqlalchemy, python-dotenv.
│
├── .env.example                  Template for environment variables (JWT
│                                 secret, DB URL, per-bank API keys, Fayda
│                                 credentials, smart-router scoring weights).
│                                 Copied to `.env` for local/prod config —
│                                 keeps secrets out of source control.
│
├── kifiya_gateway.db              SQLite database file (runtime artifact,
│                                 not architecture — created automatically).
│
└── backend/
    │
    ├── main.py                   COMPOSITION ROOT. Not really "in" any one
    │                             layer — this is where all 4 layers get
    │                             wired together. On FastAPI startup
    │                             (`lifespan`), it constructs the concrete
    │                             Layer-3 adapters (bank adapters, Fayda
    │                             adapter, SmartRouter, SQLiteRepository),
    │                             injects them into the Layer-2 use cases
    │                             (AISService, PISService), and exposes
    │                             `get_*()` accessor functions that the
    │                             Layer-4 routes call to obtain those use
    │                             cases. This is the only place that "knows
    │                             about" every layer at once — it's what
    │                             makes dependency inversion possible.
    │
    ├── config.py                 Reads environment variables into a single
    │                             `Settings` object (JWT secret/TTL, DB URL,
    │                             bank API keys, Fayda credentials, router
    │                             scoring weights, CORS origins, debug flag).
    │                             Used by Layer 3 and Layer 4 code; the
    │                             domain and application layers never touch
    │                             this file, keeping them environment-agnostic.
    │
    │
    ├── domain/                   ══════ LAYER 1 — ENTERPRISE BUSINESS RULES ══════
    │   │                         Pure Pydantic models. No FastAPI, no SQLAlchemy,
    │   │                         no HTTP, no JWT — nothing but Python + Pydantic.
    │   │                         This is the most stable layer: it represents
    │   │                         concepts ("a Payment", "an Account") that don't
    │   │                         change just because you swap a database or a
    │   │                         web framework.
    │   │
    │   └── models/
    │       ├── account.py        `Account`, `AccountType`, `BankID`, `Currency`
    │       │                     enums/models — the bank-agnostic, normalized
    │       │                     shape every bank adapter must translate its
    │       │                     proprietary data into.
    │       ├── transaction.py    `Transaction` and related enums, modeled after
    │       │                     the ISO 20022 camt.053 statement standard —
    │       │                     the normalized shape for transaction history.
    │       ├── payment.py        `Payment`, `PaymentStatus`, and the payment
    │       │                     initiation/verification request/response
    │       │                     shapes. Encodes the PIS state machine itself:
    │       │                     PENDING -> VERIFIED -> ORDERED ->
    │       │                     SUCCESS / FAILED / CANCELLED.
    │       └── identity.py       `FaydaVerifyRequest`, `FaydaKYCResult`,
    │                             `KYCLevel` — models for Ethiopia's Fayda
    │                             national ID eKYC flow.
    │
    │
    ├── application/              ══════ LAYER 2 — APPLICATION BUSINESS RULES ══════
    │   │                         Orchestrates the domain models into actual
    │   │                         use cases. Depends ONLY on domain models and
    │   │                         on its own abstract "ports" — never on a
    │   │                         concrete database, bank API, or FastAPI.
    │   │                         This is what makes the system testable: any
    │   │                         use case can be tested by handing it a fake
    │   │                         port implementation, no real bank or DB needed.
    │   │
    │   ├── ports/                 Abstract interfaces (Python ABCs). These are
    │   │   │                     CONTRACTS ONLY — no implementation, no HTTP
    │   │   │                     calls. Infrastructure adapters are required to
    │   │   │                     implement them. This is "dependency inversion":
    │   │   │                     the use cases depend on these abstractions,
    │   │   │                     and the concrete infrastructure code depends
    │   │   │                     on them too — so the arrow of dependency
    │   │   │                     points from infrastructure TOWARD application,
    │   │   │                     not the other way around.
    │   │   ├── bank_port.py       `BankPort` ABC — contract every bank adapter
    │   │   │                     (Coop, CBE, Wegagen, Awash) must satisfy:
    │   │   │                     fetch accounts, fetch statements, initiate
    │   │   │                     transfer, health_check, etc.
    │   │   ├── identity_port.py   `IdentityPort` ABC — contract the Fayda
    │   │   │                     adapter must satisfy: initiate_kyc_verification,
    │   │   │                     confirm_kyc_otp.
    │   │   └── routing_port.py    `RoutingPort` ABC (+ `RouteScore` dataclass) —
    │   │                         contract the Smart Router must satisfy:
    │   │                         register_rail, evaluate_all_routes,
    │   │                         get_optimal_route.
    │   │
    │   └── use_cases/              The actual business logic / orchestration.
    │       ├── ais_service.py      `AISService` — Account Information Service.
    │       │                     Aggregates balances and up to a year of
    │       │                     transaction history across every registered
    │       │                     bank rail, via `BankPort` only. Never touches
    │       │                     a concrete bank class or the DB directly.
    │       └── pis_service.py      `PISService` — Payment Initiation Service.
    │                             Drives the Initiate -> Verify -> Order ->
    │                             Callback lifecycle, enforcing legal state
    │                             transitions (raises `InvalidPaymentStateError`,
    │                             `SameAccountError`, `NoAvailableRouteError`,
    │                             etc. on violations) and calling out to
    │                             `RoutingPort` to pick a bank rail. Depends
    │                             only on ports and domain models.
    │
    │
    ├── infrastructure/            ══════ LAYER 3 — INFRASTRUCTURE / DRIVEN ADAPTERS ══════
    │   │                         Concrete implementations of the Layer-2 ports.
    │   │                         This is the ONLY layer allowed to make real
    │   │                         HTTP calls, touch the database, or sign/verify
    │   │                         JWTs. It's the outward-facing "plug" side of
    │   │                         the hexagon that the application core doesn't
    │   │                         know the details of.
    │   │
    │   ├── adapters/
    │   │   ├── banks/              Implementations of `BankPort`, one per bank.
    │   │   │   ├── coop_cbs.py     `CoopCBSAdapter` — Cooperative Bank of
    │   │   │   │                 Oromia. Currently returns realistic
    │   │   │   │                 deterministic MOCK data simulating Coop's
    │   │   │   │                 proprietary field names/latency; designed so
    │   │   │   │                 only the mock-response methods need
    │   │   │   │                 replacing with real httpx calls later — the
    │   │   │   │                 rest of the system wouldn't need to change.
    │   │   │   ├── cbe_cbs.py      `CBECBSAdapter` — Commercial Bank of
    │   │   │   │                 Ethiopia, same pattern as above.
    │   │   │   ├── wegagen_cbs.py  `WegagenCBSAdapter` — Wegagen Bank, same
    │   │   │   │                 pattern as above.
    │   │   │   └── _legacy_mock_bank.py   Left over from an earlier project
    │   │   │                     phase; superseded by the three adapters
    │   │   │                     above and no longer imported anywhere.
    │   │   │                     Dead code.
    │   │   │
    │   │   ├── identity/
    │   │   │   ├── fayda.py        `FaydaAdapter` — implements `IdentityPort`.
    │   │   │   │                 Simulates Ethiopia's Fayda national ID
    │   │   │   │                 OTP/eKYC flow, issues real signed JWTs
    │   │   │   │                 (delegating to jwt_handler.py) and records
    │   │   │   │                 issuance in SQLite for later revocation.
    │   │   │   └── mock_fayda.py   Earlier-phase mock identity adapter,
    │   │   │                     superseded by fayda.py. Not imported
    │   │   │                     anywhere. Dead code.
    │   │   │
    │   │   └── router/
    │   │       ├── smart_router.py `SmartRouter` — implements `RoutingPort`.
    │   │       │                 Live-pings each bank's health_check(),
    │   │       │                 keeps a rolling uptime window per bank,
    │   │       │                 and scores each rail as a weighted
    │   │       │                 composite of uptime/latency/cost (weights
    │   │       │                 configurable via config.py). Includes a
    │   │       │                 circuit breaker that excludes rails whose
    │   │       │                 rolling uptime drops below 50%.
    │   │       └── mock_router.py  Earlier-phase mock router, superseded by
    │   │                         smart_router.py. Not imported anywhere.
    │   │                         Dead code.
    │   │
    │   ├── auth/
    │   │   └── jwt_handler.py      The ONLY module allowed to sign or decode
    │   │                         gateway JWTs. Wraps PyJWT: creates
    │   │                         HS256-signed tokens carrying FIN, scopes,
    │   │                         KYC level, jti (for revocation), issued/
    │   │                         expiry timestamps; also decodes/validates
    │   │                         tokens. Used by both the Fayda adapter
    │   │                         (issuing) and the presentation routes
    │   │                         (validating incoming Bearer tokens).
    │   │
    │   └── database/
    │       ├── models.py           SQLAlchemy ORM table definitions only —
    │       │                     `PaymentRecord`, `ConsentTokenRecord`,
    │       │                     `WebhookEventRecord`. Deliberately contains
    │       │                     no business logic, just column/table shape.
    │       └── sqlite_repo.py      `SQLiteRepository` — the only module
    │                             allowed to touch the database. Converts
    │                             between domain objects (Layer 1) and ORM
    │                             rows (this file), handles payment CRUD,
    │                             consent-token issuance/revocation tracking,
    │                             webhook-event logging, and restoring the
    │                             in-memory payment cache from disk on
    │                             server restart.
    │
    │
    └── presentation/              ══════ LAYER 4 — PRESENTATION / DRIVING ADAPTERS ══════
        │                         The outermost layer. FastAPI route handlers
        │                         ONLY — they unpack an HTTP request, call a
        │                         Layer-2 use case (obtained via main.py's
        │                         get_*() functions), and translate the result
        │                         into an HTTP response. No business logic is
        │                         supposed to live here.
        │
        └── api_v1/
            ├── auth.py            `POST /v1/auth/fayda` and
            │                     `/v1/auth/fayda/confirm` — drives the
            │                     Fayda OTP flow via IdentityPort and returns
            │                     the issued JWT to the caller.
            ├── accounts.py        `GET /v1/accounts` (AIS) — validates the
            │                     Bearer JWT, then calls AISService to return
            │                     aggregated account/transaction data.
            ├── payments.py        `POST /v1/payments/initiate|verify|order`
            │                     (PIS) — drives PISService through the
            │                     payment lifecycle. Also owns the
            │                     module-level `_payment_store` dict used as
            │                     an in-memory cache alongside SQLite.
            └── webhooks.py         `POST /v1/callbacks` — receives async
                                  confirmation from a bank after the ORDER
                                  step and calls PISService to finalize the
                                  payment as SUCCESS or FAILED.


3. HOW A REQUEST FLOWS THROUGH THE LAYERS (EXAMPLE: INITIATING A PAYMENT)
--------------------------------------------------------------------------------
1. HTTP POST /v1/payments/initiate hits presentation/api_v1/payments.py
   (Layer 4). It parses/validates the JSON body with a Pydantic request model.
2. The route calls `get_pis_service()` from main.py, which returns the
   already-constructed `PISService` (Layer 2), built at startup with real
   Layer-3 adapters injected into it.
3. `PISService.initiate_payment(...)` runs pure business logic against
   `domain/models/payment.py` (Layer 1) and calls out through the
   `RoutingPort` and `BankPort` interfaces (Layer 2 contracts) to decide
   which bank rail to use and confirm the debtor account exists.
4. Those interface calls are actually satisfied by `SmartRouter` and, e.g.,
   `CoopCBSAdapter` (Layer 3) — concrete infrastructure the use case has no
   knowledge of by name.
5. The resulting `Payment` domain object is handed back up to the route,
   which stores it (in-memory dict + `SQLiteRepository`) and serializes it
   into the HTTP response.

At every step, each layer only calls inward through an interface it owns —
never sideways or through a concrete class from another layer. That's the
whole point of the architecture: bank integrations, the database engine, or
even the web framework could each be swapped out without touching
`domain/` or the core logic in `application/`.


4. QUICK REFERENCE — WHO'S ALLOWED TO DO WHAT
--------------------------------------------------------------------------------
  domain/            -> Define data shapes only. No imports of anything else
                         in this project's other layers.
  application/ports/  -> Define abstract contracts only. No implementation.
  application/use_cases/ -> Business logic, using ports + domain models only.
  infrastructure/     -> The ONLY place allowed to: make HTTP calls, touch
                         the database, sign/verify JWTs.
  presentation/        -> The ONLY place allowed to: know about FastAPI,
                         parse HTTP requests, return HTTP responses.
  main.py              -> The ONLY place allowed to know about every layer
                         at once, and wire them together (composition root).

================================================================================
