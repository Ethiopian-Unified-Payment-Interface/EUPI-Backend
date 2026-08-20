# Developer Platform — Implementation Specification

Phase 3. The surface that turns EUPI from three internal applications into a
platform third parties can build on.

Audience: backend engineers on `EUPI-Backend`, frontend engineers on
`EUPI-Admin-Portal` and the new developer console. Companion to
[ARCHITECTURE.md](ARCHITECTURE.md) and [REMAINING.md](REMAINING.md).

Every file path, column, and function name below was checked against the code at
Alembic head `c8a52f7b3d41`. Where this document contradicts an existing
docstring, the contradiction is called out rather than silently resolved.

---

## 1. What Phase 3 is

A third-party developer can today read `/openapi.json` and see AIS and PIS
endpoints. They cannot obtain a credential, so nothing is reachable. Phase 3
builds the door:

1. A developer self-registers, submits KYB, and is approved by an operator.
2. They create an application and receive a `client_id` / `client_secret`.
3. They obtain a token — app-level, or user-delegated after a consent screen.
4. Their calls are scope-checked, tenant-isolated, rate-limited, and idempotent.
5. They receive webhooks when payments settle.

### What Phase 3 is not

- **Not open banking.** The API exposes EUPI's own ledger and orchestration, not
  bank data brokered under a consent mandate. Keep the developer-facing copy in
  Stripe's register, not Tink's.
- **Not the mini-app platform.** In-Super-App distribution is Phase 7 and depends
  on this landing first.
- **Not live money.** Every bank rail is simulated. Phase 3 ships a sandbox that
  is honest about being one.

---

## 2. Decisions needed before code

Four choices change the shape of the work. Recommendations given; none are
engineering-only calls.

| # | Decision | Recommendation |
|---|---|---|
| D1 | Does `client_credentials` alone ever reach user data? | **No.** App-level tokens get app-owned resources only. User data requires an authorization-code token carrying a `psu_id`. |
| D2 | Where does the user approve a consent request? | A **gateway-issued consent page hosted on a new external-facing Next.js deployable**, shared with the developer console. Not the internal portal. Super App deep-link approval is a Phase 7 enhancement. |
| D3 | Sandbox and live: one credential or two? | **Two.** `environment` already exists on `developer_apps` and `merchants`. A sandbox `client_id` must never be accepted on a live route. |
| D4 | Rate-limit backing store | **Postgres fixed-window counters** for Phase 3 — there is no Redis in `docker-compose.yml` and adding one is a separate operational decision. Design the port so Redis is an adapter swap. |

D2 is the one worth debating. The alternative — serving the consent page from
FastAPI with Jinja templates — is less work but puts an unstyled HTML page in the
middle of a developer's checkout flow, and gives the frontend team no seam. The
recommendation costs a new deployable and buys a surface that Phase 7 and the
developer console both need anyway.

---

## 3. Prerequisites — four defects that must be fixed first

These are not new features. Each one, left in place, makes a Phase 3 component
either insecure or untestable. Fix and test them before starting §5.

### P1 · `/v1/payments/initiate` accepts any bearer string

