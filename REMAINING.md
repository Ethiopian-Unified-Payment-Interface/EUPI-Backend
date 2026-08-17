# Backend — Remaining Work

What is not built, ordered by what would hurt most if skipped. Companion to
[CHANGES.md](CHANGES.md), which covers what was done.

Phases refer to the delivery plan: **0** security, **1** ledger & fees,
**2** consent & pseudonyms, **3** developer platform, **4** pluggable services,
**5** infrastructure, **6** live rails, **7** super app as distribution.
Phases 0–2 are complete.

---

## 1. Live correctness bugs

### Two of six bank rails can never be selected

`_RAIL_COSTS` and `_BASE_LATENCY_MS` in
[`smart_router.py`](backend/infrastructure/adapters/router/smart_router.py) list
COOP, CBE, WEGAGEN, and AWASH — but **not ABYSSINIA or BERHAN**. Those fall to
the `Decimal("5.00")` default, roughly double every other rail, so the composite
score can never favour them. A third of the rails are silently disabled.

*Fix: add both to each map. Hours.*

### The payment cache is per-process

`_payment_store` in [`api_v1/payments.py`](backend/presentation/api_v1/payments.py)
is a module-level `dict`. Run two uvicorn workers or two containers and a payment
initiated on one is invisible to the other — verify/order against it returns 404.

It works today only because a single worker is running. This blocks horizontal
scaling, and when it bites it will present as intermittent, unreproducible
failures rather than an obvious error.

*Fix: read through the repository rather than the cache, or move the cache to
shared storage. The repository already persists every payment.*

---

## 2. Nothing delivers webhooks

`WebhookEventRecord`, `create_webhook_event`, and `get_pending_webhooks` all
exist. **Nothing calls the getter.** There is no delivery loop, no HMAC signing,
no retry with backoff.

So a third party can never be told a payment settled. The async settlement model
is non-functional for anyone but the Super App, which polls instead.

This is a prerequisite for the developer platform, not an add-on to it.

---

## 3. Phase 3 — the developer platform

The actual product. None of it exists.

| Missing | Notes |
|---|---|
| OAuth2 client credentials | `POST /v1/oauth/token`, `typ: tpp_access` |
| Scope enforcement | `require_scopes(...)` on `/v1`; `AISService` already documents a `required_scope` concept to extend |
| **`app_id` tenancy scoping** | **The highest-risk change in the plan** — see below |
| Developer onboarding | Self-service registration → KYB → app creation → client secret shown once |
| Scope request + admin approval | Deny-by-default; ungranted scope returns 403 even with a valid token |
| Rate limits and quotas | Per `client_id`. **None exist anywhere today.** |
| Idempotency on the TPP path | See below |
| Developer console | Self-service keys, scopes, usage, logs — distinct from the internal admin portal |

### Tenancy scoping is the dangerous part

`app_id` columns exist on `ledger_entries` and `user_app_identities`, but nothing
populates or filters on them. One missed query filter leaks one developer's
transaction data into another's.

It must be enforced by a repository-level base query that **cannot be bypassed**,
not by reviewer discipline, with explicit isolation tests proving app A cannot
read app B's data.

### Idempotency is only half done

`end_to_end_id` is documented as an idempotency key and the unique constraint
enforces it — but a duplicate raises `IntegrityError` → 500 rather than returning
the original payment. The pre-flight check was only added to the Super App
transfer route, where a single call now moves money.

The TPP `POST /v1/payments/initiate` path needs the same treatment.

---

## 4. Phase 4 — pluggable service ports

Architecturally cheap given the existing hexagonal design; strategically
important for the platform story. None of the ports exist yet.

| Port | First implementation | Status |
|---|---|---|
| `FraudCheckPort` | In-house rules: velocity, amount thresholds, first-time recipient | Not built. Wire into the payment flow **before** `order_payment` |
| `RiskScoringPort` | Null implementation, vendor later | Not built |
| `CreditScorePort` | Null implementation; NBE credit reference bureau later | Not built |
| `FxRatePort` | Interface only — **deliberately no implementation** | Not built |

