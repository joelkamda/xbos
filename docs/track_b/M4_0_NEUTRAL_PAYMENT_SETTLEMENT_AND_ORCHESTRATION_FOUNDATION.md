# M4.0 — Neutral Payment, Settlement, and Orchestration Foundation

## Outcome

M4.0 extends the single canonical Alembic lineage from
`m34_obligation_aging_010` to `m40_payment_foundation_011`. It installs empty,
tenant-scoped persistence structures for the payment and settlement domain. It
does not activate a writer, migrate legacy payment rows, expose routes, dispatch
messages, or create development financial records.

## Why the canonical tables use explicit names

The source-state baseline already contains `payments`, `payment_intents`, and
`payment_attempts`. Those tables continue to support the legacy WND path. M4.0
does not overwrite, rename, or reinterpret them. The new authorities are named
`canonical_payment_*` until an explicit, separately approved writer cutover.

This parallel structure keeps Track A stable while Track B becomes provably
complete.

## Installed authorities

| Authority | Meaning |
|---|---|
| `canonical_payment_requests` | A shareable or operator-created request for value. |
| `canonical_payment_intents` | A provider-neutral goal to collect a stated amount. |
| `canonical_payment_tenders` | One method/amount component; multiple rows support mixed tender. |
| `canonical_payment_attempts` | One execution attempt with method, rail, orchestrator, and provider kept distinct. |
| `provider_callback_events` | Immutable provider evidence with tenant-scoped deduplication. |
| `payment_settlements` | Verified movement of value into or out of an operational account. |
| `payment_settlement_reversals` | Append-only compensation against an original settlement. |

The existing `payment_provider_accounts` table remains external provider identity
authority. The existing `operational_financial_accounts` table remains internal
treasury and reconciliation authority. They are deliberately not collapsed.

## Provider neutrality

The model separates four dimensions:

- payment method: cash, mobile money, card, bank, credit, or another customer choice;
- payment rail: the network or channel that moves value;
- orchestrator: the routing and normalization layer;
- underlying provider: the institution or processor executing the movement.

XafPay is one supported orchestrator adapter. Direct MTN, Orange, bank, card, or
other provider connections remain possible without changing canonical payment
or settlement semantics.

## Database protections

- All money uses `NUMERIC(24,8)`.
- Tenant, organization, and currency scope is carried through composite foreign keys.
- Settlement net value must equal gross value less fees.
- External finality requires provider callback evidence; cash and internal credit
  use explicit non-external finality paths.
- Provider callback identity is unique per tenant, provider account, and provider
  event reference.
- Provider evidence and settlement reversals are immutable.
- Settlement operational-account currency must match.
- M3 `value_sources.payment_settlement_public_id` now has its deferred foreign key
  to canonical settlement authority.
- Deletes use `RESTRICT` and no cascade deletes financial evidence.

## M3 checkpoint compatibility

M3 remains frozen at `m34_obligation_aging_010`. Its manifest and component
digests do not change. M4.0 updates the M3 validator and consolidated development
verifier so that the approved M3 lineage is treated as an immutable prefix of a
single later lineage, not as a permanent repository head.

## Deferred to later M4 increments

- M4.1 typed request, intent, and standalone-payment commands;
- M4.2 mixed-tender execution and transactional attempt processing;
- M4.3 callback authentication, durable inbox routing, and outbox publication;
- M4.4 settlement finality, fees, reserves, and reconciliation;
- M4.5 retry, outage, delayed, and out-of-order event recovery;
- M4.6 deterministic payment and settlement traces;
- M4.7 consolidated acceptance and freeze;
- any WND writer cutover or public route.

## Acceptance evidence

The single acceptance runner verifies static contracts, the one Alembic head,
the exact M3 starting revision, read-only development emptiness, a fresh
disposable upgrade, schema inventory, legacy coexistence, downgrade/upgrade
reconstruction, development upgrade with unchanged counts, the full regression
suite, and Git whitespace checks.