[`api_v1/payments.py:95-108`](backend/presentation/api_v1/payments.py#L95-L108)
declares `credentials: HTTPAuthorizationCredentials = Depends(_bearer)` and never
reads it. `HTTPBearer()` checks that a header is *present and well-formed* —
nothing more. `Authorization: Bearer x` initiates a payment today.

By contrast [`api_v1/accounts.py:75`](backend/presentation/api_v1/accounts.py#L75)
does pass the token into `AISService` as a consent token, which validates it.
The PIS path has no equivalent.

*Fix as part of §7's `require_scopes` dependency — do not paper over it with a
bare decode, because the correct check is scope-aware.*

### P2 · `required_scope` is accepted and ignored

[`ais_service.py:240-260`](backend/application/use_cases/ais_service.py#L240-L260)
takes `required_scope` and documents that it "assert[s] it carries the required
scope". The body verifies the token and the KYC level. **The parameter is never
read.** Three call sites pass `accounts:read` and `transactions:read` believing
they are enforced.

This is the single most misleading line in the codebase: a reviewer sees scope
enforcement in the signature and at the call sites, and there is none.

### P3 · Three disjoint scope vocabularies

| Source | Values |
|---|---|
| [`domain/models/consent.py`](backend/domain/models/consent.py) `ConsentScope` | `identity:read:basic`, `identity:read:name`, `identity:read:phone`, `identity:read:fin`, `transactions:read:own`, `payments:initiate`, `webhooks:receive` |
| [`ais_service.py`](backend/application/use_cases/ais_service.py) call sites | `accounts:read`, `transactions:read` |
| [`admin_repositories.py:194`](backend/infrastructure/database/admin_repositories.py#L194) seed | `ais:read`, `pis:write` |

No value in rows 2 or 3 appears in row 1. `ConsentScope` is the canonical
vocabulary — it is the only one with descriptions, restriction rules, and a
`self_service()` catalogue. §4 unifies on it.

### P4 · `end_to_end_id` is globally unique

[`models.py`](backend/infrastructure/database/models.py) declares
`end_to_end_id` as `unique=True` on `payments`. Two different developers both
using `INV-001` collide: the second receives a 409 telling them the ID exists,
which is a cross-tenant information leak *and* a functional block on a value
they legitimately own.

Must become `UNIQUE(app_id, end_to_end_id)`.

Related, and worth correcting in [REMAINING.md](REMAINING.md) §3: that file says
a duplicate "raises `IntegrityError` → 500". It does not — `initiate_payment`
catches it and returns a 409 with a helpful message. The real gap is narrower:
a 409 is not idempotency. A retried request must return **the original payment
with 200**, not an error. See §9.

---

## 4. The unified scope vocabulary

Extend `ConsentScope` in
[`domain/models/consent.py`](backend/domain/models/consent.py). Do not create a
second enum.

```python
class ConsentScope(str, Enum):
    # ── Identity ──────────────────────────────────────────────────────────────
    IDENTITY_READ_BASIC = "identity:read:basic"
    IDENTITY_READ_NAME  = "identity:read:name"
    IDENTITY_READ_PHONE = "identity:read:phone"
    IDENTITY_READ_FIN   = "identity:read:fin"      # RESTRICTED

    # ── Money ─────────────────────────────────────────────────────────────────
    ACCOUNTS_READ         = "accounts:read"          # NEW — AIS balances
    TRANSACTIONS_READ_OWN = "transactions:read:own"
    PAYMENTS_INITIATE     = "payments:initiate"
    PAYMENTS_READ_OWN     = "payments:read:own"      # NEW — app's own payments

    # ── Platform ──────────────────────────────────────────────────────────────
    WEBHOOKS_RECEIVE = "webhooks:receive"
```

Two additions, both filling gaps the AIS/PIS routes already assume:

- **`accounts:read`** — replaces the phantom scope of the same name that
  `ais_service` already passes. Balance data across a user's linked accounts.
  Requires user consent.
- **`payments:read:own`** — an app reading the status of payments it initiated.
  This is app-level, not user-delegated: it needs no `psu_id` and no user
  consent, because the app is reading its own records.

### Which token type may carry which scope

This table is the authorisation model. Implement it as data, not as scattered
conditionals.

| Scope | `tpp_access` (app) | `tpp_user_access` (delegated) | User consent |
|---|---|---|---|
| `identity:read:basic` | ✗ | ✓ | required |
| `identity:read:name` | ✗ | ✓ | required |
| `identity:read:phone` | ✗ | ✓ | required |
| `identity:read:fin` | ✗ | ✓ | required + licensing review |
| `accounts:read` | ✗ | ✓ | required |
| `transactions:read:own` | ✗ | ✓ | required |
| `payments:initiate` | ✗ | ✓ | required |
| `payments:read:own` | ✓ | ✓ | none |
| `webhooks:receive` | ✓ | ✗ | none |

Add to `ConsentScope`:

```python
@property
def is_app_level(self) -> bool:
    """
    Whether an app-only token may carry this scope.

    App-level scopes touch the application's own records or its integration
    mechanics. Everything touching a user requires a delegated token, because
    client_credentials proves only that the developer holds a secret — it
    carries no evidence that any user agreed to anything.
    """
    return self in (ConsentScope.PAYMENTS_READ_OWN, ConsentScope.WEBHOOKS_RECEIVE)
```

`requires_user_consent` already exists and returns `False` only for
`WEBHOOKS_RECEIVE`. Extend it to also exclude `PAYMENTS_READ_OWN`.

### Migrating existing rows

The seed in `admin_repositories._seed_default_merchants` and the two
`kyb_requests` rows carry `ais:read` / `pis:write`. Map them in the §5 migration:

| Legacy | Becomes |
|---|---|
| `ais:read` | `accounts:read`, `transactions:read:own` |
| `pis:write` | `payments:initiate`, `payments:read:own` |

Then change the seed to emit `ConsentScope` values, and add a startup assertion
that every string in `developer_apps.allowed_scopes` parses to a `ConsentScope` —
an unparseable scope must fail loudly at boot, not silently deny at request time.

---

## 5. Data model changes

One migration, `down_revision = "c8a52f7b3d41"`. Suggested slug:
`d9f11a4c7e02_developer_platform.py`.

### 5.1 `developer_apps` — add credentials, webhooks, limits

```python
op.add_column("developer_apps", sa.Column("client_secret_hash", sa.String(255), nullable=True))
op.add_column("developer_apps", sa.Column("secret_created_at",  sa.DateTime(), nullable=True))
op.add_column("developer_apps", sa.Column("secret_rotated_at",  sa.DateTime(), nullable=True))
op.add_column("developer_apps", sa.Column("webhook_url",        sa.String(512), nullable=True))
op.add_column("developer_apps", sa.Column("webhook_secret",     sa.Text(), nullable=True))
op.add_column("developer_apps", sa.Column("redirect_uris",      sa.Text(), nullable=False, server_default="[]"))
op.add_column("developer_apps", sa.Column("rate_limit_per_min", sa.Integer(), nullable=False, server_default="60"))
op.add_column("developer_apps", sa.Column("suspended_reason",   sa.Text(), nullable=True))
```

`client_secret_hash` does not exist today — `DeveloperAppRecord` has `client_id`
and no secret at all. Hash it with the existing `Argon2PasswordHasher` behind
`PasswordHasherPort`; do not introduce a second hashing scheme.

`webhook_secret` is the HMAC signing key, encrypted at rest via the existing
`IdentityVaultPort` (`FernetIdentityVault`). It is a shared secret the developer
must be able to read back, so it cannot be a one-way hash — which is exactly why
it must be encrypted rather than stored plainly.

`redirect_uris` is a JSON list, matching the existing `allowed_scopes`
convention. Exact-match only at authorize time: no prefix matching, no wildcards,
no `localhost` exemption outside `environment = "SANDBOX"`.

### 5.2 `payments` — tenancy and per-tenant idempotency

```python
op.add_column("payments", sa.Column("app_id", sa.String(64), nullable=True, index=True))
op.drop_constraint("payments_end_to_end_id_key", "payments", type_="unique")
op.create_unique_constraint("uq_payment_app_e2e", "payments", ["app_id", "end_to_end_id"])
```

`app_id` is nullable because Super App payments have no owning application —
consistent with `ledger_entries.app_id`, documented as "Null for Super App
originated activity."

**Postgres treats NULLs as distinct in a unique constraint**, so
`(NULL, 'X')` twice does not collide. Super App transfers therefore lose the
uniqueness guard they currently have. That path already performs its own
pre-flight idempotency check in
[`api_superapp/transfers.py`](backend/presentation/api_superapp/transfers.py), so
behaviour is preserved — but add a partial index to keep the database honest:

```python
op.create_index(
    "uq_payment_superapp_e2e", "payments", ["end_to_end_id"],
    unique=True, postgresql_where=sa.text("app_id IS NULL"),
)
```

### 5.3 New table — `authorization_codes`

Single-use, short-lived, PKCE-bound.

```python
op.create_table(
    "authorization_codes",
    sa.Column("code_hash",     sa.String(64),  primary_key=True),  # SHA-256 of the code
    sa.Column("app_id",        sa.String(64),  nullable=False, index=True),
    sa.Column("username",      sa.String(64),  nullable=False),
    sa.Column("scopes",        sa.Text(),      nullable=False),    # JSON list
    sa.Column("redirect_uri",  sa.String(512), nullable=False),
    sa.Column("code_challenge",        sa.String(128), nullable=False),
    sa.Column("code_challenge_method", sa.String(8),   nullable=False),
    sa.Column("expires_at",    sa.DateTime(),  nullable=False),
    sa.Column("consumed_at",   sa.DateTime(),  nullable=True),
    sa.Column("created_at",    sa.DateTime(),  nullable=False),
)
```

Store `code_hash`, never the code. A leaked table must not yield usable codes —
same reasoning as `pin_hash`.

`username` is stored, not `psu_id`: the pseudonym is resolved at token issuance
via `ConsentService.resolve_psu_id`, so the code row does not pin a mapping that
may not exist yet.

### 5.4 New table — `rate_limit_counters`

```python
op.create_table(
    "rate_limit_counters",
    sa.Column("client_id",    sa.String(64), primary_key=True),
    sa.Column("window_start", sa.DateTime(), primary_key=True),
    sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
)
```

Fixed 60-second windows. Rows older than one hour are pruned by the same
background worker that delivers webhooks (§10).

### 5.5 Widen `webhook_events`

```python
op.add_column("webhook_events", sa.Column("app_id",     sa.String(64), nullable=True, index=True))
op.add_column("webhook_events", sa.Column("event_type", sa.String(64), nullable=False, server_default="payment.settled"))
op.add_column("webhook_events", sa.Column("next_attempt_at", sa.DateTime(), nullable=True, index=True))
```

`next_attempt_at` is what makes retry-with-backoff queryable.
`get_pending_webhooks` currently returns *every* undelivered row, which becomes a
hot-loop the moment one endpoint is permanently down.

### 5.6 `merchants` — self-service registration

```python
op.add_column("merchants", sa.Column("password_hash", sa.String(255), nullable=True))
op.add_column("merchants", sa.Column("contact_name",  sa.String(100), nullable=True))
op.add_column("merchants", sa.Column("is_active",     sa.Boolean(), nullable=False, server_default=sa.true()))
```

Developers need to sign in to the console. Reuse `Argon2PasswordHasher`.

---

## 6. Token model

Two new types. Register both in
[`infrastructure/auth/jwt_handler.py`](backend/infrastructure/auth/jwt_handler.py)
and give each a decoder that asserts its exact type via the existing `_decode`.
The module docstring already explains why the assertion is load-bearing; the same
reasoning applies with more force here, because a TPP token that validated as a
`gateway_access` token would let a developer act as a consumer.

```python
TOKEN_TYPE_TPP:      Final = "tpp_access"
TOKEN_TYPE_TPP_USER: Final = "tpp_user_access"
```

### `tpp_access` — client credentials, no user

```json
{
  "sub": "app_live_9x8c7v",
  "type": "tpp_access",
  "client_id": "client_ethiopay_99",
  "app_id": "app_live_9x8c7v",
  "merchant_id": "mer_5678",
  "environment": "SANDBOX",
  "scopes": ["payments:read:own", "webhooks:receive"],
  "jti": "…", "iss": "kifiya-open-gateway", "iat": 0, "exp": 0
}
```

TTL 1 hour. `sub` is the `app_id` — the acting principal is the application.
There is deliberately **no `psu_id` and no `kyc_level`**: absence of those claims
is what stops this token reaching a user-scoped route.

### `tpp_user_access` — authorization code, acts for one user

```json
{
  "sub": "psu_7f3a9c2e14b84d6fa1e5c8027b93de41",
  "type": "tpp_user_access",
  "app_id": "app_live_9x8c7v",
  "client_id": "client_ethiopay_99",
  "environment": "SANDBOX",
  "scopes": ["accounts:read", "payments:initiate"],
  "kyc_level": "STANDARD",
  "consent_method": "tpp_authorization_code",
  "jti": "…", "iss": "kifiya-open-gateway", "iat": 0, "exp": 0
}
```

TTL 1 hour, refreshable. Three properties matter:

- **`sub` is the pseudonym, never the username.** The `username` never leaves the
  gateway. Resolve internally with `ConsentService.resolve_username(psu_id, app_id)`,
  which already scopes the lookup to the owning app.
- **`consent_method` extends the existing enumeration.** `CONSENT_METHOD_FAYDA_OTP`
  and `CONSENT_METHOD_SUPERAPP_PIN` exist; add
  `CONSENT_METHOD_TPP_AUTH_CODE: Final = "tpp_authorization_code"`. A payment
  authorised by a third-party redirect is not the same evidence as one authorised
  by an in-app PIN, and the ledger must be able to tell them apart.
- **Scopes in the token are a ceiling, not a grant.** Every user-scoped read must
  re-check live consent via `ConsentService.has_consent`. A user who revokes at
  10:00 must be denied at 10:01, not at token expiry. This is why
  `build_claims` re-reads consent per request, and the same discipline applies
  to `accounts:read`.

### Refresh tokens

Opaque, 30-day, single-use with rotation, stored hashed in
`consent_tokens` (the table already exists for revocation tracking) with a
`token_type` discriminator column. Reuse of a consumed refresh token revokes the
whole chain — the standard detection for a stolen refresh token.

---

## 7. OAuth endpoints

New router: `backend/presentation/api_oauth/`, registered in
[`main.py`](backend/main.py) alongside the others with `prefix=API_V1_PREFIX`.

### `POST /v1/oauth/token`

`application/x-www-form-urlencoded`, per RFC 6749. Client authentication by HTTP
Basic (`client_id:client_secret`) or form body; accept both, prefer Basic.

**`grant_type=client_credentials`**

```
grant_type=client_credentials&scope=payments:read:own webhooks:receive
```

```json
{ "access_token": "eyJ…", "token_type": "Bearer", "expires_in": 3600,
  "scope": "payments:read:own webhooks:receive" }
```

Requesting a non-app-level scope is `400 invalid_scope`. Never silently narrow
the grant — a developer who asked for `accounts:read` and received a token
without it will debug the wrong thing for a day.

**`grant_type=authorization_code`**

```
grant_type=authorization_code&code=…&redirect_uri=…&code_verifier=…
```

Validate in this order, failing closed at each step: code exists → not consumed →
not expired → `app_id` matches the authenticated client → `redirect_uri` matches
byte-for-byte → `SHA256(code_verifier) == code_challenge`. Mark consumed in the
**same transaction** that issues the token, so a concurrent double-exchange
cannot yield two tokens.

**`grant_type=refresh_token`** — rotate, revoke the presented token, return a new pair.

### `GET /v1/oauth/authorize`

Not an API call — a browser redirect target.

| Param | Required | Notes |
|---|---|---|
| `client_id` | ✓ | Must be ACTIVE, KYB-approved |
| `redirect_uri` | ✓ | Exact match against `redirect_uris` |
| `response_type` | ✓ | `code` only |
| `scope` | ✓ | Space-separated; ⊆ `allowed_scopes` |
| `state` | ✓ | Opaque, echoed back. Reject if absent — CSRF protection is not optional |
| `code_challenge` | ✓ | PKCE, base64url |
| `code_challenge_method` | ✓ | `S256` only. Reject `plain` |

On valid input: create a pending consent request, `302` to the consent UI at
`{CONSENT_UI_BASE_URL}/consent/{request_id}`.

On an **invalid `redirect_uri` or unknown `client_id`**: render an error page.
Do **not** redirect. Redirecting to an unvalidated URI is an open redirect.

Every other failure redirects to the validated `redirect_uri` with
`?error=…&state=…` per RFC 6749 §4.1.2.1.

### `POST /v1/oauth/consent/{request_id}/approve`

Called by the consent UI after the user authenticates. Requires a
`superapp_session` token — the user proves identity with their existing PIN
login, and the gateway is the only party that ever sees it.

```json
{ "granted_scopes": ["accounts:read", "payments:initiate"] }
```

Server-side, in one transaction:

1. Assert `granted_scopes ⊆ requested ⊆ app.allowed_scopes`.
2. Reject `identity:read:fin` unless the app holds an approved licensing review —
   `ConsentService.grant` already raises `RestrictedScopeError` for this;
   let it propagate to a 403 rather than re-implementing the check.
3. `ConsentService.grant(...)` per scope.
4. Allocate the authorization code, store `SHA256(code)`, TTL **60 seconds**.
5. Return `{"redirect_to": "<redirect_uri>?code=…&state=…"}`.

Partial approval is a first-class outcome: a user may grant `accounts:read` and
deny `identity:read:name`. The token then carries only what was granted, and the
developer discovers this from the `scope` field in the token response.

### `POST /v1/oauth/revoke` · `POST /v1/oauth/introspect`

RFC 7009 and 7662. Introspection is authenticated and returns only the presented
token's own metadata — never another app's.

---

## 8. Scope enforcement

Mirror the shape of
[`api_admin/auth_deps.py`](backend/presentation/api_admin/auth_deps.py), which
is already the house pattern for this: a `Depends`-able factory that fails closed.

New file: `backend/presentation/api_oauth/auth_deps.py`.

```python
@dataclass(frozen=True)
class TPPPrincipal:
    """The authenticated caller on a /v1 developer route."""
    app_id: str
    client_id: str
    merchant_id: str
    environment: str
    token_scopes: frozenset[ConsentScope]
    psu_id: str | None      # None for app-level tokens
    username: str | None    # Resolved internally. NEVER serialised.


def require_scopes(*needed: ConsentScope) -> Callable[..., TPPPrincipal]:
    """
    Admit only callers whose token carries every listed scope AND — for
    user-scoped routes — whose user still consents to each one.

    The live consent re-check is the point. Scopes in a token are what the user
    agreed to when it was issued; consent may have been withdrawn since. A
    revocation that only takes effect at token expiry is not a revocation.
    """
```

Order of checks, all failing closed:

1. Bearer header present → else `401`
2. Decode as `tpp_user_access`, else `tpp_access`, else `401`. Assert the type.
3. `jti` not revoked (`repo.is_token_revoked`) → else `401`
4. App still `ACTIVE` and KYB `APPROVED`, re-read per request → else `403`.
   *Same reasoning as the admin dependency re-reading the operator: a suspension
   must bite immediately, not at the end of the TTL.*
5. Every `needed` scope in `token_scopes` → else `403 insufficient_scope`
6. Any `needed` scope where `requires_user_consent`: token must be
   `tpp_user_access`, and `ConsentService.has_consent(username, app_id, scope)`
   must hold → else `403`
7. Rate limit (§11) → else `429`
8. Environment matches the route's environment → else `403`

Then apply to the existing `/v1` routes:

| Route | Guard |
|---|---|
| `GET /v1/accounts` | `require_scopes(ACCOUNTS_READ)` |
| `GET /v1/accounts/{bank}/{acct}` | `require_scopes(ACCOUNTS_READ)` |
| `GET /v1/accounts/{bank}/{acct}/transactions` | `require_scopes(TRANSACTIONS_READ_OWN)` |
| `POST /v1/payments/initiate` | `require_scopes(PAYMENTS_INITIATE)` — **closes P1** |
| `POST /v1/payments/{id}/verify` | `require_scopes(PAYMENTS_INITIATE)` |
| `POST /v1/payments/{id}/order` | `require_scopes(PAYMENTS_INITIATE)` |
| `GET /v1/payments/{id}` | `require_scopes(PAYMENTS_READ_OWN)` |

### Fixing P2 properly

Delete the unused `required_scope` parameter from
`AISService._validate_consent`. Do not implement scope checking there.

The reasoning: `AISService` receives an opaque consent token and cannot know
whether the caller is a Super App user or a TPP. Scope authorisation is a
presentation-layer concern about *who is calling*; the use case's job is
verifying the consent token and KYC level, which it already does correctly. A
half-scope-check inside the service would be a second enforcement path — exactly
what the token-type work eliminated elsewhere.

Leaving the parameter in place with a docstring claiming it is enforced is the
worst of the three options.

---

## 9. Tenant isolation

The highest-risk item in Phase 3. One missed `WHERE app_id = …` leaks one
developer's payment data to another. It must be structurally impossible, not
review-dependent.

### The pattern

New `backend/infrastructure/database/tenant_scope.py`:

```python
class AppScope:
    """
    Whose data a repository may see.

    Constructed only via `for_app` or `internal` — never from a bare string, and
    never defaulting. A repository that forgets to pass one fails to construct,
    which is the entire point: the unsafe case must be a compile-time-visible
    omission, not a silently-unfiltered query.
    """
    __slots__ = ("_app_id", "_is_internal")

    @classmethod
    def for_app(cls, app_id: str) -> "AppScope": ...

    @classmethod
    def internal(cls) -> "AppScope":
        """
        Unfiltered access, for admin and Super App paths.

        Deliberately verbose at the call site. `AppScope.internal()` in a code
        review is a question worth asking; an absent filter is invisible.
        """


class TenantScopedRepository(RepositoryBase):
    def __init__(self, db: Database, scope: AppScope) -> None:
        super().__init__(db)
        self._scope = scope

    def _scoped(self, session: Session, model: type) -> Query:
        """Every query in a subclass starts here. No exceptions."""
        query = session.query(model)
        if self._scope.is_internal:
            return query
        return query.filter(model.app_id == self._scope.app_id)
```

`PaymentRepository` and `LedgerRepository` extend it and replace every
`session.query(X)` with `self._scoped(session, X)`. Both already extend
`RepositoryBase` and use the `with self._session()` idiom, so this is mechanical.

### Enforcement that outlives the reviewer

A convention holds for about six weeks. Add both of these:

1. **A test that greps the source.** Assert no `session.query(` appears in
   `payment_repository.py` or `ledger_repository.py` outside `_scoped`. Crude,
   and it will catch the regression that code review will not.
2. **Isolation tests.** Two apps, overlapping `end_to_end_id`s, and explicit
   assertions that app A's token returns 404 — not 403 — for app B's
   `payment_id`. A 403 confirms the resource exists, which is itself a leak.

### Threading `app_id` through writes

`PISService.initiate_payment` must accept and persist `app_id`. It reaches:

- `payments.app_id` (§5.2)
- `ledger_entries.app_id` — the column and the domain field already exist and are
  documented for exactly this; nothing populates them
- `webhook_events.app_id` (§5.5)

Super App paths pass `None` and construct `AppScope.internal()`.

---

## 10. Webhook delivery

Nothing delivers webhooks today. `create_webhook_event`,
`mark_webhook_delivered`, and `get_pending_webhooks` all exist in
[`payment_repository.py:245-291`](backend/infrastructure/database/payment_repository.py#L245-L291);
**no caller invokes the getter.**

### The worker

An `asyncio` task started in the `main.py` lifespan, polling every 5 seconds:

```
claim due events (next_attempt_at <= now, delivered = false, attempts < 8)
  → POST with HMAC signature
  → 2xx: mark delivered
  → else: attempts += 1, next_attempt_at = now + backoff(attempts)
```

Backoff: `10s, 30s, 2m, 10m, 1h, 6h, 24h`, then dead-letter. Total ~31 hours.

Claim rows with `SELECT … FOR UPDATE SKIP LOCKED` so two workers never deliver
the same event twice. This matters more than it looks: the payment cache being
per-process already blocks running two workers ([REMAINING.md](REMAINING.md) §1),
and that will be fixed — the webhook worker must not become the next thing that
breaks under a second process.

### Signature

```
X-EUPI-Signature: t=1755400000,v1=<hex hmac_sha256(secret, "{t}.{body}")>
X-EUPI-Event-Id: WH-3A7F9E2114B84D6F
X-EUPI-Event-Type: payment.settled
```

Sign `timestamp.body`, not `body` alone — without the timestamp in the signed
payload, a captured request replays forever. Document a 5-minute tolerance and
tell developers to reject outside it.

Events: `payment.settled`, `payment.failed`, `consent.revoked`,
`app.suspended`. `consent.revoked` is the one developers will forget to handle
and the one that matters most for correctness on their side.

### Depends on

The callback handler must persist terminal status first
([REMAINING.md](REMAINING.md) §1 — confirmed still open: `webhooks.py` writes
`_payment_store` only and never calls `repo.update_payment`). A webhook fired
from a status the database does not hold is a webhook that disagrees with the API
the developer will call next.

---

## 11. Rate limiting

Per `client_id`, fixed 60-second windows, `rate_limit_counters` (§5.4).

Define `RateLimitPort` in `backend/application/ports/` beside the existing ports,
with `PostgresRateLimiter` as the first adapter. Redis becomes an adapter swap,
consistent with how `BankPort` and `FraudCheckPort` are arranged.

Defaults: 60 req/min sandbox, `developer_apps.rate_limit_per_min` for live.
`POST /v1/oauth/token` gets its own tighter bucket — 10/min per `client_id` —
because token endpoints are where credential-stuffing lands.

Always return the headers, not just on rejection:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 41
X-RateLimit-Reset: 1755400060
Retry-After: 23          # 429 only
```

Counting happens **after** authentication, so an unauthenticated flood cannot
exhaust a real developer's quota by presenting their `client_id`.

---

## 12. Idempotency

Closes P4. Applies to `POST /v1/payments/initiate`.

```
if a payment exists for (app_id, end_to_end_id):
    if the request body is byte-identical:  200 + the original payment
    else:                                   409 idempotency_key_reuse
else:
    create → 201
```

Returning the original on a retry is the whole feature: a developer whose
connection dropped mid-request must be able to retry safely. A 409 forces them
to guess whether the first attempt moved money.

The body comparison needs a stored fingerprint — add `request_fingerprint`
(SHA-256 of the canonical JSON body) to `payments` in the §5.2 migration.

Port the pre-flight check that
[`api_superapp/transfers.py`](backend/presentation/api_superapp/transfers.py)
already performs; do not write a second implementation. Extract it to a shared
helper and have both call sites use it.

---

## 13. Admin Portal work

Repo: `EUPI-Admin-Portal`. Operator side only — the developer-facing console is
§14.

### 13.1 Fix the KYB queue before extending it

[`kyb-approval-queue.tsx:31`](../EUPI-Admin-Portal/components/kifiya/views/kyb-approval-queue.tsx#L31)
has three defects in one function:

```ts
const res = await fetch(`http://192.168.11.126:8000/v1/admin/developers/kyb-requests/${id}`, {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json' },   // no Authorization
  ...
})
```

1. **A hardcoded LAN IP.** Works on one developer's machine, 404s or hangs
   everywhere else, and bypasses `API_BASE_URL`.
2. **No auth header.** The endpoint requires `require_admin`, so this returns 401
   in every environment where it resolves at all.
3. **The failure path removes the row anyway** — the comment says "we'd probably
   fallback to removing it locally". The operator sees the request vanish and
   concludes it was approved. Nothing was approved.

Defect 3 is the same class as the fabricated dashboard figures and the empty risk
panel: the UI reports success it has no evidence for. On a KYB queue that means
an unapproved merchant is believed approved.

Rewrite with `apiMutate('/v1/admin/developers/kyb-requests/{id}', 'PUT', …)`,
which supplies `authHeaders()`, handles 401 via `forceSignOut`, and throws the
API's own `detail`. Surface the error and leave the row in the queue.

### 13.2 New operator surfaces

New endpoints, all under `require_admin` unless noted, mounted in the existing
Developers tab group:

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/admin/developers/apps` | POST | Create an app for a merchant; return the secret **once** |
| `/v1/admin/developers/apps/{app_id}` | PATCH | Scopes, rate limit, redirect URIs, status |
| `/v1/admin/developers/apps/{app_id}/rotate-secret` | POST | Rotate; show once |
| `/v1/admin/developers/apps/{app_id}/suspend` | POST | Immediate kill switch |
| `/v1/admin/developers/apps/{app_id}/usage` | GET | Request counts, error rate, 429s |
| `/v1/admin/developers/licensing-reviews` | GET/PUT | Approve `identity:read:fin` per app |
| `/v1/admin/developers/webhooks/{event_id}/redeliver` | POST | Manual retry |

UI work, following the `useApiData` / `DataState` conventions already
established:

- **App detail drawer** — scopes as checkboxes sourced from
  `GET /v1/superapp/consents/scopes` (the catalogue endpoint already exists;
  do not hardcode a second list in TypeScript), redirect URIs, rate limit,
  usage sparkline.
- **Secret-reveal modal** — shown once, with copy-to-clipboard and an explicit
  "this will not be shown again". No secret in any list response, ever.
- **Licensing review queue** — `identity:read:fin` requests. This is the screen
  that decides whether an app may read a national ID; it needs the requesting
  app, the stated legal basis, and the reviewing operator recorded to
  `audit_logs`.
- **Promote the existing dead components.** `consent-view`,
  `consent-lifecycle-timeline`, and `consent-lookup-bar` are built and
  unreferenced ([REMAINING.md](../EUPI-Admin-Portal/REMAINING.md) §1). Consent
  management is a Phase 3 operator requirement, so they get mounted here — but
  four of the ten unimplemented endpoints in §1a are theirs, so land the backend
  routes in the same PR or they 404 on mount.

### 13.3 Data honesty

`MerchantStats.api_traffic_per_day` and `avg_setup_time_days` currently return a
structural `0`. Once §11 counts requests, `api_traffic_per_day` becomes real.
`avg_setup_time_days` becomes computable as KYB-submitted → first-successful-call.
Until each is real, render "not tracked", not `0` — a zero reads as "none
happened".

---

## 14. Developer console — new deployable

Per D2. A Next.js app serving two external-facing surfaces that share an origin
and an auth model, and must not share either with the internal portal.

Suggested repo: `EUPI-Developer-Console`. Reuse the portal's `useApiData` /
`apiMutate` / `DataState` primitives — copy them rather than importing across
repos; there is no shared package yet and Phase 3 is not the time to create one.

### 14.1 The consent UI

The user-facing half. Route `/consent/{request_id}`.

#### Where it appears

**In a browser, on EUPI's origin.** The user never sees it inside the third
party's app, and the third party never sees the PIN.

```text
Third-party app
  → 302  GET  /v1/oauth/authorize?client_id=…&code_challenge=…
  → 302  {CONSENT_UI_BASE_URL}/consent/{request_id}      ← the user is here
         · handle + PIN sign-in
         · per-scope toggles
  → POST /v1/oauth/consent/{request_id}/approve
  → 302  {redirect_uri}?code=…&state=…                   ← back to the TPP
```

The redirect is the security model, not a UX convenience. The authorization code
must be issued by whoever authenticated the user, and the PIN must be entered
only on an origin EUPI controls. A consent screen rendered by the TPP — however
convenient — is a credential-harvesting form with EUPI's branding on it.

**For mobile TPPs, this must open in the system browser** — `SFSafariViewController`
/ `ASWebAuthenticationSession` on iOS, Custom Tabs on Android — **never an
embedded `WebView`**. A host app owning the WebView can read the PIN as it is
typed, which defeats the entire redirect. Reject an embedded WebView where it can
be detected, and state the requirement in `/docs`; RFC 8252 §8.12 is the citation
to give developers who argue.

Approval inside the Super App by deep link (`eupikifiya://`) is a Phase 7
enhancement, not this. The scheme already appears in the Super App's receive-money
QR but no handler is registered for it, so nothing consumes it today.

#### The flow

1. `GET /v1/oauth/consent/{request_id}` → app name, merchant name, requested
   scopes with `ConsentScope.description` text, and `environment`.
2. The user signs in with their existing handle + PIN → `superapp_session`.
3. Scope list with per-scope toggles. Non-restricted scopes default **on**;
   `identity:read:fin`, if present, defaults **off** and carries a distinct
   visual treatment.
4. Approve → `POST /v1/oauth/consent/{request_id}/approve` → follow
   `redirect_to`. Deny → redirect with `error=access_denied`.

Constraints that are requirements, not polish:

- **Never render the raw scope string as the primary label.** Use
  `description` from the catalogue endpoint. A user cannot consent to
  `identity:read:phone`; they can consent to "See your phone number."
- **Show the merchant's legal name**, not just the app name. "EthioPay Checkout
  wants access" is phishable; "EthioPay Solutions PLC" is checkable.
- **`environment: "SANDBOX"` must be unmissable.** A user must never be tricked
  into granting live access to a sandbox integration or vice versa.
- **No PIN in any URL, no token in `localStorage` on this surface.** The consent
  session is a short-lived in-memory token; this origin is public.

### 14.2 The developer console

| Route | Contents |
|---|---|
| `/signup`, `/login` | Merchant self-registration against §5.6 |
| `/kyb` | Submit company name, TIN, requested scopes; track status |
| `/apps` | List, create, view |
| `/apps/{id}` | `client_id`, secret rotation, redirect URIs, scopes, environment toggle |
| `/apps/{id}/webhooks` | Endpoint URL, signing secret, delivery log, redeliver |
| `/apps/{id}/logs` | Recent API calls: status, scope denials, 429s |
| `/docs` | Quickstart, scope reference, sandbox test users |

Backend routes for these live under a new `/v1/developers/*` prefix guarded by a
merchant session — **not** `/v1/admin/*`. A developer must never hold an
`admin_session`, and the two surfaces must not share a router.

`/apps/{id}/logs` is the highest-value screen and the easiest to under-build. A
developer whose call was denied for a missing scope needs to see *which* scope,
or they will open a support ticket. Return the scope name in the 403 body and
render it here.

---

## 15. Error catalogue

OAuth endpoints use RFC 6749 codes in an `{"error", "error_description"}` body.
Everything else uses FastAPI's `{"detail": …}`, matching the existing API.

| HTTP | `error` | When |
|---|---|---|
| 400 | `invalid_request` | Missing or malformed parameter |
| 400 | `unsupported_grant_type` | Not one of the three grants |
| 400 | `invalid_scope` | Unknown scope, or not in `allowed_scopes`, or app-level token requesting a user scope |
| 401 | `invalid_client` | Unknown `client_id`, bad secret |
| 400 | `invalid_grant` | Code unknown, expired, consumed, PKCE mismatch, `redirect_uri` mismatch |
| 403 | `insufficient_scope` | Token lacks the scope. **Name it in `error_description`.** |
| 403 | `consent_required` | Scope present in token, live consent revoked |
| 403 | `app_suspended` | App or merchant not ACTIVE |
| 403 | `restricted_scope` | `identity:read:fin` without a licensing review |
| 404 | — | Resource not found **or** owned by another tenant. Never distinguish. |
| 409 | `idempotency_key_reuse` | Same `end_to_end_id`, different body |
| 429 | `rate_limit_exceeded` | With `Retry-After` |

Two rules worth stating because they are easy to get backwards:

- **404, never 403, for another tenant's resource.** A 403 confirms existence.
- **`insufficient_scope` must name the scope.** Withholding it protects nothing
  — the caller already knows their own token — and costs every developer an hour.

---

## 16. Tests

Backend currently has 100 tests across three files. Phase 3 needs its own,
in this order of value:

**Tenant isolation** — `tests/test_tenant_isolation.py`. Two apps, overlapping
`end_to_end_id`s. Assert cross-tenant reads 404 for payments, ledger entries,
webhook events, and `psu_id` resolution. Plus the source-grep test from §9.

**OAuth flows** — `tests/test_oauth.py`. Happy paths for all three grants;
then the failure cases that actually matter: PKCE downgrade to `plain`, code
replay, code issued to app A redeemed by app B, `redirect_uri` mismatch,
`state` absent, refresh-token reuse revoking the chain.

**Scope enforcement** — `tests/test_scope_enforcement.py`. For every route in
§8: correct scope passes; missing scope 403s; app-level token on a user route
403s; scope in token but consent revoked 403s. That last one is the regression
that would otherwise ship.

**Idempotency** — identical retry returns the original with 200; differing body
409s; two apps may share an `end_to_end_id`.

**Webhooks** — signature verifies against a known vector; backoff schedule;
dead-letter after 8; `SKIP LOCKED` prevents double delivery.

**Contract test** — snapshot `/openapi.json` and fail when a portal or console
endpoint string has no matching path. This is what would have caught the ten
portal endpoints calling routes that were never implemented, and it is cheap.

### CI is a prerequisite, not a follow-up

No repo has `.github/workflows`. Adding it is roughly a day and it protects
everything above. Backend: `ruff`, `mypy`, `pytest`, image build. Portal and
console: `tsc --noEmit`, `next build`. Do this first — a 40-file change to
authorisation logic without CI is the highest-risk way to spend four weeks.

---

## 17. Sequencing

Nine work packages. P-items are §3 prerequisites.

| # | Package | Depends on | Rough size |
|---|---|---|---|
| 0 | CI on all three repos | — | 1 day |
| 1 | P2 (delete dead `required_scope`), P3 (unify scopes), §4 | 0 | 2 days |
| 2 | Migration §5, `AppScope` + `TenantScopedRepository` §9 | 1 | 4 days |
| 3 | Token types §6, `/v1/oauth/token` §7 | 2 | 4 days |
| 4 | `require_scopes` §8, applied to `/v1` — **closes P1** | 3 | 3 days |
| 5 | Authorize + consent approval §7 | 3 | 3 days |
| 6 | Idempotency §12 — **closes P4** | 2 | 1 day |
| 7 | Rate limiting §11 | 3 | 2 days |
| 8 | Webhook worker §10 | callback persistence fix | 3 days |
| 9 | Consent UI + console §14, portal §13 | 3, 5 | 8 days, parallel |

Backend critical path is packages 0→1→2→3→4, about three weeks. Frontend can
start package 9's static shell after package 3 fixes the token contract.

**Package 2 is where the risk is.** It is the migration plus the isolation
pattern, it touches every repository, and a mistake in it is a data leak rather
than a broken build. It deserves the most careful reviewer and it should not be
compressed to make the schedule work.

---

## 18. Out of scope, deliberately

- **Live bank rails.** Phase 6, gated on a bank agreement. Phase 3 ships a
  sandbox against simulated CBS adapters. Say so in the developer docs — a
  developer who discovers it after integrating will not integrate again.
- **Mini-app platform.** Phase 7.
- **Fraud and risk ports.** Phase 4. `FraudCheckPort` wires in before
  `order_payment`; nothing in Phase 3 should assume it exists.
- **FX.** Deliberately unbuilt. Cross-border is a separate licence and a
  separate business.
- **Key rotation** for `JWT_SECRET_KEY` and `FIN_ENCRYPTION_KEY`. A real gap
  ([REMAINING.md](REMAINING.md) §5) that Phase 3 makes worse by adding
  `webhook_secret` and `client_secret_hash` to the set of things that cannot be
  rotated. Worth scheduling immediately after.

## 19. Two questions for counsel

Unchanged from [ARCHITECTURE.md](ARCHITECTURE.md) §9, and both now on the
critical path rather than adjacent to it — Phase 3 is what makes them concrete:

- Does orchestration-plus-revenue-share trigger NBE payment-operator licensing?
  Onboarding third parties is the step that makes this visible.
- Does the pseudonymity design satisfy Ethiopia's personal data protection
  regime? Phase 3 is the first time personal data leaves EUPI's own surfaces,
  which is the moment the answer starts to matter.

Both run on legal timelines. Start them at package 0, not package 9.