**Cross-border FX stays deferred.** Ethiopian forex is tightly controlled and
cross-border remittance is a separate licence and a separate business. The seam
should exist so it is not a rewrite later; nothing should be built behind it.

---

## 5. Operational readiness

### No CI in any repo

100 tests exist and nothing runs them on push. This is the cheapest high-value
item on the list — roughly a day, and it stops regressions permanently.

Needs: ruff, mypy, pytest, image build on the backend.

### No structured logging, and no PII redaction

PII is masked in API *responses*, but logs are a separate egress path. A
`logger.info(..., extra={"username": ...})`, or an exception carrying a request
payload, can still write a Fayda number to disk.

Needs JSON logging, request IDs, and a redaction filter — the filter especially,
since it is the only thing that catches the case nobody remembered to mask.

### Vault key rotation is a one-way door

Changing `FIN_ENCRYPTION_KEY` makes existing ciphertext unreadable; changing
`FIN_BLIND_INDEX_PEPPER` makes accounts unfindable by FIN. Rotation needs a
key-version column and a re-encryption pass.

Worth building **before** you are in a position where rotating is necessary.

### No reconciliation against an external source

The per-bank position report exists, but nothing compares it to a bank statement.
That is the first thing a partner will ask for.

---

## 6. Test debt

`e2e_test.py` was **never ported**. It is 604 lines requiring a manually started
server, so it does not run in CI. Its 14 scenario groups contain genuinely good
assertions the pytest suite does not duplicate — replay attacks, tampered tokens,
impersonation, cross-user guards. Worth porting rather than rewriting.

Also missing: contract tests that snapshot the OpenAPI schema and validate the
Flutter and portal endpoint constants against it. That would have caught the ten
portal endpoints calling routes that were never implemented.

---

## 7. Commercial and product decisions

These are not engineering calls.

- **Fee rules are placeholder pricing.** 2.50 flat intra-bank, 5.00 + 0.10%
  capped cross-bank, seeded with a loud warning. Dev defaults, not negotiated
  rates.
- **Direct (non-handle) payments cannot complete.** They need a Fayda consent
  token the Super App does not obtain. Extending PIN-as-consent there is a
  separate decision, since the payee is not another EUPI user.
- **Bank adapters are all simulated.** The mock/real seam is clean — see the
  commented `httpx` blocks in `coop_cbs.py` — but no live CBS integration exists.

---

## 8. Phase 6 — live rails (gated on a bank agreement)

No engineering unblocks this. The architecture is arranged so the first signed
bank means an adapter swap behind `BankPort`: weeks of integration, not months of
re-architecture.

**Intra-bank first** is the wedge — same-CBS transfers need no interbank
settlement, so one agreement yields a complete live product for that bank's
customers.

Cross-bank should interoperate with **EthSwitch** rather than rebuilding national
interbank settlement. Confirm their instant-payment roadmap before designing
around it.

Also needed here: live reconciliation against the bank's statements, a go-live
runbook, and incident response.

---

## 9. Two questions for counsel

Neither is engineering's to answer, and both run on legal rather than sprint
timelines — so they are worth starting early.

- Does orchestration-plus-revenue-share itself trigger NBE payment-operator
  licensing?
- Does the Phase 2 pseudonymity design satisfy Ethiopia's personal data
  protection regime? It is built to be defensible, but that judgement is not
  ours to make.

---

## Suggested order

1. Smart Router rails + payment cache — hours, both are live bugs
2. CI on all three repos — a day, protects everything after it
3. Webhook delivery — prerequisite for Phase 3
4. **Phase 3 developer platform**, tenancy scoping first and most carefully
5. Structured logging with redaction — in parallel, cheap
6. Phase 4 service ports — cheap, and makes the platform story credible

Items 1–3 are roughly a week and depend on nobody. Phase 3 is the four-week block
that turns this into a product.
