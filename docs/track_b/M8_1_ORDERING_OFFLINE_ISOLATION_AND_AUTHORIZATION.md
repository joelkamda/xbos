# M8.1 — Ordering, offline resilience, isolation and authorization

M8.1 adversarially proves accepted kernel behavior without adding schema or authority.

- Economic occurrence and governed business date remain authoritative when facts arrive late or out of order; server receipt/recording time remains separately inspectable.
- Offline facts require stable source identity and an exact payload fingerprint. Identical replay is one effect; conflicting replay fails closed.
- A projection cannot mix tenant or organization scope. The canonical organization-authority check fails a missing, inactive or cross-tenant organization reference with `organization_unit_not_active` before any source-record lookup or write.
- Existing RBAC codes and domain engines remain permission authority. Reconciliation close/reopen continues through M6.3, with explicit approval, evidence, actor attribution and immutable history.
- A late fact intersecting a closed window must use accepted correction/reopen controls. It cannot rewrite historical truth.
- Writer routing is unchanged, cutover is not authorized, and R6 remains live-cutover owner.

The single gate runs focused contracts, a disposable PostgreSQL late-arrival/replay/isolation exercise, the full regression suite and whitespace validation.
