# Backend Changes

Work completed on the EUPI gateway, in the order it was done. Each section says
what changed and why it mattered — the "why" is usually the part worth reading,
because several of these were fixing something that looked like it worked.

**Verification:** 100 tests (`py -m pytest tests/ -q`), the stack running on
Postgres under `docker compose`, and the Super App journey driven end to end on
a physical Android device.

---

## Phase 0 — Security blockers

Nothing else was safe to build on top of these.

### The Admin API was completely unauthenticated

`api_admin/auth_deps.py` returned a valid admin identity when **no credentials
were supplied**, and accepted the literal strings `dev-admin-token` and
`mock-admin-token`. It also called `jwt_handler.verify_access_token`, a function
that **did not exist** — so presenting a genuine token raised `AttributeError`
and returned 500, leaving the unauthenticated path as the only one that worked.

Replaced with real authentication:

- `AdminUser` domain model with an `AdminRole` enum (`ADMIN`, `READ_ONLY`)
- `AdminUserRepositoryPort` + relational implementation
- `POST /v1/admin/auth/login` issuing a signed `admin_session` token
- `require_role(...)` / `require_admin` dependencies, applied to every
  configuration write
- Operator re-read on every request, so a token issued before a role change or
  a deactivation stops working immediately rather than at the end of its TTL
- First-operator bootstrap from `ADMIN_BOOTSTRAP_EMAIL` / `_PASSWORD`, since
  there is now no unauthenticated way in

### PINs were unsalted SHA-256

A 6-digit PIN has 10⁶ possibilities. An unsalted digest of one falls to a
precomputed table instantly, and identical PINs produced identical hashes
across users.

- New `PasswordHasherPort` + `Argon2PasswordHasher` (argon2id, OWASP
  parameters), so the algorithm sits behind a port rather than in a use case
- Legacy SHA-256 hashes still verify **once** and are migrated to argon2id on
  that first successful login, so no account needs a reset
- `pin_hash` widened from `String(64)`
- Per-account attempt throttling with lockout, persisted so it survives a
  restart and cannot be cleared by reconnecting
- Applied to change-PIN as well as login — otherwise change-PIN was an
  unthrottled oracle for guessing the current PIN

### Token-type confusion

`decode_gateway_jwt` required `sub`/`jti`/`scopes`/`kyc_level` but never checked
the token's `type`. A Super App session token carries all four, so it validated
as a gateway AIS/PIS token and granted access to banking endpoints it was never
issued for.

Every token now carries a `type` claim and every decoder asserts the exact type
it expects. Issuer verification was also switched on.

One thing this surfaced: `logout` called `get_jti`, which decodes as a *gateway*
token, on a Super App session token. Adding the type check would have silently
broken session revocation, so revocation got its own deliberately type-agnostic
accessor — logging out must invalidate whatever token was presented.

### PII exposure

- FIN masked to last-4 across the Admin API, with unmasking gated on the `ADMIN`
  role and written to the audit log
- Account numbers always masked in admin transaction listings

### Configuration could ship insecurely

`config.py` now validates at import time and refuses to start when
`DEBUG=false` with a known-default `JWT_SECRET_KEY`, a wildcard `CORS_ORIGINS`,
or Smart Router weights that do not sum to 1.0. It reports every problem at
once rather than the first.

### Dashboard metrics were fabricated

`admin_repositories.py` clamped real counts up to marketing figures —
`max(user_count, 145000)` — and returned hardcoded transaction stats
(425.8B ETB). A database with twelve users reported a hundred and forty-five
thousand.

Every figure is now computed from the database. Where a metric genuinely cannot
be derived from the current schema it returns 0 and says so in a comment, rather
than an invented value.

---

## Phase 1 — Ledger & fee engine

### Double-entry ledger

`ledger_entries` is append-only: no update path, no delete path. A correction is
a new opposing transaction, because an audit trail that can be rewritten is not
an audit trail.

The design decision that shaped everything: under **revenue share** EUPI never
holds customer funds, so the ledger holds two independent books.

- **Mirror entries** record value that moved *at the banks*. EUPI never
  controlled it. They answer "what did we orchestrate?"
- **Revenue entries** are EUPI's own receivable and recognised income.

They balance separately and reconciliation never nets them — a number mixing
"money we moved" with "money we're owed" means nothing. A test asserts a mirror
leg cannot offset a revenue leg.

Money is `Decimal` end to end and `Numeric(18,2)` in the schema. Never float.

### Fee engine

- `FeeRule` matched on bank × transaction type × currency × amount tier
- Specificity resolution: a bank-specific rule beats a wildcard, so a negotiated
  rate overrides the platform default without restating every other bank's
  pricing
- **Versioned and never edited in place.** Revising publishes version N+1 and
  retires N; the old row stays, so re-running last quarter's report produces
  last quarter's prices
