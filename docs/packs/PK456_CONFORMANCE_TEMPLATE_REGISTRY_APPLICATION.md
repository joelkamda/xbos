# PK456 — Pack Conformance, Template Registry, Application and Upgrade Governance

PK456 completes PK4-PK6 without changing Finance or Shared Operations semantics.

## PK4 — conformance and certification

Certification is immutable evidence that a specific immutable pack version passed the declared conformance suite. It is not a permission grant and cannot replace runtime authorization. The required evidence covers architecture boundaries, tenant isolation, migration compatibility, authorization, semantics, Finance, Shared Operations, XA and manifest integrity. Finance-specific proof reuses the frozen M8.4 pack-financial-conformance authority rather than creating a second financial verifier.

## PK5 — industry/profile/template registry

Template classification references PC3 semantic identity. PK owns only template composition identity and immutable template versions. A template can declare required, optional and incompatible packs, allowed merchant override paths, configuration defaults, terminology, semantic references and XA metadata. A template cannot disable the Neutral Finance kernel, even when the Accounting workspace is not exposed.

## PK6 — deterministic application and upgrades

Template application is a two-step process: deterministic preflight plan, then explicit acceptance of the exact plan fingerprint. Required and selected optional pack versions must exist, be certified and be active for the tenant before the template pin is accepted. Incompatible packs fail closed. Merchant overrides are allowed only on template-declared paths and are tenant-local.

Template upgrades are never silent. The target version is immutable; an upgrade plan compares the pinned version with the target, preserves only still-allowed merchant overrides, identifies conflicts and produces a deterministic plan hash. The tenant moves only after an explicit upgrade command against that plan. Append-only application/upgrade history preserves provenance.

## Payments-only neutrality proof

The `neutral.payments_only` example proves the critical product invariant: the Accounting, Sales, Inventory and Procurement workspaces may be absent while the Neutral Finance kernel remains active. Receive/Pay/Transfer product orchestration continues to reach existing canonical Finance/Treasury authorities. Provider-specific payout execution remains a typed product/integration concern and becomes canonical financial truth only when existing Finance settlement/finality authorities say so.

## Boundaries

- Pack = composition, never source-of-truth replacement.
- PC3 owns semantic identity.
- PC4 owns configuration/module/entitlement truth.
- PC5 owns authorization.
- SO1-SO10 own operational truths.
- Neutral Finance owns obligations, settlement, allocation, journals and reconciliation.
- XA owns presentation-facing experience law.
- PK stores template intent, pinning, certification and merchant composition state only.
