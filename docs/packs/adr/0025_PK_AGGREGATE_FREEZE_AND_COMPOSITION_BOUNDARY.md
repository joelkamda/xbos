# ADR 0025 — Freeze PK0-PK6 as composition authority, not business authority

## Status

Accepted by the PK Aggregate candidate; final only after the authoritative operator gate passes.

## Decision

Freeze PK0-PK6 with no new migration and no new business capability. The Pack Platform owns pack manifests, lifecycle, extension declarations, connector declarations, conformance evidence, template versions, tenant template bindings, allowlisted overrides and explicit upgrade history.

It does not own any business truth referenced by those declarations.

## Provider-edge decision

Outbound provider payout execution remains outside frozen Finance unless implementation proves a universal financial invariant cannot be represented truthfully through existing canonical authorities. Provider routing, beneficiary tokens, provider idempotency references, callbacks and finality evidence are edge concerns. Canonical outgoing settlement, payable/disbursement, allocation, treasury and journals remain Finance concerns.

A provider execution record must never manufacture financial meaning. A provider state may authorize settlement only when it reaches the configured finality threshold. Unknown or ambiguous outcomes must be recovered by stable external identity/lookup where possible and must never be blindly resubmitted.

## Consequences

1. Packs cannot become a dynamic Python plugin or arbitrary SQL execution mechanism.
2. Certification evidence cannot grant runtime authorization; PC5 remains the authorization authority.
3. Template application produces a deterministic plan and requires explicit tenant acceptance.
4. Tenant template versions remain pinned until an explicit upgrade plan is accepted.
5. Two tenants may diverge through permitted overrides without mutating the template or each other.
6. Payments-only composition may hide Accounting UI while retaining the Finance kernel.
7. PA consumes this frozen composition platform rather than redefining it.