- Intra-bank priced below cross-bank, reflecting that it needs no interbank
  settlement
- A missing rule raises rather than defaulting to zero — a silent zero fee is
  indistinguishable from a correctly free transaction, and the difference is
  revenue nobody notices is missing

### Bug this found

Fees were priced against `selected_rail`, the Smart Router's chosen rail, so a
COOP→COOP payment accrued its receivable against **CBE**. The reconciliation
report surfaced it immediately: volume on one bank, revenue on another. Now
priced against the debtor's bank — the bank that actually charges the customer.

---

## Phase 2 — Consent & pseudonymous identity

### Per-application pseudonyms

The same person integrating with two developers gets two unrelated IDs. 128 bits
of randomness, **stored rather than derived** — a derived scheme
(`HMAC(secret, user + app)`) collapses the moment the secret leaks, because
every mapping can be recomputed.

The reverse lookup is scoped by `app_id`, so presenting another developer's
pseudonym resolves to nothing. Without that, a developer could confirm a
harvested ID belongs to a real user and re-enable the correlation the split IDs
prevent.

Context for why this matters: India ran the alternative with Aadhaar and lost.
Private-entity access was struck down in 2018, forcing a retrofit to tokenised
reference IDs.

### Consent

- One grant per scope, so withdrawing "see my name" does not sever payments
- Expiry evaluated on read, so a lapsed grant stops authorising the instant it
  lapses rather than whenever a cleanup job next runs
- `disconnect_app` revokes everything in one action — disconnecting must not
  depend on the user remembering every scope
- Revoking another user's consent returns the same error as a missing one, so
  the response cannot be used to probe for other users' IDs
- User-facing endpoints under `/v1/superapp/consents`

### FIN vaulted

`identity:read:fin` is **structurally unreachable** through self-service:
excluded from the catalogue, and `grant()` refuses it without an explicit
override reserved for the licensing-review path.

`VerifiedClaims` has no `username` field, asserted at schema level so a future
field addition that reintroduces a cross-app identifier fails the test even if
nothing populates it.

Fernet encryption plus a **keyed** blind index. The index has to be an HMAC, not
a bare hash: a 14-digit FIN has only a 10¹⁴ keyspace and a plain SHA-256 of one
is brute-forceable offline by anyone holding the table.

---

## Phase 3 — Postgres, one engine, migrations

### Thirteen engines to one

Every repository built its own `create_engine` and called
`Base.metadata.create_all()` in its constructor. Thirteen connection pools
against one database, schema creation as an import side effect, and — the part
that mattered — **no way for two repositories to share a transaction**, so a
payment and its ledger entries could not commit atomically no matter how the
calling code was written.

All 13 now take an injected `Database` (`infrastructure/database/session.py`).
Classes were renamed too: `SQLiteLedgerRepository` running on Postgres is a lie,
so they are `LedgerRepository`, `PaymentRepository`, and so on.

### Alembic

Two migrations, plus one added later:

1. `ae32cbf33580` — initial schema
2. `b7d41e9c2a10` — **encrypt the national ID at rest.** Hand-written, because
   autogenerate can add columns but cannot encrypt. Existing plaintext FINs are
   encrypted, then the migration **verifies before it destroys**: it counts
   unencrypted rows and refuses to drop the plaintext column if any remain,
   because a national ID lost there is unrecoverable. `downgrade()` works.
3. `c8a52f7b3d41` — prevent duplicate linked accounts (below)

`users.fin` (plaintext, indexed, unique) became three columns, each with one job:

| Column | Purpose |
|---|---|
| `fin_encrypted` | Fernet ciphertext — the only place the value survives |
| `fin_blind_index` | Keyed HMAC, so equality lookups need no decryption |
| `fin_last4` | Masked suffix, so the admin analytics repository renders a mask **with no decryption capability at all** |

That third column is a least-privilege decision, not tidiness: an operator
browsing the customer list cannot obtain a full national ID through that path
even if the presentation layer forgot to mask.

Incidental find: `customer_id` was `f"usr_{u.fin[:6]}"` — six digits of a
national ID baked into an identifier that then travelled through logs and URLs.

`create_all()` now no-ops when it detects `alembic_version`, so the two schema
mechanisms cannot fight each other.

### Postgres

Migrations run in the **container entrypoint, not application startup** — a
failed migration stops the container rather than leaving a process serving
against a half-migrated schema.

Verified: `numeric(18,2)` throughout, a 2500.55 payment round-tripping exactly,
20 concurrent reads in 312ms and 10/10 concurrent writes. SQLite's single-writer
lock would have serialised those.

---

## Super App P2P — PIN as consent

PIS VERIFY requires a `gateway_access` token, and a Super App session token is
correctly not interchangeable with one. So the app could **create a payment and
never complete it** — transfers were left `PENDING` and never reached the bank.
The old "demo fallback success" in the app had been masking that.

