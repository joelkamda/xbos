# M4.5 — XafPay orchestration adapter

## Outcome

M4.5 connects the canonical XBOS payment attempt and settlement authorities to
XafPay without moving gateway-specific behavior into the finance kernel. It
adds no table, route, migration, provider credential store, or live-network
test. The canonical Alembic head remains `m44_payment_patterns_014`.

In plain language: XBOS continues to decide what a payment means. XafPay is an
external messenger that starts a payment and reports evidence back. A gateway
callback can never rewrite XBOS history or bypass the existing payment engines.

## Boundary

All XafPay code lives under `core/integrations/xafpay`. The adapter translates
the current gateway wire contract; the orchestration service applies verified
results through the existing M4.2 attempt engine and M4.3 settlement engine.
The transport is injected, so production HTTP, secrets, retries, and deployment
configuration remain outside the finance domain.

## Initiation

- XAF amounts must be positive whole units.
- `mtn_momo` maps to XafPay rail `mtn`; `orange_money` maps to `orange`.
- The XBOS payment-attempt UUID becomes XafPay `externalId`.
- `Idempotency-Key` is mandatory.
- API keys are accepted only at the call boundary and are never canonicalized.
- The returned gateway-intent UUID becomes the immutable external attempt
  reference through M4.2 transitions.

## Callback authentication and replay

The caller must supply the exact raw body, `X-Xafpay-Event-Id`,
`X-Xafpay-Signature`, and a configured callback secret. Verification is
HMAC-SHA256 over the exact bytes and uses constant-time comparison. Missing
material fails closed.

The immutable `provider_callback_events` table remains the replay authority.
The tuple `(tenant, provider account, event reference)` is unique:

- identical bytes return the original result;
- different bytes under the same event reference raise a conflict;
- invalid signatures are preserved as rejected evidence without changing a
  payment attempt;
- later callbacks are preserved as ignored when they would regress a terminal
  attempt.

## Successful settlement

A verified success is processed in one database transaction:

1. preserve the immutable callback evidence;
2. advance the canonical attempt to `succeeded` through M4.2;
3. create the incoming settlement through M4.3;
4. confirm it as final and available through M4.3.

Any failure rolls back the complete callback effect. No outbox dispatch occurs
in M4.5.

## Explicit exclusions

- no public HTTP route;
- no XafPay or Tranzak policy in `core/domain/finance`;
- no live call in contract tests or the disposable verifier;
- no gateway credential persistence;
- no fee or reserve recognition (M4.6);
- no changes to customer-payment truth based on net provider settlement.

## Acceptance

`scripts/verify_m45_xafpay_orchestration.py` checks the development database
read-only, clones it to `xbos_track_b_m45_xafpay_test`, uses an injected fake
transport, exercises initiation, signature verification, replay, conflict,
out-of-order delivery, settlement, scope checks, immutability, and rollback,
then drops the clone. Development payment and financial tables must remain
empty and the canonical head must remain M4.4.

## Next step

M4.6 should model provider fees, reserves, net settlement, and later provider
adjustments as separate financial facts. It must not alter the gross customer
payment or the callback evidence established here.