`POST /v1/superapp/transfers` now takes a `pin` and runs the whole lifecycle:

```
{ sender_username, recipient_username, amount, pin, client_reference }
  → PIN verified (same argon2 hash + lockout as login)
  → short-lived consent token minted from that verification
  → initiate → verify → order
  → returns ORDERED
```

**The PIN is required per transfer, not "a session token is enough."** A session
token is a bearer credential valid for an hour; accepting it as payment
authorisation would make a leaked token sufficient to drain an account — a
*weaker* bar than the OTP it replaces.

Rather than adding a second, weaker branch inside `PISService`, the PIN check
mints a real 2-minute gateway token via a new `issue_delegated_consent_token`
port method. The payment is then validated by exactly the same path as an
OTP-authorised one: signature, expiry, revocation tracking, KYC level.

The token carries a `consent_method` claim (`superapp_pin` vs `fayda_otp`) so an
auditor can tell the two apart. They are not equivalent evidence of consent and
the record must not blur them.

### Idempotency

`client_reference` makes a retry safe. The unique constraint on `end_to_end_id`
would also catch a duplicate — but only at INSERT, **after** the payment had
already been ordered at the bank. A double-tapped button would have sent the
money twice and merely failed to record the second. Now checked before anything
happens, returning the original payment.

### Duplicate linked accounts

No unique constraint existed on `(username, bank_id, account_number)`, and
`add_link` inserted blindly. Hit live: one user had two rows for the same COOP
account with conflicting default flags.

Not cosmetic. The aggregated balance sums every linked account, so a duplicate
**shows the user money they do not have**, and default resolution takes the
first match, making the account used for a transfer ambiguous. Fixed in the
service, in the model, and with a migration that collapses existing duplicates
while merging default flags upward so nobody loses a default they had set.

---

## New endpoints

| Endpoint | Purpose |
|---|---|
| `POST /v1/admin/auth/login` | Operator login |
| `GET /v1/admin/auth/me` | Current operator |
| `GET/POST /v1/admin/ledger/fee-rules` | List / create pricing |
| `POST /v1/admin/ledger/fee-rules/{id}/revise` | Publish a new version |
| `DELETE /v1/admin/ledger/fee-rules/{id}/versions/{v}` | Retire a version |
| `GET /v1/admin/ledger/fee-rules/preview` | Price a hypothetical payment |
| `GET /v1/admin/ledger/reconciliation` | Per-bank volume and revenue |
| `GET /v1/admin/ledger/payments/{id}/entries` | Ledger entries for a payment |
| `GET /v1/superapp/transactions` | The user's own payment history |
| `GET/DELETE /v1/superapp/consents` | Consent screen and revocation |
| `DELETE /v1/superapp/consents/apps/{id}` | Disconnect an application |
| `GET /v1/superapp/consents/scopes` | Scope catalogue |

---

## Tests

100 tests, all in-process — no server or container required, so they run in CI.

| File | Covers |
|---|---|
| `tests/test_ledger.py` | Balance invariants, immutability, fee pricing, versioning, reconciliation |
| `tests/test_consent.py` | Pseudonym unlinkability, consent lifecycle, vault, claim assembly |
| `tests/test_e2e_superapp_p2p.py` | Full journey against the real app: registration → linking → defaults → PIN-authorised transfer → ledger → history |

`tests/conftest.py` exists because `settings` reads the environment **once**, so
whichever test module imported `backend.config` first fixed the database URL for
the whole session. Two e2e tests passed alone and failed in the suite for that
reason — they were running against the committed SQLite file and inheriting
users from previous runs.

---

## Running it

```bash
# Tests
py -m pytest tests/ -q

# Local, SQLite
uvicorn backend.main:app --reload

# Full stack on Postgres (from the parent directory)
docker compose up --build
```

Migrations are applied by the container entrypoint. Applying them by hand:

```bash
alembic upgrade head
```

---

## Known gaps

- **Bank adapters are still simulated.** All six. The mock/real seam is clean
  (see the commented `httpx` blocks in `coop_cbs.py`), but no live CBS
  integration exists.
- **Vault key rotation is a one-way door.** Changing `FIN_ENCRYPTION_KEY` makes
  existing ciphertext unreadable; changing the pepper makes accounts unfindable
  by FIN. Proper rotation needs a key-version column and a re-encryption pass.
- **Direct (non-handle) payments cannot complete.** They need a Fayda consent
  token the Super App does not obtain. Extending PIN-as-consent to merchant
  payments is a separate decision, since the payee is not another EUPI user.
- **No developer platform yet.** No TPP authentication, no `app_id` tenancy
  scoping, no rate limits. `app_id` columns exist on ledger entries and
  pseudonyms in preparation.
- **Structured logging and CI are not set up.**
